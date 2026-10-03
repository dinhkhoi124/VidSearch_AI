"""FastAPI entry point for AIC 2026 Video Retrieval backend."""
import sys
from contextlib import asynccontextmanager

# Console Windows mặc định cp1252: mọi print() tiếng Việt có dấu trong codebase
# (log của ensemble, warmup, agent...) sẽ ném UnicodeEncodeError NGAY TRONG
# đường xử lý request, biến một dòng log thành lỗi 500. errors="replace" để
# không bao giờ chết vì log, dù ký tự lạ có hiện thành '?'.
#
# line_buffering=True: chuyển hướng `> be.log` biến stdout thành block-buffered,
# nên mọi dòng print() nằm lại trong bộ đệm tới lúc thoát êm - Ctrl-C hay kill là
# mất sạch, đúng lúc cần đọc log nhất. Log của uvicorn vẫn hiện vì nó tự flush,
# càng dễ tưởng codebase không in gì.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, ValueError):  # stream đã bị thay bằng thứ khác
        pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from services.hf_setup import configure_hf

# PHẢI gọi ở đây, TRƯỚC khi import routers/services: huggingface_hub đọc
# HF_HOME và HF_HUB_ENABLE_HF_TRANSFER một lần duy nhất lúc nó được import, đặt
# muộn hơn là vô tác dụng. verify=False để không gọi mạng ở thời điểm import
# module - whoami chạy trong bước warm-up.
configure_hf(verify=False)

from routers import (  # noqa: E402 - phải sau configure_hf(), xem chú thích trên
    agent,
    catalog,
    frames,
    graph,
    room,
    search_asr,
    search_caption,
    search_feedback,
    search_image,
    search_ocr,
    search_temporal,
    search_text,
    verify,
)
from services import llm_status, warmup  # noqa: E402
from services.faiss_service import IndexUnavailable  # noqa: E402

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Nạp trước model/index khi bật server (xem services/warmup.py).

    WARMUP_BACKGROUND=true (mặc định) cho server nhận request ngay trong lúc
    nạp - cần khi chạy sau ngrok/Colab để tunnel lên sớm. Đặt false nếu muốn
    chắc chắn request đầu tiên đã có đủ model.
    """
    if settings.warmup_on_startup:
        warmup.start_warmup(background=settings.warmup_background)
    else:
        print("[warmup] tắt (WARMUP_ON_STARTUP=false) - model nạp lazy như cũ")
    # Giỏ chung của nhóm phải có TRƯỚC khi nhận request đầu tiên, nếu không
    # client kết nối sớm sẽ nhận snapshot rỗng rồi ghi đè mất giỏ cũ.
    #
    # Thua khoá (thường vì scripts/room_server.py đang chạy sẵn) thì CHỈ tắt
    # /room, không chặn server lên: đây vẫn là backend search của một người, và
    # đá luôn phần tìm kiếm chỉ vì phòng nằm ở tiến trình khác là phá quá tay.
    owns_room = settings.room_enabled and room.claim_state("main.py (backend search)")
    yield
    # Snapshot ghi theo kiểu debounce -> thao tác trong ~1s cuối chưa xuống đĩa.
    if owns_room:
        await room.store.flush()
        await room.agent_history.flush()


app = FastAPI(
    title="AIC Video Retrieval API",
    version="1.0.0",
    description="Backend cho Ho Chi Minh AI Challenge - text/image/ocr/asr/temporal search.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Đồng đội mở FE qua IP LAN của máy chủ, IP đổi theo phòng thi nên không
    # liệt kê sẵn trong CORS_ORIGINS được - xem Settings.cors_regex.
    allow_origin_regex=settings.cors_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Header tuỳ biến bị trình duyệt GIẤU khỏi JS nếu không expose — banner
    # "hết lượt Gemini" đọc đúng hai header này (xem services/llm_status.py).
    expose_headers=["X-Llm-Quota", "X-Llm-Quota-Info"],
)


@app.middleware("http")
async def llm_quota_header(request: Request, call_next):
    """Gắn trạng thái quota LLM vào MỌI response.

    Key Gemini hết lượt làm cả hệ degrade âm thầm (query giữ nguyên tiếng Việt,
    plan rơi về câu cuối, QA không trả lời) — người dùng chỉ thấy kết quả kém
    đi. Đi kèm response sẵn có thì frontend bật banner ngay ở thao tác kế tiếp,
    khỏi phải polling một endpoint riêng.
    """
    response = await call_next(request)
    try:
        for key, value in llm_status.headers().items():
            response.headers[key] = value
    except Exception as e:  # noqa: BLE001 — cảnh báo phụ, không được làm hỏng response
        print(f"[llm-quota] không gắn được header ({e!r})")
    return response

@app.exception_handler(IndexUnavailable)
async def index_unavailable_handler(request: Request, exc: IndexUnavailable):
    """Thiếu index -> 503 kèm tên file còn thiếu, KHÔNG trả kết quả giả.

    503 chứ không phải 500: server chạy tốt, chỉ là dữ liệu chưa sẵn sàng - sửa
    bằng cách build index hoặc đổi model, không phải bằng cách đọc traceback.
    """
    print(f"[503] {request.url.path}: {exc}")
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# Media giờ do FE phục vụ (FE public/media) - BE không mount StaticFiles,
# URL được build từ settings.media_base trong metadata_service.

app.include_router(search_text.router, tags=["search"])
app.include_router(search_image.router, tags=["search"])
app.include_router(search_ocr.router, tags=["search"])
app.include_router(search_asr.router, tags=["search"])
app.include_router(search_temporal.router, tags=["search"])
app.include_router(search_caption.router, tags=["search"])
app.include_router(search_feedback.router, tags=["search"])
app.include_router(catalog.router, tags=["catalog"])
app.include_router(frames.router, tags=["frames"])
app.include_router(graph.router, tags=["graph"])
app.include_router(agent.router, tags=["agent"])
app.include_router(verify.router, tags=["verify"])
app.include_router(room.router)


@app.get("/health", tags=["meta"])
def health_check():
    """Sống hay chưa + model đã nạp xong chưa (warmup: pending|running|done|error)."""
    state = warmup.get_status()
    return {
        "status": "ok",
        "warmup": state["status"],
        "ready": state["status"] == "done",
        "elapsed_s": state["elapsed_s"],
    }


@app.get("/warmup", tags=["meta"])
def warmup_status():
    """Báo cáo chi tiết từng bước warm-up (model nào nạp thật, index nào thiếu)."""
    return warmup.get_status()


@app.post("/warmup", tags=["meta"])
def warmup_run(background: bool = True):
    """Chạy lại warm-up thủ công - dùng sau khi copy thêm index vào data/."""
    if warmup.get_status()["status"] == "running":
        return {"status": "running", "detail": "warm-up đang chạy, bỏ qua yêu cầu"}
    warmup.start_warmup(background=background)
    return warmup.get_status()


if __name__ == "__main__":
    # `python main.py` phải bật được server. Không có khối này thì file chỉ
    # định nghĩa `app` rồi thoát - không có lifespan nên KHÔNG có warm-up, dễ
    # tưởng là warm-up hỏng.
    import uvicorn

    # reload=True cho uvicorn spawn tiến trình con và nạp lại toàn bộ model mỗi
    # lần file đổi (~2 phút + một lượt VRAM nữa) -> mặc định tắt. Dev muốn thì
    # đặt RELOAD=true, hoặc dùng run.sh (đã bật sẵn --reload).
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
