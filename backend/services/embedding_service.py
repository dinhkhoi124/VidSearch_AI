"""Text/image embedding service.

Encodes queries into the SAME vector space as the FAISS index built in Step 4/5.
Real backbones are loaded lazily via `transformers`. On a small GPU the model is
loaded in fp16 to fit VRAM; if CUDA still runs out of memory it falls back to CPU
(NOT to mock) so search stays meaningful. Only if the libraries/weights are missing
does it fall back to a deterministic mock vector.

Device can be forced with env EMBED_DEVICE = auto | cuda | cpu (default: auto).

Supported real models (must match the index you deployed):
    clip      -> openai/clip-vit-large-patch14-336    (768-d)
    siglip    -> google/siglip2-so400m-patch14-384    (1152-d)
    siglip512 -> google/siglip2-so400m-patch16-512    (1152-d, res cao - vật thể nhỏ)
    metaclip  -> facebook/metaclip-h14-fullcc2.5b     (1024-d, thay clip 2021 yếu)
    metaclip2 -> facebook/metaclip-2-worldwide-huge-quickgelu
                                                      (1024-d, MetaCLIP 2 worldwide,
                                                       300+ ngôn ngữ — cần transformers >= 4.56)
    jina      -> jinaai/jina-clip-v2                  (1024-d, đa ngữ có tiếng Việt)
"""
from __future__ import annotations

import hashlib
import threading
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from config import get_settings

settings = get_settings()

# Dimensionality per model - match your real index when you swap in real models
_DIMS = {
    "beit3": 768, "clip": 768, "siglip": 1152,
    "siglip512": 1152, "metaclip": 1024, "metaclip2": 1024, "jina": 1024,
}

# Số token text tối đa mỗi backbone chấp nhận (= text_config.max_position_embeddings).
# Chỉ liệt kê model mà tokenizer KHÔNG tự biết giới hạn này: metaclip2 dùng
# XLMRobertaTokenizer với model_max_length = sentinel 1e30, nên
# `truncation=True` không cắt gì cả ("no maximum length is provided ... Default
# to no truncation") và query dài quá 77 token làm vỡ position embedding lúc
# chạy. Phải truyền max_length tường minh.
_TEXT_MAX_LEN = {"metaclip2": 77}

# HuggingFace model id per key (only these have a real encoder)
_HF_NAME = {
    "clip": "openai/clip-vit-large-patch14-336",
    "siglip": "google/siglip2-so400m-patch14-384",
    "siglip512": "google/siglip2-so400m-patch16-512",
    "metaclip": "facebook/metaclip-h14-fullcc2.5b",
    # PHẢI trùng checkpoint đã build index (kaggle 04b): index hiện tại là bản
    # huge-378 (fine-tune 378px từ huge-quickgelu). Hai bản text tower gần nhau
    # nên lệch checkpoint vẫn "chạy được" — nhưng là chạy dưới sức, và không có
    # lỗi nào báo cho biết. Đổi bản build là phải đổi dòng này theo.
    "metaclip2": "facebook/metaclip-2-worldwide-huge-378",
    "jina": "jinaai/jina-clip-v2",
}

# Lazy singletons: model_key -> (processor, model, device) ; None means "use mock"
_loaded: dict[str, Optional[Tuple[object, object, str]]] = {}
_lock = threading.Lock()


def _resolve_device() -> str:
    pref = (settings.embed_device or "auto").lower()
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False
    if pref == "cpu":
        return "cpu"
    if pref == "cuda":
        return "cuda" if has_cuda else "cpu"
    return "cuda" if has_cuda else "cpu"  # auto


def _resolve_half(device: str) -> bool:
    """Whether to use fp16. auto = fp16 on cuda, fp32 on cpu (fp16 on CPU is unsupported/slow)."""
    pref = (settings.embed_dtype or "auto").lower()
    if pref in ("fp16", "float16", "half"):
        return device == "cuda"   # fp16 chỉ áp dụng trên GPU
    if pref in ("fp32", "float32", "full"):
        return False
    return device == "cuda"        # auto


