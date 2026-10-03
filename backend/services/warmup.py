"""Warm-up: nạp trước mọi model + index được cấu hình, ngay khi server bật.

Mặc định các service nạp LAZY - model chỉ vào RAM/VRAM ở request đầu tiên chạm
tới nó. Trên Colab điều đó nghĩa là câu search đầu phải chờ tải weight
SigLIP/MetaCLIP/E5/reranker (hàng GB, có khi phải kéo từ HuggingFace) trước khi
trả kết quả, và mỗi kênh (visual / OCR / ASR / caption / graph) lại trả giá đó
riêng ở lần đầu của nó. Module này ép mọi thứ vào bộ nhớ một lần lúc khởi động.

Nạp những gì (đúng theo cấu hình đang chạy, không nạp bừa):
  * encoder visual  - settings.default_model + mọi model trong ENSEMBLE_MODELS
  * index FAISS visual + id map của chính các model đó
  * model embedding text (TEXT_EMBED_MODEL) + 3 index text ocr/asr/caption
  * reranker text (cross-encoder) và visual (BLIP ITM) - tắt được bằng
    WARMUP_RERANKERS=false khi VRAM eo hẹp
  * metadata frame, OCR/ASR/caption JSON, graph + index token scene + knn

Mọi bước đều best-effort: một bước hỏng chỉ được ghi "error" trong báo cáo, các
bước sau vẫn chạy và server vẫn phục vụ (đúng tinh thần fallback sẵn có của
từng service). Báo cáo đọc được ở GET /health và GET /warmup.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List

from config import get_settings

settings = get_settings()

# Trạng thái dùng chung, đọc bởi /health và /warmup.
_state: Dict[str, Any] = {
    "status": "pending",        # pending | running | done | error
    "started_at": None,
    "finished_at": None,
    "elapsed_s": None,
    "device": None,
    "steps": [],                # [{name, status, detail, elapsed_s}]
}
_lock = threading.Lock()
_thread: threading.Thread | None = None


def get_status() -> Dict[str, Any]:
    with _lock:
        return dict(_state, steps=list(_state["steps"]))


def is_ready() -> bool:
    return get_status()["status"] == "done"


def _configured_visual_models() -> List[str]:
    """default_model + các model trong ENSEMBLE_MODELS (trọng số > 0), giữ thứ tự."""
    from services.ensemble_service import parse_ensemble_models

    names = [settings.default_model]
    names += [m for m, w in parse_ensemble_models() if w > 0]
    seen, out = set(), []
    for n in names:
        n = (n or "").strip()
        if n and n != "ensemble" and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _device_info() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            return f"cuda ({name}, {total:.1f} GiB)"
        return "cpu (không thấy CUDA)"
    except Exception as e:  # noqa: BLE001 - torch thiếu cũng không được chặn boot
        return f"cpu (torch không dùng được: {e!r})"


def _vram_used() -> str:
    try:
        import torch

        if not torch.cuda.is_available():
            return ""
        return f" | VRAM {torch.cuda.memory_allocated() / 1024**3:.2f} GiB"
    except Exception:  # noqa: BLE001
        return ""


def _run_step(name: str, fn: Callable[[], str]) -> None:
    """Chạy một bước warm-up, ghi kết quả vào _state. Không bao giờ raise."""
    t0 = time.perf_counter()
    try:
        detail = fn()
        status = "ok"
    except Exception as e:  # noqa: BLE001 - warm-up hỏng không được giết server
        detail, status = f"{e!r}", "error"
    elapsed = time.perf_counter() - t0
    with _lock:
        _state["steps"].append(
            {"name": name, "status": status, "detail": detail,
             "elapsed_s": round(elapsed, 2)}
        )
    mark = "ok " if status == "ok" else "ERR"
    print(f"[warmup] {mark} {name}: {detail} ({elapsed:.1f}s){_vram_used()}")


# --- Từng bước ------------------------------------------------------------------

def _step_hf() -> str:
    """Xác nhận cấu hình HF đang có hiệu lực + kiểm chứng token bằng whoami.

    main.py đã gọi configure_hf(verify=False) trước mọi import; ở đây gọi lại
    (idempotent) để bắt trường hợp warm-up được chạy ngoài main.py, và để lần
    này chạm mạng lấy danh tính - chậm thì cũng chỉ chậm bước warm-up.
    """
    from services.hf_setup import configure_hf

    r = configure_hf(verify=True)
    warn = " | CẢNH BÁO: cấu hình đặt muộn, không có hiệu lực" if r["late_import"] else ""
    return (f"cache={r['cache_dir']}, {r['token']}, {r['auth']}, "
            f"hf_transfer={r['hf_transfer']}, hf_xet={r['hf_xet']}{warn}")


def _step_visual_encoders(models: List[str]) -> str:
    from services.embedding_service import encode_text, has_real_encoder

    got, mock = [], []
    for m in models:
        if has_real_encoder(m):
            # Encode thử một câu để chạm hết đường dẫn nóng (processor, cuda
            # kernel autotune, cấp phát buffer) - request đầu khỏi trả giá đó.
            encode_text("warmup", model=m)
            got.append(m)
        else:
            mock.append(m)
    if mock:
        # Model rơi về mock vẫn "chạy" nhưng trả vector ngẫu nhiên; ensemble
        # lặng lẽ bỏ qua nó, chất lượng tụt mà không có dấu hiệu gì. Phải là
        # lỗi đỏ trong báo cáo, không phải một ghi chú trong chuỗi ok.
        raise RuntimeError(
            f"model không nạp được weight thật, đang dùng mock: {', '.join(mock)}"
            + (f" (đã nạp thật: {', '.join(got)})" if got else "")
        )
    return ", ".join(got) or "không có model nào được cấu hình"


def _step_visual_indexes(models: List[str]) -> str:
    from services.faiss_service import preload

    parts = []
    for m in models:
        info = preload(m)
        parts.append(
            f"{m}: {info['vectors']} vec/{info['dim']}d" if info else f"{m}: THIẾU index"
        )
    return ", ".join(parts) or "không có model nào được cấu hình"


def _step_text_encoder() -> str:
    from services.text_embedding_service import encode_query, is_available

    if not is_available():
        return "tắt/không nạp được -> OCR/ASR dùng fuzzy-exact"
    encode_query("warmup")
    return f"{settings.text_embed_model} sẵn sàng"


def _step_text_indexes() -> str:
    from services.text_faiss_service import preload

    parts = []
    for name in ("ocr_text", "asr_text", "caption_text"):
        info = preload(name)
        parts.append(f"{name}: {info['vectors']} vec" if info else f"{name}: THIẾU")
    return ", ".join(parts)


def _step_rerankers() -> str:
    from services.rerank_service import text_available, visual_available

    text = "ok" if text_available() else "tắt/không nạp được"
    visual = "ok" if visual_available() else "tắt/không nạp được"
    return f"text({settings.text_rerank_model})={text}, visual({settings.visual_rerank_model})={visual}"


def _step_metadata() -> str:
    from services.metadata_service import preload

    info = preload()
    return f"{info['frames']} frame, {info['videos']} video"


def _step_text_data() -> str:
    from services.asr_service import preload as asr_preload
    from services.caption_service import preload as caption_preload
    from services.ocr_service import preload as ocr_preload

    return (f"ocr={ocr_preload()} frame, asr={asr_preload()} video, "
            f"caption={caption_preload()} frame")


def _step_graph(models: List[str]) -> str:
    from services.graph_service import preload

    info = preload(models)
    if info is None:
        return "chưa build graph -> các bonus scene/knn tự no-op"
    knn = ", ".join(f"knn_{m}={n}" for m, n in info["knn"].items()) or "không có knn"
    return f"{info['scenes']} scene, {info['frames']} frame, {knn}"


def _step_llm_config() -> str:
    """Không gọi mạng - chỉ soi cấu hình để lỗi thiếu key lộ ra lúc boot."""
    from services.agent_service import _openai_host, _openai_model_for

    provider = (settings.llm_provider or "auto").lower()
    gemini = "có key" if settings.gemini_api_key.strip() else "THIẾU key"
    openai = "có key" if settings.openai_api_key.strip() else "THIẾU key"
    # Host in ra để phân biệt được đang trỏ openrouter/ollama/orcarouter - đổi
    # OPENAI_BASE_URL mà quên là kiểu lỗi rất khó nhìn ra từ triệu chứng.
    host = _openai_host() if settings.openai_base_url.strip() else "chưa đặt base_url"
    order = {
        "auto": "gemini -> openai",
        "openai_first": "openai -> gemini",
        "gemini": "chỉ gemini",
        "openai": "chỉ openai (KHÔNG có đường lui)",
    }.get(provider, f"{provider}?")
    # Model per-task của phía OpenAI: sai ở đây thì QA gãy lặng lẽ (model
    # text-thuần nhận ảnh -> lỗi -> caller thấy None), nên in ra ngay lúc boot.
    per_task = ", ".join(
        f"{t}={_openai_model_for(t) or '-'}" for t in ("expand", "react", "qa")
    )
    return (f"provider={provider} [{order}], gemini({settings.gemini_model})={gemini}, "
            f"openai@{host}={openai} [{per_task}]")


# --- Điều phối --------------------------------------------------------------------

def run_warmup() -> Dict[str, Any]:
    """Chạy toàn bộ warm-up (đồng bộ). An toàn khi gọi lại: chỉ chạy lại từ đầu."""
    with _lock:
        if _state["status"] == "running":
            return dict(_state)
        # Mốc thời gian đặt TRƯỚC _device_info(): lần chạm torch.cuda đầu tiên
        # khởi tạo CUDA context (~10s) - phải nằm trong elapsed_s.
        t0 = time.perf_counter()
        _state.update(
            status="running", started_at=time.time(), finished_at=None,
            elapsed_s=None, device=None, steps=[],
        )
    device = _device_info()   # ngoài lock: /warmup vẫn đọc được trong lúc chờ
    with _lock:
        _state["device"] = device
    print(f"[warmup] bắt đầu nạp model/index trên {_state['device']}")

    models = _configured_visual_models()
    print(f"[warmup] model visual theo cấu hình: {', '.join(models) or '(rỗng)'}")

    rerank_step = (
        _step_rerankers if settings.warmup_rerankers
        else (lambda: "bỏ qua (WARMUP_RERANKERS=false)")
    )

    # Hai loại việc, hai nút thắt khác nhau:
    #   io  - đọc đĩa (~4GB index + JSON). faiss.read_index nhả GIL trong lúc
    #         đọc nên chạy nền được thật.
    #   gpu - import transformers (~25s, phần lớn thời gian của bước encoder
    #         đầu tiên) rồi nạp weight lên GPU.
    # Trong MỖI luồng vẫn tuần tự: đọc song song nhiều file lớn trên ổ quay chỉ
    # làm đầu từ nhảy loạn, và nạp song song nhiều model dễ vọt VRAM.
    io_steps = [
        ("metadata", _step_metadata),
        ("ocr/asr/caption data", _step_text_data),
        ("visual FAISS", lambda: _step_visual_indexes(models)),
        ("text FAISS", _step_text_indexes),
        ("graph", lambda: _step_graph(models)),
    ]
    # Mọi bước nạp weight nằm CHUNG một luồng, tuần tự. Đã thử tách đôi (visual
    # một luồng, text+reranker luồng kia) để chồng thời gian: nhanh hơn ~35s
    # nhưng SAI - transformers materialise weight từ meta-device, hai thread
    # cùng from_pretrained thì đua nhau và ném
    #   NotImplementedError: Cannot copy out of meta tensor; no data!
    # rồi service tự rơi về CPU hoặc mock, tức là "nhanh" nhờ không nạp gì.
    gpu_steps = [
        ("visual encoders", lambda: _step_visual_encoders(models)),
        ("text encoder", _step_text_encoder),
        ("rerankers", rerank_step),
        ("cấu hình LLM", _step_llm_config),
    ]

    def _run_track(steps):
        for name, fn in steps:
            _run_step(name, fn)

    # HuggingFace luôn chạy trước và một mình: nó đặt biến môi trường mà mọi
    # bước tải weight phía sau đọc, chạy song song là đặt muộn mất tác dụng.
    _run_step("HuggingFace", _step_hf)

    if settings.warmup_parallel:
        threads = [
            threading.Thread(target=_run_track, args=(s,), name=n, daemon=True)
            for n, s in (("warmup-io", io_steps), ("warmup-gpu", gpu_steps))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        _run_track(gpu_steps)
        _run_track(io_steps)

    elapsed = time.perf_counter() - t0
    with _lock:
        failed = [s["name"] for s in _state["steps"] if s["status"] != "ok"]
        _state.update(
            status="error" if failed else "done",
            finished_at=time.time(),
            elapsed_s=round(elapsed, 2),
        )
        snapshot = dict(_state, steps=list(_state["steps"]))
    if failed:
        print(f"[warmup] xong trong {elapsed:.1f}s - LỖI ở: {', '.join(failed)}")
    else:
        print(f"[warmup] xong trong {elapsed:.1f}s - tất cả sẵn sàng{_vram_used()}")
    return snapshot


def start_warmup(background: bool) -> None:
    """Khởi động warm-up. background=True cho server nhận request ngay lập tức."""
    global _thread
    if not background:
        run_warmup()
        return
    _thread = threading.Thread(target=run_warmup, name="warmup", daemon=True)
    _thread.start()
