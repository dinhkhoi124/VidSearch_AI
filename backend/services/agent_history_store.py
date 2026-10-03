"""Lịch sử tra cứu Agent, RIÊNG từng thành viên.

Vì sao có file này: panel Agent trước đây giữ hội thoại trong RAM của trình duyệt,
F5 là mất cả câu hỏi lẫn danh sách frame vừa tìm ra. Muốn xem lại một hướng đã dò
thì phải chạy lại /agent/chat, mà mỗi lượt là 1..N call LLM (plan, ReAct, QA
vision) - đốt quota để lấy lại đúng thứ vừa có. Ở đây lưu nguyên KẾT QUẢ nên xem
lại là 0 request tới /agent/*, 0 token.

Ba quyết định đáng giải thích:

1. LƯU NGUYÊN DICT SearchResult, không lưu [{id, score}] rồi dựng lại bằng
   metadata_service.build_search_results. Máy chủ phòng có thể là
   scripts/room_server.py - bản cố ý KHÔNG import service model nào để chạy được
   trên máy không GPU, không data. Nó không có frames_meta để dựng lại bất cứ thứ
   gì. Bù lại, bản ghi tự chứa: frame_url trỏ về MEDIA_BASE_URL (FE tự serve ảnh)
   nên lịch sử vẫn xem được cả khi backend search đã tắt.

2. MỖI MEMBER MỘT FILE, không nhét vào room-default.json. Một lượt top_k=200
   nặng ~70KB; gộp vào snapshot dùng chung là bắt ghi lại toàn bộ giỏ của cả
   phòng mỗi lần ai đó gõ một chữ trong ô đáp án.

3. CÓ TRẦN DUNG LƯỢNG, và trần cắt PAYLOAD trước, cắt CHỮ sau: phần chữ (câu
   hỏi, reply, plan) rẻ và là thứ giúp nhớ "mình đã dò hướng nào", nên nó sống
   lâu hơn danh sách frame. Lượt bị dọn payload mang cờ `trimmed` để UI nói thẳng
   là phải chạy lại, thay vì hiện một nút xem lại rỗng.

Cơ chế ghi đĩa (atomic + debounce) sao chép từ services/room_store.py - xem chú
thích bên đó về việc vì sao ghi đè trực tiếp là mất trắng khi cúp điện.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")

# Tiêu đề cuộc trò chuyện = câu hỏi đầu tiên, cắt bớt cho khỏi phình file.
TITLE_MAX = 120


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_member(member_id: str) -> str:
    """member_id -> tên file an toàn.

    member_id do CLIENT sinh (crypto.randomUUID bên roomClient) nên tuyệt đối
    không được ghép thẳng vào đường dẫn: "../../room-default" là xoá giỏ của cả
    phòng. Giữ phần ký tự lành để còn đọc được tên file bằng mắt, rồi luôn gắn
    thêm 8 ký tự băm của chuỗi GỐC - nếu không, hai member_id chỉ khác nhau ở
    dấu chấm sẽ dùng chung một file lịch sử.
    """
    raw = str(member_id or "").strip()
    clean = _SAFE_ID_RE.sub("", raw)[:48] or "anon"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{clean}-{digest}"


def _empty() -> Dict[str, Any]:
    return {"chats": []}


def _normalize(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    chats = raw.get("chats")
    out: List[Dict[str, Any]] = []
    for c in chats if isinstance(chats, list) else []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        turns = c.get("turns")
        out.append({
            "id": str(c["id"]),
            "title": str(c.get("title") or ""),
            "created_at": int(c.get("created_at") or 0),
            "updated_at": int(c.get("updated_at") or 0),
            "turns": [t for t in turns if isinstance(t, dict) and t.get("id")]
                     if isinstance(turns, list) else [],
        })
    return {"chats": out}


def _chat_summary(chat: Dict[str, Any]) -> Dict[str, Any]:
    """Bản NHẸ của một cuộc - không kèm results/videos.

    Danh sách lịch sử được gọi mỗi lần người dùng mở tab; trả kèm payload thì
    riêng cái danh sách đã là vài MB, tức là đúng thứ tính năng này muốn tránh.
    """
    turns = chat["turns"]
    return {
        "id": chat["id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
        "updated_at": chat["updated_at"],
        "turn_count": len(turns),
        "result_count": sum(int(t.get("result_count") or 0) for t in turns),
        "last_question": turns[-1].get("question", "") if turns else "",
    }


class AgentHistoryStore:
    def __init__(
        self,
        root: Path,
        max_chats: int = 30,
        result_cap: int = 200,
        payload_turns: int = 60,
        debounce_s: float = 1.0,
    ):
        self._lock = asyncio.Lock()
        self._root = root
        self._max_chats = max_chats
        self._result_cap = result_cap
        self._payload_turns = payload_turns
        self._debounce_s = debounce_s
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._dirty: Set[str] = set()
        self._flush_task: Optional[asyncio.Task] = None

    # --- Đĩa ------------------------------------------------------------------
    def _path(self, member_id: str) -> Path:
        return self._root / f"{_safe_member(member_id)}.json"

    def _state(self, member_id: str) -> Dict[str, Any]:
        """State của một member, nạp lười. Gọi TRONG lock."""
        if member_id in self._cache:
            return self._cache[member_id]
        state = _empty()
        path = self._path(member_id)
        try:
            if path.exists():
                state = _normalize(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - file hỏng không được chặn cả phòng
            print(f"[agent-history] {path.name} hỏng ({exc}) -> coi như chưa có lịch sử")
            state = _empty()
        self._cache[member_id] = state
        return state

    def _write_member(self, member_id: str) -> None:
        state = self._cache.get(member_id)
        if state is None:
            return
        path = self._path(member_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001
            print(f"[agent-history] ghi {path.name} lỗi: {exc}")

    def _write_dirty(self) -> None:
        for member_id in list(self._dirty):
            self._write_member(member_id)
        self._dirty.clear()

    def _schedule_flush(self, member_id: str) -> None:
        self._dirty.add(member_id)
        if self._flush_task and not self._flush_task.done():
            return

        async def _later():
            await asyncio.sleep(self._debounce_s)
            if self._dirty:
                self._write_dirty()

        try:
            self._flush_task = asyncio.get_running_loop().create_task(_later())
        except RuntimeError:
            self._write_dirty()  # không có loop (test đồng bộ) -> ghi luôn

    async def flush(self) -> None:
        """Ghi ngay - gọi lúc shutdown, nếu không lượt cuối nằm lại trong debounce."""
        async with self._lock:
            if self._dirty:
                self._write_dirty()

    # --- Trần dung lượng ------------------------------------------------------
    def _strip_results(self, turn: Dict[str, Any]) -> None:
        turn["results"] = []
        turn["videos"] = []
        turn["trimmed"] = True

    def _enforce_caps(self, state: Dict[str, Any]) -> None:
        """Cắt cuộc cũ, rồi dọn payload của các lượt cũ. Gọi TRONG lock, sau mỗi ghi.

        Thứ tự quan trọng: cắt cuộc trước thì số lượt còn lại mới đúng để đếm hạn
        payload.
        """
        del state["chats"][self._max_chats:]

        # Mọi lượt của member, mới nhất trước. Hạn tính trên TOÀN BỘ member chứ
        # không theo từng cuộc: 30 cuộc x mỗi cuộc giữ vài lượt vẫn ra hàng chục
        # MB, mà người dùng chỉ thực sự quay lại vài cuộc gần đây.
        turns = [t for c in state["chats"] for t in c["turns"]]
        turns.sort(key=lambda t: int(t.get("ts") or 0), reverse=True)
        for turn in turns[self._payload_turns:]:
            if turn.get("results") or turn.get("videos"):
                self._strip_results(turn)

    def _pack_turn(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Chuẩn hoá + cắt gọn một lượt trước khi lưu."""
        results = raw.get("results")
        videos = raw.get("videos")
        results = results[: self._result_cap] if isinstance(results, list) else []
        videos = videos[: self._result_cap] if isinstance(videos, list) else []
        # `duplicates` nhân đôi payload mà xem lại thì không cần bung cụm - lưới
        # chỉ hiện đại diện, muốn bung thì tìm lại (việc đó không tốn token).
        results = [{k: v for k, v in r.items() if k != "duplicates"}
                   for r in results if isinstance(r, dict)]
        return {
            "id": str(raw.get("id") or ""),
            "ts": int(raw.get("ts") or _now_ms()),
            "mode": str(raw.get("mode") or "search"),
            "question": str(raw.get("question") or "")[:2000],
            "reply": str(raw.get("reply") or ""),
            "plan": raw.get("plan") if isinstance(raw.get("plan"), dict) else None,
            "trace": raw.get("trace") if isinstance(raw.get("trace"), list) else [],
            "result_type": str(raw.get("result_type") or "grid"),
            "results": results,
            "videos": videos,
            "result_count": len(results) or len(videos),
            "trimmed": False,
        }

    # --- Đọc ------------------------------------------------------------------
    async def list_chats(self, member_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        async with self._lock:
            chats = self._state(member_id)["chats"][:limit]
            return [_chat_summary(c) for c in chats]

    async def get_chat(self, member_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            for c in self._state(member_id)["chats"]:
                if c["id"] == chat_id:
                    return json.loads(json.dumps(c))  # bản sao sâu, không lộ dict gốc
            return None

    # --- Ghi ------------------------------------------------------------------
    async def append_turn(
        self, member_id: str, chat_id: str, title: str, turn: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Thêm một lượt vào cuộc (tạo cuộc nếu chưa có). None = không đổi gì.

        Idempotent theo turn["id"]: roomClient xả lại hàng đợi sau khi mất mạng,
        cùng lý do với RoomStore.add_submission. Gửi lại một lượt không được nhân
        đôi nó trong lịch sử.
        """
        chat_id = str(chat_id or "").strip()
        turn_id = str(turn.get("id") or "").strip()
        if not chat_id or not turn_id:
            return None

        async with self._lock:
            state = self._state(member_id)
            chats: List[Dict[str, Any]] = state["chats"]
            idx = next((i for i, c in enumerate(chats) if c["id"] == chat_id), -1)
            if idx == -1:
                chat = {
                    "id": chat_id,
                    "title": str(title or turn.get("question") or "")[:TITLE_MAX],
                    "created_at": _now_ms(),
                    "updated_at": _now_ms(),
                    "turns": [],
                }
                chats.insert(0, chat)
            else:
                chat = chats.pop(idx)
                chats.insert(0, chat)  # vừa hoạt động -> lên đầu danh sách
                if title and not chat["title"]:
                    chat["title"] = str(title)[:TITLE_MAX]

            if any(t.get("id") == turn_id for t in chat["turns"]):
                return None

            chat["turns"].append(self._pack_turn(turn))
            chat["updated_at"] = _now_ms()
            self._enforce_caps(state)
            self._schedule_flush(member_id)
            return _chat_summary(chat)

    async def delete_chat(self, member_id: str, chat_id: str) -> bool:
        async with self._lock:
            state = self._state(member_id)
            n = len(state["chats"])
            state["chats"] = [c for c in state["chats"] if c["id"] != chat_id]
            if len(state["chats"]) == n:
                return False
            self._schedule_flush(member_id)
            return True

    async def clear(self, member_id: str) -> bool:
        async with self._lock:
            state = self._state(member_id)
            if not state["chats"]:
                return False
            state["chats"] = []
            self._schedule_flush(member_id)
            return True
