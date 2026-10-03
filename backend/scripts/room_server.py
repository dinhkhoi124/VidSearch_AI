"""Chạy RIÊNG phòng thi nhóm - giỏ đáp án + lịch sử chung, không có search.

    python scripts/room_server.py --port 8100

Dùng khi mỗi người chạy backend search của riêng mình (GPU của mình, data của
mình) nhưng cả nhóm muốn chung MỘT giỏ đáp án: mọi người để ô "Backend URL" trỏ
về máy mình, còn ô "Room URL" trong Cài đặt (⚙) thì dán CÙNG một địa chỉ - chính
là tiến trình này.

Vì sao không dùng main.py với WARMUP_ON_STARTUP=false: main.py import cả cây
service (torch, faiss, transformers) ngay lúc khởi động dù không nạp weight -
chậm, tốn RAM, và bắt máy chủ phòng phải cài đủ bộ thư viện nặng. routers/room.py
không import service model nào, nên bản này chỉ cần fastapi + uvicorn và lên
trong một hai giây. Đặt được trên máy bất kỳ, kể cả máy không có GPU lẫn data.

State ghi ra ROOM_DIR (mặc định ./room_state) giống hệt bản đầy đủ, nên đổi qua
lại giữa hai cách chạy không mất giỏ.
"""
from __future__ import annotations

import argparse
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Console Windows mặc định là cp1252, không encode nổi tiếng Việt: chỉ một chữ
# "tại" trong print bên dưới là UnicodeEncodeError, và nó giết tiến trình TRƯỚC
# khi uvicorn kịp lên -> máy chủ phòng không bao giờ khởi động, triệu chứng lại
# là một traceback về codec chẳng liên quan gì tới phòng. errors="replace" để
# terminal cổ lỗ nhất cũng chỉ mất dấu chứ không làm sập server.
#
# line_buffering=True vì cùng lý do, một tầng nữa: chuyển hướng `> room.log` là
# stdout thành block-buffered, và mọi dòng [room] (nạp snapshot bao nhiêu frame,
# thua khoá state vì tiến trình nào) nằm lại trong bộ đệm cho tới khi tiến trình
# thoát êm. Ctrl-C hay kill thì mất sạch - đúng lúc cần đọc log nhất thì không
# có gì để đọc, trong khi log của uvicorn vẫn hiện vì nó tự flush.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from config import get_settings  # noqa: E402
from routers import room  # noqa: E402

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Giống main.py: giành khoá state, nạp snapshot lúc bật, flush lúc tắt.
    # Snapshot ghi theo kiểu debounce nên thiếu cú flush là mất thao tác cuối.
    #
    # Khác main.py ở chỗ thua khoá là VÔ DỤNG hẳn: tiến trình này không làm gì
    # ngoài phòng. Vẫn để nó lên để /health và mọi endpoint /room trả 503 kèm
    # câu giải thích - im lặng thoát thì người chạy chỉ thấy terminal đóng sập.
    owns_room = room.claim_state("room_server.py")
    if not owns_room:
        print("[room] ^ tắt tiến trình kia rồi chạy lại, hoặc dùng thẳng nó.")
    yield
    # Thua khoá thì tuyệt đối KHÔNG ghi: state trong RAM ở đây là bản rỗng chưa
    # từng load, ghi ra là xoá sạch giỏ của tiến trình đang sở hữu.
    if owns_room:
        await room.store.flush()
        await room.agent_history.flush()


app = FastAPI(title="AIC Room", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(room.router)


@app.get("/health")
def health():
    """Cùng hình dạng với /health của main.py để kiểm tra bằng đúng một lệnh curl.
    ready luôn true: ở đây không có model nào để chờ."""
    return {"status": "ok", "ready": True, "room_only": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy riêng phòng thi nhóm (không có search)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    if not settings.room_enabled:
        print("ROOM_ENABLED=false trong .env -> mọi endpoint /room sẽ trả 503.")
        print("Sửa lại thành true rồi chạy lại, nếu không thì tiến trình này vô dụng.")
        return 1

    import uvicorn

    print(f"[room] state: {settings.room_path}")
    print(f"[room] nghe tại http://{args.host}:{args.port}")
    print("[room] để cả nhóm vào chung, mở tunnel rồi dán URL vào ô 'Room URL' của mỗi máy:")
    print(f"           cloudflared tunnel --url http://localhost:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