def _shim_jina_transformers_compat() -> None:
    """Vá 2 khác biệt của transformers >= 5 mà remote code jina-clip-v2 (viết cho
    4.x) chưa theo kịp:
      1. `clip_loss` bị gỡ khỏi modeling_clip nhưng vẫn được import (chỉ dùng
         khi training) -> định nghĩa lại đúng hàm gốc.
      2. `AutoModel.from_config` không còn nuốt kwarg `code_revision` mà đẩy
         thẳng xuống __init__ của model con (XLMRobertaLoRA vỡ) -> thử lại
         không kèm kwarg đó khi gặp TypeError."""
    import torch
    import torch.nn.functional as F
    import transformers.models.clip.modeling_clip as clip_mod
    from transformers import AutoModel as _AM

    if not hasattr(clip_mod, "clip_loss"):
        def _contrastive_loss(logits):
            return F.cross_entropy(logits, torch.arange(len(logits), device=logits.device))

        def clip_loss(similarity):
            return (_contrastive_loss(similarity) + _contrastive_loss(similarity.t())) / 2.0

        clip_mod.clip_loss = clip_loss

    if not getattr(_AM.from_config, "_jina_shim", False):
        _orig = _AM.from_config.__func__

        def _from_config(cls, config, **kwargs):
            try:
                return _orig(cls, config, **kwargs)
            except TypeError:
                if "code_revision" not in kwargs:
                    raise
                kwargs.pop("code_revision")
                return _orig(cls, config, **kwargs)

        _from_config._jina_shim = True
        _AM.from_config = classmethod(_from_config)


def _load_on(model: str, device: str) -> Tuple[object, object, str]:
    """Load (processor, model) onto `device`. fp16 on cuda (fits small GPUs)."""
    import torch
    from transformers import AutoModel, AutoProcessor

    name = _HF_NAME[model]
    if model == "jina":
        # jina-clip-v2 ships its own remote code with encode_text/encode_image
        # (preprocessing included) - no separate AutoProcessor.
        _shim_jina_transformers_compat()
        # transformers >= 5 materialise model từ meta-device mà KHÔNG chạy
        # __init__, nên mọi buffer non-persistent (lora_dropout_mask, rope
        # freqs_cos/sin...) chứa memory rác - lúc thành NaN, lúc thành số sai
        # âm thầm. Lấy giá trị đúng từ một bản khởi tạo bằng __init__ thật
        # (from_config), chỉ giữ lại các buffer đó (vài MB) rồi chép sang.
        import torch
        from transformers import AutoConfig

        buf_cache = settings.data_path / "jina_nonpersistent_buffers.pt"
        good_bufs = None
        if buf_cache.exists():
            try:
                good_bufs = torch.load(buf_cache)
            except Exception:
                good_bufs = None
        if good_bufs is None:
            # AutoModel.from_config(trust_remote_code=True) trên transformers 5.x
            # truyền lạc kwarg `code_revision` vào __init__ của remote model,
            # nên resolve class trực tiếp từ dynamic module.
            from transformers.dynamic_module_utils import get_class_from_dynamic_module

            cfg = AutoConfig.from_pretrained(name, trust_remote_code=True)
            ref_cls = get_class_from_dynamic_module(cfg.auto_map["AutoModel"], name)
            ref = ref_cls(cfg)
            persistent = set(ref.state_dict().keys())
            good_bufs = {
                n: b.detach().clone()
                for n, b in ref.named_buffers()
                if n not in persistent
            }
            del ref
            try:
                torch.save(good_bufs, buf_cache)
            except Exception:
                pass

        mdl = AutoModel.from_pretrained(name, trust_remote_code=True)
        for bname, buf in mdl.named_buffers():
            if bname in good_bufs:
                buf.data.copy_(good_bufs[bname].to(buf.dtype))
        if _resolve_half(device):
            mdl = mdl.half()
        mdl = mdl.to(device).eval()
        return None, mdl, device
    proc = AutoProcessor.from_pretrained(name)
    # Nạp THẲNG fp16 thay vì materialise fp32 rồi .half(): cách cũ dựng bản
    # fp32 đầy đủ trong RAM (so400m ~3.5GB) rồi convert sang bản fp16 thứ hai.
    # Đo trên siglip2-so400m-512: 6.0s -> 1.1s.
    kwargs = {"dtype": torch.float16} if _resolve_half(device) else {}
    mdl = AutoModel.from_pretrained(name, **kwargs)
    mdl = mdl.to(device).eval()
    return proc, mdl, device


def backbone_catalog() -> dict:
    """{model: {"hf": <tên HuggingFace>, "dim": <chiều vector>}} cho MỌI backbone
    có encoder thật. Có index hay chưa là chuyện của routers/catalog.py — nó đọc
    đĩa; ở đây chỉ trả những gì code encode được."""
    return {name: {"hf": hf, "dim": _DIMS.get(name, 0)} for name, hf in _HF_NAME.items()}


