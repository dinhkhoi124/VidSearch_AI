"""Stage-2 re-ranking on top of first-stage retrieval.

Two independent rerankers, both lazy singletons and both optional:
  * text   - a sentence-transformers CrossEncoder (settings.text_rerank_model,
             default BAAI/bge-reranker-v2-m3) scoring (query, document) pairs.
             Used by OCR and ASR search, where the document is the OCR text /
             ASR window the candidate matched on.
  * visual - a BLIP-family image-text matching head (settings.visual_rerank_model,
             default Salesforce/blip2-itm-vit-g) scoring (query, keyframe image)
             pairs with real cross-attention. Used by /search_text on top of
             SigLIP/CLIP dual-encoder retrieval. Query must be English, same as
             the SigLIP query. Both BLIP and BLIP-2 checkpoints are supported -
             see _visual_kind for the two calling conventions.

Only the top `settings.rerank_candidates` hits are re-scored. Blending keeps
head/tail score ordering intact: both signals are min-max normalised over the
head, mixed with alpha, then mapped back into the head's original score range,
so re-ranked hits stay comparable with (and above) the un-reranked tail.

If a model cannot be loaded (missing weights, OOM, disabled via "none") the
rerank pass returns None and callers keep the retrieval order - the API never
breaks because of this service. Device/dtype follow EMBED_DEVICE/EMBED_DTYPE
like the other embedding services.
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

from config import get_settings

settings = get_settings()

# Lazy singletons; None after a failed/disabled load attempt.
_text_model: Optional[object] = None
_text_tried = False
# (processor, model, device, kind) - kind xem _visual_kind.
_visual: Optional[Tuple[object, object, str, str]] = None
_visual_tried = False
_lock = threading.Lock()

_TEXT_BATCH = 16
# Đo trên RTX 3060 12GB, fp16, 100 ảnh: blip2 batch 4 -> 3.76s (2.55GB VRAM),
# 16 -> 3.41s (2.65GB), 32 -> 3.45s (2.80GB). ViT-g nghẽn ở tính toán chứ không
# ở kích thước lô, nên qua 16 là hết lợi; lấy 16 vì rẻ VRAM mà nhanh hơn 9%.
# crossencoder là model 2B+ sinh token, để nhỏ cho an toàn VRAM.
_VISUAL_BATCH = {"blip": 8, "blip2": 16, "crossencoder": 4}


def _disabled(name: str) -> bool:
    return name.strip().lower() in ("", "none", "off", "disabled", "false", "0")


def _visual_kind(name: str) -> str:
    """Họ kiến trúc của `name`. Ba họ khác nhau ở CẢ cách gọi lẫn tên trường
    kết quả, nên phải biết trước lúc load chứ không đoán lúc chấm điểm:

      blip         -> BlipForImageTextRetrieval,  mdl(**inputs).itm_score
      blip2        -> Blip2ForImageTextRetrieval, cần use_image_text_matching_head=True,
                      kết quả ở .logits_per_image
      crossencoder -> sentence-transformers CrossEncoder đa phương thức
                      (Qwen3-VL-Reranker, llama-nemotron-rerank-vl, jina-reranker-m0,
                      MonoQwen2-VL): mdl.predict([(query, ảnh), ...]) -> điểm

    blip/blip2 trả logit 2 lớp (N, 2), lớp 1 = khớp; crossencoder trả thẳng một
    điểm mỗi cặp. Thang điểm giữa các họ không so được với nhau, nhưng blend()
    chuẩn hoá min-max trước khi trộn nên không ảnh hưởng.
    """
    n = name.lower()
    if "blip2" in n:
        return "blip2"
    if "rerank" in n or "monoqwen" in n:
        return "crossencoder"
    return "blip"


def _resolve_device() -> str:
    pref = (settings.embed_device or "auto").lower()
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False
    if pref == "cpu":
        return "cpu"
    return "cuda" if has_cuda else "cpu"


def _use_half(device: str) -> bool:
    pref = (settings.embed_dtype or "auto").lower()
    if pref in ("fp32", "float32", "full"):
        return False
    return device == "cuda"


def _get_text():
    """CrossEncoder for (query, doc) pairs, or None (-> keep retrieval order)."""
    global _text_model, _text_tried
    if _text_tried:
        return _text_model
    with _lock:
        if _text_tried:
            return _text_model
        _text_tried = True
        name = (settings.text_rerank_model or "").strip()
        if _disabled(name):
            print("[rerank] text reranker disabled via TEXT_RERANK_MODEL")
            return None
        try:
            import torch
            from sentence_transformers import CrossEncoder

            device = _resolve_device()
            kwargs = {"dtype": torch.float16} if _use_half(device) else {}
            _text_model = CrossEncoder(
                name, device=device, max_length=512, model_kwargs=kwargs
            )
            print(f"[rerank] loaded text reranker {name} on {device}")
        except Exception as e:  # noqa: BLE001 - any failure -> graceful skip
            print(f"[rerank] text reranker unavailable ({e!r}); skipping rerank")
            _text_model = None
        return _text_model


def _get_visual():
    """(processor, ITM model, device, kind), or None (-> keep retrieval order)."""
    global _visual, _visual_tried
    if _visual_tried:
        return _visual
    with _lock:
        if _visual_tried:
            return _visual
        _visual_tried = True
        name = (settings.visual_rerank_model or "").strip()
        if _disabled(name):
            print("[rerank] visual reranker disabled via VISUAL_RERANK_MODEL")
            return None
        try:
            import torch
            from transformers import AutoProcessor

            kind = _visual_kind(name)
            device = _resolve_device()
            kwargs = {"dtype": torch.float16} if _use_half(device) else {}

            if kind == "crossencoder":
                # Tự lo tokenizer/processor + chia lô, nên không có processor riêng.
                # trust_remote_code: các repo này ship modeling code của chúng.
                from sentence_transformers import CrossEncoder

                # max_pixels: trần token thị giác mỗi ảnh (họ Qwen-VL). Đây là
                # knob tốc độ chính chứ không phải batch - xem config.
                mp = settings.visual_rerank_max_pixels
                mdl = CrossEncoder(
                    name, device=device, trust_remote_code=True, model_kwargs=kwargs,
                    processor_kwargs={"max_pixels": mp} if mp else {},
                )
                _visual = (None, mdl, device, kind)
            else:
                if kind == "blip2":
                    from transformers import Blip2ForImageTextRetrieval as _Cls
                else:
                    from transformers import BlipForImageTextRetrieval as _Cls

                proc = AutoProcessor.from_pretrained(name)
                # Nạp thẳng fp16 thay vì fp32 rồi .half() - xem embedding_service.
                mdl = _Cls.from_pretrained(name, **kwargs)
                mdl = mdl.to(device).eval()
                _visual = (proc, mdl, device, kind)
            print(f"[rerank] loaded visual reranker {name} ({kind}) on {device}")
        except Exception as e:  # noqa: BLE001
            print(f"[rerank] visual reranker unavailable ({e!r}); skipping rerank")
            _visual = None
        return _visual


def text_available() -> bool:
    """Nạp (nếu chưa) và cho biết cross-encoder text có dùng được không."""
    return _get_text() is not None


def visual_available() -> bool:
    """Nạp (nếu chưa) và cho biết BLIP ITM có dùng được không."""
    return _get_visual() is not None


def _minmax(xs: List[float]) -> List[float]:
    lo, hi = min(xs), max(xs)
    span = hi - lo
    if span < 1e-9:
        return [0.5] * len(xs)
    return [(x - lo) / span for x in xs]


def blend(base: List[float], rerank: List[float], alpha: float) -> List[float]:
    """Mix normalised scores, then map back into the base score range.

    Staying inside [min(base), max(base)] keeps the re-ranked head comparable
    with any un-reranked tail that follows it (head min >= tail max holds
    before and after).
    """
    mixed = [
        alpha * r + (1.0 - alpha) * b
        for b, r in zip(_minmax(base), _minmax(rerank))
    ]
    lo, hi = min(base), max(base)
    span = (hi - lo) or 1e-6
    return [lo + m * span for m in mixed]


def rerank_text(query: str, docs: List[str]) -> Optional[List[float]]:
    """Cross-encoder relevance of each doc to the query, or None if unavailable."""
    model = _get_text()
    if model is None or not docs:
        return None
    try:
        scores = model.predict(
            [(query, d) for d in docs],
            batch_size=_TEXT_BATCH,
            show_progress_bar=False,
        )
        return [float(s) for s in scores]
    except Exception as e:  # noqa: BLE001 - e.g. CUDA OOM mid-request
        print(f"[rerank] text predict failed ({e!r}); keeping retrieval order")
        return None


def _rerank_crossencoder(query: str, images: List, mdl, batch_size: int) -> List[float]:
    """CrossEncoder đa phương thức: chấm thẳng cặp (query, PIL.Image).

    Ảnh thiếu bị loại khỏi lô rồi ghép lại điểm 0.0 theo đúng vị trí - điểm thô
    của họ này có thể ÂM (logit chưa qua sigmoid), nên 0.0 không còn là "đáy"
    như ở blip. Đặt ảnh thiếu xuống dưới min thay vì đúng 0.
    """
    idx = [i for i, im in enumerate(images) if im is not None]
    if not idx:
        return [0.0] * len(images)

    raw = mdl.predict(
        [(query, images[i]) for i in idx],
        batch_size=batch_size,
        prompt=(settings.visual_rerank_prompt or None),
        show_progress_bar=False,
    )
    raw = [float(x) for x in raw]
    floor = min(raw) - 1.0
    scores = [floor] * len(images)
    for i, s in zip(idx, raw):
        scores[i] = s
    return scores


def rerank_visual(query: str, images: List) -> Optional[List[float]]:
    """ITM match probability per image, or None if unavailable.

    `images` = list of PIL.Image (None = missing). Missing/unreadable images
    score 0.0 so they sink without breaking the batch.
    """
    got = _get_visual()
    if got is None or not images:
        return None
    proc, mdl, device, kind = got
    batch_size = _VISUAL_BATCH[kind]

    if kind == "crossencoder":
        try:
            return _rerank_crossencoder(query, images, mdl, batch_size)
        except Exception as e:  # noqa: BLE001
            print(f"[rerank] crossencoder predict failed ({e!r}); keeping retrieval order")
            return None

    try:
        import torch

        scores = [0.0] * len(images)
        loaded: List[Tuple[int, "object"]] = []
        for i, img in enumerate(images):
            if img is not None:
                loaded.append((i, img))

        dtype = next(mdl.parameters()).dtype
        with torch.no_grad():
            for start in range(0, len(loaded), batch_size):
                batch = loaded[start : start + batch_size]
                inputs = proc(
                    images=[img for _, img in batch],
                    text=[query] * len(batch),
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                )
                inputs = {
                    k: v.to(device).to(dtype) if torch.is_floating_point(v) else v.to(device)
                    for k, v in inputs.items()
                }
                # Cả hai họ đều trả logit 2 lớp (N, 2), lớp 1 = khớp; chỉ khác
                # chỗ lấy ra. BLIP-2 mặc định chạy nhánh ITC (cosine) - không
                # bật cờ thì mất đúng phần cross-attention là lý do rerank.
                if kind == "blip2":
                    logits = mdl(**inputs, use_image_text_matching_head=True).logits_per_image
                else:
                    logits = mdl(**inputs).itm_score
                probs = torch.softmax(logits.float(), dim=-1)[:, 1]
                for (idx, _), p in zip(batch, probs.cpu().tolist()):
                    scores[idx] = float(p)
        return scores
    except Exception as e:  # noqa: BLE001
        print(f"[rerank] visual predict failed ({e!r}); keeping retrieval order")
        return None


def rerank_frames(query: str, raw: List[dict]) -> List[dict]:
    """Re-rank [{id, score}, ...] retrieval hits by BLIP ITM against frame images.

    Only the head (settings.rerank_candidates) is re-scored; the tail keeps its
    retrieval order below it. Returns the input unchanged if the model is off.
    """
    from services.metadata_service import frame_bytes_many, get_meta

    n = min(len(raw), settings.rerank_candidates)
    if n < 2:
        return raw
    head, tail = raw[:n], raw[n:]

    # Kéo cả 100 ảnh SONG SONG rồi mới decode. Tuần tự thì tổng = 100 × RTT,
    # vô hại khi media ở localhost nhưng thành hàng chục giây khi backend ở
    # Colab còn media ở máy nhà qua ngrok.
    metas = [get_meta(item["id"]) for item in head]
    blobs = frame_bytes_many([(m["video_name"], m["frame_name"]) for m in metas])

    from io import BytesIO

    from PIL import Image

    images = []
    for data in blobs:
        if data is None:
            images.append(None)
            continue
        try:
            images.append(Image.open(BytesIO(data)).convert("RGB"))
        except Exception:
            images.append(None)

    rr = rerank_visual(query, images)
    if rr is None:
        return raw

    blended = blend([float(h["score"]) for h in head], rr, settings.visual_rerank_alpha)
    head = [{**h, "score": s} for h, s in zip(head, blended)]
    head.sort(key=lambda x: x["score"], reverse=True)
    return head + tail
