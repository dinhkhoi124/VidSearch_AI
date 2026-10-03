"""Quản lý WebSocket của phòng thi: broadcast + presence.

WS ở đây CHỈ ĐI MỘT CHIỀU XUỐNG (server -> client). Mọi thao tác ghi đi bằng
REST POST /room/op. Đổi lại: không phải làm request/response correlation trên
socket, reconnect không cần replay gì phía server, và debug được bằng curl.
Chiều lên chỉ có hai loại tin vặt: "ping" và "đang mở câu mấy".
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket


# Cần ngưỡng này vì socket "chết lặng" (đóng nắp laptop, rút dây) KHÔNG sinh ra
# disconnect: nó nằm lại trong hub cho tới lần broadcast kế tiếp bị lỗi, và trong
# lúc đó mọi máy khác vẫn thấy người đó "đang online". Đóng tab hay tắt trình
# duyệt thì có disconnect thật, nhánh finally của /room/ws gỡ ngay - chỗ này chỉ
# lo trường hợp chết lặng.
#
# 150s chứ không phải 75s: client ping mỗi 25s khi tab đang mở, nhưng ở TAB NỀN
# trình duyệt bóp timer xuống ~1 lần/phút (xem ghi chú PONG_TIMEOUT_MS trong
# frontend/src/api/roomClient.js). Ngưỡng ở đây phải rộng hơn CẢ nhịp ping tệ
# nhất đó LẪN hạn 90s của client, nếu không server đá một người ra chỉ vì họ
# đang xem tab khác - và 4 máy còn lại thấy người đó biến mất khỏi danh sách.
STALE_MS = 150_000


def _now_ms() -> int:
    return int(time.time() * 1000)


class Connection:
    __slots__ = ("ws", "member_id", "member_name", "current", "online_since", "last_seen")

    def __init__(self, ws: WebSocket, member_id: str, member_name: str):
        self.ws = ws
        self.member_id = member_id
        self.member_name = member_name
        self.current = 1
        self.online_since = _now_ms()
        self.last_seen = self.online_since

    def touch(self) -> None:
        self.last_seen = _now_ms()


class RoomHub:
    def __init__(self) -> None:
        self._conns: Set[Connection] = set()
        self._lock = asyncio.Lock()

    async def add(self, conn: Connection) -> None:
        async with self._lock:
            self._conns.add(conn)

    async def remove(self, conn: Connection) -> None:
        async with self._lock:
            self._conns.discard(conn)

    def presence(self) -> List[Dict[str, Any]]:
        """Ai đang online và đang làm câu mấy - để 5 người khỏi giẫm chân nhau.

        Gộp theo member_id: mở hai tab vẫn là một người. online_since lấy lần nối
        SỚM NHẤT (người đó vào phòng từ lúc nào), current lấy LỚN NHẤT.

        Cả hai phải là phép rút gọn không phụ thuộc thứ tự duyệt: self._conns là
        set, thứ tự lặp tuỳ ý, nên bất kỳ quy tắc kiểu "ai duyệt sau thì đè" đều
        làm ô 'đang làm câu mấy' nhảy qua nhảy lại giữa các tab của cùng một
        người, mỗi lần broadcast một khác.
        """
        cutoff = _now_ms() - STALE_MS
        by_member: Dict[str, Dict[str, Any]] = {}
        for c in self._conns:
            if c.last_seen < cutoff:
                continue  # im lặng quá lâu -> đừng đếm là người đang online
            prev = by_member.get(c.member_id)
            if prev is None:
                by_member[c.member_id] = {
                    "id": c.member_id,
                    "name": c.member_name,
                    "current": c.current,
                    "online_since": c.online_since,
                }
                continue
            prev["current"] = max(prev["current"], c.current)
            if c.online_since < prev["online_since"]:
                prev["online_since"] = c.online_since
                prev["name"] = c.member_name
        return sorted(by_member.values(), key=lambda m: (m["online_since"], m["id"]))

    async def broadcast(self, message: Dict[str, Any], exclude: Optional[Connection] = None) -> None:
        """Gửi cho mọi socket. Socket lỗi bị gỡ luôn - một máy rút mạng không
        được phép làm chậm hay chặn 4 máy còn lại."""
        async with self._lock:
            targets = [c for c in self._conns if c is not exclude]
        if not targets:
            return
        results = await asyncio.gather(
            *(c.ws.send_json(message) for c in targets), return_exceptions=True
        )
        dead = [c for c, r in zip(targets, results) if isinstance(r, Exception)]
        if dead:
            async with self._lock:
                for c in dead:
                    self._conns.discard(c)

    async def broadcast_presence(self) -> None:
        await self.broadcast({"type": "presence", "members": self.presence()})

    async def sweep(self) -> bool:
        """Dọn các socket đã im lặng quá STALE_MS. Trả về True nếu có dọn ai.

        Gọi từ nhánh nhận `ping`: cứ còn một máy sống là mỗi 25s có một lần quét,
        khỏi phải nuôi thêm task nền. Không còn ai ping thì cũng không còn ai
        nhìn danh sách sai nữa.
        """
        cutoff = _now_ms() - STALE_MS
        async with self._lock:
            dead = [c for c in self._conns if c.last_seen < cutoff]
            for c in dead:
                self._conns.discard(c)
        for c in dead:
            try:
                await c.ws.close(code=1001)
            except Exception:  # noqa: BLE001 - socket đã chết thì đóng lỗi là bình thường
                pass
        return bool(dead)
