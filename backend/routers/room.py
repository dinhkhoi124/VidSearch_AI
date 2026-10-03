"""Phòng thi nhóm: giỏ đáp án + lịch sử truy vấn dùng chung cho 5 người.

Kiến trúc: GHI bằng REST (`POST /room/op`), ĐỌC realtime bằng WebSocket
(`/room/ws`) - xem chú thích trong services/room_hub.py về lý do tách hai chiều.

Không có auth: phòng thi là mạng LAN kín, thêm login chỉ tốn thời gian lúc thi.
Danh tính chỉ là cái tên tự chọn, dùng để hiển thị "frame này ai thêm".
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from config import get_settings
from models.room_schemas import (
    AgentChatDeleteRequest,
    AgentTurnRequest,
    HistoryRequest,
    OpRequest,
    SubmitLogRequest,
)
from services import room_lock
from services.agent_history_store import AgentHistoryStore
from services.room_hub import Connection, RoomHub
from services.room_store import RoomStore

settings = get_settings()
router = APIRouter(prefix="/room", tags=["room"])

STATE_PATH = settings.room_path / "room-default.json"

store = RoomStore(
    path=STATE_PATH,
    history_max=settings.room_history_max,
    debounce_s=settings.room_snapshot_debounce_s,
)
hub = RoomHub()

# Lịch sử tra cứu Agent: RIÊNG từng thành viên, mỗi member một file. Ở chung
# router /room vì cùng một điều kiện phục vụ - _guard() dưới đây đã chặn khi tắt
# phòng hoặc khi tiến trình khác đang giữ khoá state, mà hai tiến trình cùng ghi
# file lịch sử của một người thì hỏng y như cùng ghi giỏ.
agent_history = AgentHistoryStore(
    root=settings.room_path / "agent-history",
    max_chats=settings.agent_history_max_chats,
    result_cap=settings.agent_history_result_cap,
    payload_turns=settings.agent_history_payload_turns,
    debounce_s=settings.room_snapshot_debounce_s,
)

# Khác None = tiến trình khác đang sở hữu file state, ta KHÔNG được phục vụ
# /room. Xem services/room_lock.py về việc vì sao hai chủ là mất giỏ đáp án.
lock_error: Optional[str] = None


def claim_state(label: str) -> bool:
    """Giành quyền sở hữu state phòng rồi nạp snapshot. False = thua, /room tắt.

    Gọi từ lifespan của mỗi app phục vụ router này. Gộp cả `store.load()` vào
    đây vì hai việc phải đi liền: nạp snapshot khi chưa cầm khoá là đọc một file
    tiến trình khác đang ghi dở, và giỏ đọc lên có thể cụt.
    """
    global lock_error
    lock_error = room_lock.acquire(STATE_PATH, label)
    if lock_error:
        print(f"[room] KHÔNG phục vụ /room: {lock_error}")
        return False
    store.load()
    return True


def _guard() -> None:
    if not settings.room_enabled:
        raise HTTPException(status_code=503, detail="Chế độ phòng đang tắt (ROOM_ENABLED=false)")
    if lock_error:
        raise HTTPException(status_code=503, detail=lock_error)


@router.get("/state")
async def get_state():
    """Snapshot đầy đủ. FE dùng khi WS chưa lên hoặc vừa mất kết nối xong."""
    _guard()
    state = await store.snapshot()
    state["members"] = hub.presence()
    return state


@router.post("/op")
async def post_op(req: OpRequest):
    """Áp dụng một thao tác lên giỏ chung rồi phát cho mọi máy đang mở."""
    _guard()
    member = {"id": req.member_id, "name": req.member_name}
    # by_alias=True: op "reorder" mang trường `from` (từ khoá Python nên bên
    # models phải alias) - quên chỗ này là reorder im lặng không chạy.
    op = req.op.model_dump(by_alias=True, exclude_none=True)
    message = await store.apply_op(op, member)
    if message is None:
        # Op không đổi gì (thêm frame đã có, gõ lại đúng chữ cũ...) -> không tăng
        # rev, không broadcast. Vẫn trả 200: với client thì kết quả đã đúng rồi.
        return {"applied": False}
    await hub.broadcast(message)
    return {"applied": True, "rev": message["rev"]}


@router.post("/history")
async def post_history(req: HistoryRequest):
    """Ghi một truy vấn vào lịch sử NHÓM, để không ai tìm lại đường đồng đội đã đi."""
    _guard()
    query = (req.query or "").strip()
    if not query:
        return {"applied": False}
    message = await store.add_history({
        "member_id": req.member_id,
        "member_name": req.member_name,
        "mode": req.mode,
        "query": query,
        "result_count": req.result_count,
    })
    await hub.broadcast(message)
    return {"applied": True}


@router.post("/submitlog")
async def post_submit_log(req: SubmitLogRequest):
    """Ghi một lượt tải zip nộp bài để CẢ PHÒNG cùng đếm.

    BTC cho 3 lượt mỗi gói và chấm lượt CUỐI CÙNG. Đếm trên từng máy thì 5 người
    mỗi người thấy một con số khác nhau, đúng vào thứ không được phép đoán sai.
    """
    _guard()
    entry_id = (req.id or "").strip()
    if not entry_id:
        return {"applied": False}
    message = await store.add_submission({
        "id": entry_id,
        "at": req.at,
        "member_id": req.member_id,
        "member_name": req.member_name,
        "packageName": req.package_name,
        "zipName": req.zip_name,
        "files": [f.model_dump() for f in req.files],
    })
    if message is None:
        # Đã có mục cùng id (gửi lại sau khi mất mạng) -> không nhân đôi lượt.
        return {"applied": False}
    await hub.broadcast(message)
    return {"applied": True}


@router.post("/submitlog/clear")
async def clear_submit_log():
    """Xoá nhật ký nộp của cả phòng - đi kèm thao tác "tạo đề mới" bên FE.

    Vòng thi mới là gói truy vấn mới, mà BTC đếm 3 lượt theo từng gói, nên bộ
    đếm phải về 0 trên MỌI máy chứ không riêng máy bấm.
    """
    _guard()
    message = await store.clear_submissions()
    if message is None:
        return {"applied": False}
    await hub.broadcast(message)
    return {"applied": True}


# --- Lịch sử tra cứu Agent ---------------------------------------------------
# KHÔNG broadcast WebSocket như các endpoint trên: lịch sử là của riêng một
# người, và payload một lượt nặng ~70KB - đẩy cho 4 máy còn lại là tốn băng
# thông phòng thi để gửi thứ không ai dùng.


@router.get("/agent_chats")
async def list_agent_chats(member_id: str, limit: int = 50):
    """Danh sách các cuộc trò chuyện Agent đã lưu - KHÔNG kèm frame.

    Panel gọi endpoint này mỗi lần người dùng mở tab lịch sử, nên nó phải nhẹ;
    frame chỉ đi kèm khi mở hẳn một cuộc (endpoint dưới).
    """
    _guard()
    limit = max(1, min(200, limit))
    return {"chats": await agent_history.list_chats(member_id, limit)}


@router.get("/agent_chats/{chat_id}")
async def get_agent_chat(chat_id: str, member_id: str):
    """Một cuộc trò chuyện đầy đủ, KÈM danh sách frame của từng lượt.

    Đây là cả mục đích của tính năng: mở lại cuộc cũ và đổ frame vào lưới mà
    không chạm tới /agent/chat, tức không tốn lượt LLM nào.
    """
    _guard()
    chat = await agent_history.get_chat(member_id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Không có cuộc trò chuyện này")
    return chat


@router.post("/agent_chats/turn")
async def post_agent_turn(req: AgentTurnRequest):
    """Lưu MỘT lượt vừa chạy xong. Gửi lại cùng turn.id không nhân đôi lượt."""
    _guard()
    summary = await agent_history.append_turn(
        req.member_id, req.chat_id, req.title, req.turn.model_dump(),
    )
    if summary is None:
        return {"applied": False}
    return {"applied": True, "chat": summary}


@router.post("/agent_chats/delete")
async def delete_agent_chat(req: AgentChatDeleteRequest):
    """Xoá một cuộc, hoặc cả lịch sử Agent của thành viên khi thiếu chat_id.

    POST chứ không DELETE: hàng đợi bền vững của roomClient (mất mạng thì nằm
    chờ trong localStorage) chỉ biết gửi POST.
    """
    _guard()
    if req.chat_id:
        applied = await agent_history.delete_chat(req.member_id, req.chat_id)
    else:
        applied = await agent_history.clear(req.member_id)
    return {"applied": applied}


@router.get("/export")
async def export_state():
    """Tải toàn bộ state phòng dạng JSON - bản sao lưu bấm tay giữa lúc thi,
    và là đường thoát nếu FE hỏng mà giỏ vẫn còn trên server."""
    _guard()
    state = await store.snapshot()
    return JSONResponse(
        content=state,
        headers={"Content-Disposition": 'attachment; filename="room-backup.json"'},
    )


@router.websocket("/ws")
async def room_ws(websocket: WebSocket, member_id: str = "", member_name: str = ""):
    """Kênh đẩy: snapshot lúc vào, delta sau đó.

    Chiều lên chỉ nhận `ping` và `presence` (đang mở câu mấy). Mọi thứ khác bị
    bỏ qua - ghi phải đi qua POST /room/op để server tuần tự hoá được.
    """
    if not settings.room_enabled:
        await websocket.close(code=1008, reason="room disabled")
        return
    if lock_error:
        # Đóng TRƯỚC accept() -> uvicorn từ chối ngay ở bước bắt tay bằng HTTP
        # 403, nên `reason` dưới đây KHÔNG bao giờ tới được trình duyệt (giống
        # hệt nhánh "room disabled" ở trên). Câu giải thích đầy đủ nằm ở hai chỗ
        # người ta thật sự đọc được: log lúc khởi động, và detail của mọi
        # endpoint REST /room - đừng đi tìm nó trong DevTools của WebSocket.
        await websocket.close(code=1008, reason="room state locked by another process")
        return

    await websocket.accept()
    conn = Connection(websocket, member_id or "anon", member_name or "Ẩn danh")
    await hub.add(conn)

    try:
        state = await store.snapshot()
        await websocket.send_json({"type": "snapshot", "state": state, "rev": state["rev"]})
        await hub.broadcast_presence()

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            conn.touch()
            if kind == "ping":
                await websocket.send_json({"type": "pong"})
                # Mỗi nhịp ping tranh thủ dọn socket chết lặng; có dọn ai thì báo
                # lại danh sách cho cả phòng, không thì im.
                if await hub.sweep():
                    await hub.broadcast_presence()
            elif kind == "presence":
                try:
                    conn.current = max(1, int(msg.get("current") or 1))
                except (TypeError, ValueError):
                    conn.current = 1
                await hub.broadcast_presence()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - một socket hỏng không được kéo sập router
        print(f"[room] ws lỗi ({conn.member_name}): {exc}")
    finally:
        await hub.remove(conn)
        await hub.broadcast_presence()