def has_real_encoder(model: str) -> bool:
    """True when `model` has real weights loaded (not the mock fallback)."""
    return _get(model) is not None


def _get(model: str) -> Optional[Tuple[object, object, str]]:
    """Return (processor, model, device) for a real backbone, or None for mock."""
    if model not in _HF_NAME:
        return None
    with _lock:
        if model not in _loaded:
            device = _resolve_device()
            try:
                _loaded[model] = _load_on(model, device)
                print(f"[embedding] loaded {model} -> {_HF_NAME[model]} on {device}")
            except Exception as e:
                # CUDA OOM (or anything) -> retry on CPU before giving up to mock
                if device == "cuda":
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    try:
                        _loaded[model] = _load_on(model, "cpu")
                        print(f"[embedding] cuda failed ({e!r}); loaded {model} on CPU")
                    except Exception as e2:
                        print(f"[embedding] could not load {model} ({e2!r}); using mock")
                        _loaded[model] = None
                else:
                    print(f"[embedding] could not load {model} ({e!r}); using mock")
                    _loaded[model] = None
        return _loaded[model]


def _prep_inputs(inputs, mdl, device):
    """Move processor outputs to the model's device & floating dtype (fp16/fp32)."""
    import torch

    dtype = next(mdl.parameters()).dtype
    out = {}
    for k, v in inputs.items():
        v = v.to(device)
        if torch.is_floating_point(v):
            v = v.to(dtype)
        out[k] = v
    return out


def _to_unit_np(out) -> np.ndarray:
    """Pool a transformers output (or tensor) -> L2-normalised float32 numpy (N, dim)."""
    import torch

    if torch.is_tensor(out):
        emb = out
    elif getattr(out, "pooler_output", None) is not None:
        emb = out.pooler_output
    elif getattr(out, "last_hidden_state", None) is not None:
        emb = out.last_hidden_state.mean(dim=1)
    else:
        raise TypeError(f"Unexpected feature output: {type(out)}")
    emb = emb.detach().to(torch.float32).cpu().numpy()
    return emb / (np.linalg.norm(emb, axis=-1, keepdims=True) + 1e-9)


def _mock_vector(seed_bytes: bytes, model: str) -> np.ndarray:
    dim = _DIMS.get(model, 512)
    h = hashlib.sha256(seed_bytes).digest()
    rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
    v = rng.standard_normal(dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _jina_to_unit_np(emb) -> np.ndarray:
    """jina encode_* output (numpy/tensor) -> L2-normalised float32 (dim,)."""
    import torch

    if torch.is_tensor(emb):
        emb = emb.detach().to(torch.float32).cpu().numpy()
    emb = np.asarray(emb, dtype=np.float32).reshape(-1)
    return emb / (np.linalg.norm(emb) + 1e-9)


def encode_text(query: str, model: str = "siglip") -> np.ndarray:
    got = _get(model)
    if got is None:
        return _mock_vector(query.encode("utf-8"), model)

    import torch

    processor, mdl, device = got
    if model == "jina":
        with torch.no_grad():
            return _jina_to_unit_np(mdl.encode_text([query]))
    with torch.no_grad():
        if model.startswith("siglip"):
            # SigLIP expects fixed-length padding
            inputs = processor(
                text=[query], padding="max_length", max_length=64,
                truncation=True, return_tensors="pt",
            )
        elif model in _TEXT_MAX_LEN:
            inputs = processor(
                text=[query], padding=True, max_length=_TEXT_MAX_LEN[model],
                truncation=True, return_tensors="pt",
            )
        else:
            inputs = processor(
                text=[query], padding=True, truncation=True, return_tensors="pt",
            )
        inputs = _prep_inputs(inputs, mdl, device)
        emb = _to_unit_np(mdl.get_text_features(**inputs))
    return emb[0]


def encode_image(image: Image.Image, model: str = "siglip") -> np.ndarray:
    got = _get(model)
    if got is None:
        buf = image.resize((32, 32)).tobytes()
        return _mock_vector(buf, model)

    import torch

    processor, mdl, device = got
    if model == "jina":
        with torch.no_grad():
            return _jina_to_unit_np(mdl.encode_image([image.convert("RGB")]))
    with torch.no_grad():
        inputs = processor(images=[image.convert("RGB")], return_tensors="pt")
        inputs = _prep_inputs(inputs, mdl, device)
        emb = _to_unit_np(mdl.get_image_features(**inputs))
    return emb[0]
