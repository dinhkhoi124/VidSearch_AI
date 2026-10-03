"""Giỏ đáp án + lịch sử truy vấn DÙNG CHUNG cho cả nhóm khi thi.

⚠ BẢN SAO JAVASCRIPT: frontend/src/hooks/basketReducer.js - hàm `_apply()` dưới
đây phải cho ra ĐÚNG kết quả như `applyOp()` bên đó. Sửa tập op hoặc ngữ nghĩa
một op ở một bên mà quên bên kia thì client tính ra state khác server, và giỏ
của cả nhóm sẽ lệch nhau ngay giữa lúc thi mà không báo lỗi gì.

Vì sao server-authoritative + op thay vì last-write-wins cả câu: giỏ là danh
sách CÓ THỨ TỰ (rank = thứ tự nộp). Hai người sửa cùng câu mà mỗi bên gửi cả
danh sách thì người gửi sau xoá mất việc của người gửi trước. Ở đây server tuần
tự hoá từng op dưới một khoá rồi phát lại nguyên câu, nên không mất thao tác nào
và mọi máy hội tụ về cùng một thứ tự.

Không dùng DB: dự án không có sẵn DB nào, và một buổi thi 5 người thì state vừa
đủ nằm trong RAM. Snapshot JSON ra đĩa chỉ để sống sót qua crash/restart.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_QUESTIONS = 200
# Trần cứng của BTC: mỗi file nộp tối đa 100 dòng. Trùng MAX_ROWS bên
# frontend/src/utils/submissionFormat.js.
MAX_ROWS = 100

# Tên truy vấn theo quy ước BTC: "query-<số>-<task>", có thể chèn thêm đoạn tiền
# tố đợt thi ("query-p1-15-qa"). Mỗi đoạn tiền tố phải bắt đầu bằng chữ, nếu
# không thì "p1" và số câu nhập nhằng nhau. Đổi task thì tên file nộp phải đổi
# theo, nhưng chỉ khi người dùng CHƯA sửa tay - xem _is_auto_query_id.
# ⚠ Mirror: QUERY_ID_RE trong frontend/src/utils/submissionFormat.js.
_TASK_TYPES = ("kis", "qa", "trake")
_AUTO_QUERY_ID_RE = re.compile(r"^query-((?:[a-z][a-z0-9]*-)*)(\d+)-(kis|qa|trake)$", re.IGNORECASE)


def clamp_q(n: Any, max_q: int = MAX_QUESTIONS) -> int:
    try:
        v = int(round(float(n)))
    except (TypeError, ValueError):
        v = 1
    return max(1, min(max_q, v))


def _js_round(x: float) -> int:
    """Làm tròn ĐÚNG KIỂU Math.round của JS: .5 luôn lên trên.

    round() của Python là làm tròn ngân hàng (round(2.5) == 2) - dùng nó ở nhánh
    nào mà bên JS dùng Math.round là hai bên tính ra hai frame_idx khác nhau ở
    đúng những mốc .5, mà lệch một frame là mất điểm cả dòng. Chỉ đúng cho x ≥ 0
    (mọi chỗ gọi ở đây đều vậy: số frame và mốc mili-giây).
    """
    return int(x + 0.5)


def default_query_id(qid: int, task_type: str) -> str:
    return f"query-{qid}-{task_type}"


def _is_auto_query_id(query_id: Any) -> bool:
    return bool(_AUTO_QUERY_ID_RE.match(str(query_id or "").strip()))


def _retarget_query_id(query_id: Any, qid: int, task_type: str) -> str:
    """Sinh lại tên truy vấn tự động cho câu `qid` khi đổi task, GIỮ tiền tố đợt.

    Số câu và task luôn bám câu hiện tại, nhưng "p1" thì phải giữ: gói thật đặt
    tên "query-p1-15-qa", nuốt mất tiền tố là nộp file mang tên một truy vấn
    không tồn tại.
    ⚠ Mirror: retargetQueryId trong frontend/src/utils/submissionFormat.js.
    """
    m = _AUTO_QUERY_ID_RE.match(str(query_id or "").strip())
    prefix = m.group(1) if m else ""
    return f"query-{prefix}{qid}-{task_type}"


def default_question(qid: int) -> Dict[str, Any]:
    return {
        "taskType": "kis",
        "queryId": default_query_id(qid, "kis"),
        # True = tên truy vấn do BTC phát (nạp từ gói đề), KHÔNG được tự đổi theo
        # task nữa: file nộp phải trùng tên truy vấn thì mới được chấm.
        "queryIdLocked": False,
        "maxRows": MAX_ROWS,
        # Số event của đề TRAKE. None = chưa khai -> FE chặn nộp vì không biết
        # cắt chuỗi frame ở đâu.
        "numEvents": None,
        # Nội dung đề BTC phát (điền khi nhập gói truy vấn).
        "queryText": "",
        "items": [],
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_question(raw: Any, qid: int) -> Dict[str, Any]:
    base = default_question(qid)
    raw = raw if isinstance(raw, dict) else {}
    items = raw.get("items")
    num_events = raw.get("numEvents")
    return {
        "taskType": raw["taskType"] if isinstance(raw.get("taskType"), str) else base["taskType"],
        "queryId": raw["queryId"] if isinstance(raw.get("queryId"), str) else base["queryId"],
        "queryIdLocked": raw.get("queryIdLocked") is True,
        # Kẹp trần MAX_ROWS: snapshot từ phiên bản cũ có thể đang giữ maxRows > 100.
        "maxRows": min(int(raw["maxRows"]), MAX_ROWS) if isinstance(raw.get("maxRows"), (int, float)) and raw["maxRows"] > 0 else base["maxRows"],
        "numEvents": int(round(num_events)) if isinstance(num_events, (int, float)) and num_events > 0 else None,
        "queryText": raw["queryText"] if isinstance(raw.get("queryText"), str) else "",
        "items": [it for it in items if isinstance(it, dict) and it.get("id") is not None] if isinstance(items, list) else [],
    }


# Nhật ký lượt nộp của cả phòng. Ít mục hơn history nhiều: BTC chỉ cho 3 lượt
# mỗi gói, giữ 50 là đủ cho cả vòng thi.
SUBMIT_LOG_MAX = 50


def empty_state() -> Dict[str, Any]:
    return {"rev": 0, "numQuestions": 1, "questions": {}, "history": [], "submitLog": []}


def normalize_state(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    questions: Dict[str, Dict[str, Any]] = {}
    for key, q in (raw.get("questions") or {}).items():
        try:
            qid = int(key)
        except (TypeError, ValueError):
            continue
        if qid < 1:
            continue
        questions[str(qid)] = _normalize_question(q, qid)
    history = raw.get("history")
    submit_log = raw.get("submitLog")
    return {
        "rev": int(raw.get("rev") or 0),
        "numQuestions": clamp_q(raw.get("numQuestions", 1)),
        "questions": questions,
        "history": history if isinstance(history, list) else [],
        "submitLog": submit_log if isinstance(submit_log, list) else [],
    }


def _apply(state: Dict[str, Any], op: Dict[str, Any], member: Dict[str, str]) -> Optional[int]:
    """Áp dụng MỘT op tại chỗ. Trả về qid bị đổi, hoặc None nếu không đổi gì.

    Trả None khi không đổi là quan trọng: không tăng rev, không broadcast -> gõ
    lại đúng chữ cũ trong ô đáp án không làm 4 máy kia render lại.
    """
    op_type = op.get("type")

    if op_type == "clear_all":
        if not state["questions"]:
            return None
        state["questions"] = {}
        return -1  # -1 = đổi ở phạm vi toàn phòng, không riêng câu nào

    if op_type == "set_num_questions":
        num = clamp_q(op.get("value"))
        if num == state["numQuestions"]:
            return None
        state["numQuestions"] = num
        return -1

    # Nạp cấu hình từ gói truy vấn BTC - đề là của CẢ NHÓM nên đi qua op.
    #
    # Hai chế độ, khác nhau ở chỗ ĐỀ CŨ còn hay mất:
    #   * gộp (mặc định): chỉ ghi đè phần CẤU HÌNH (task/queryId/numEvents/
    #     queryText); items đã bỏ công tìm thì giữ nguyên. Dùng khi BTC phát bù
    #     một file hoặc sửa đề giữa vòng.
    #   * reset=True ("nhập lại từ đầu"): gói mới là ĐỀ CỦA VÒNG KHÁC, nên xoá
    #     sạch questions rồi dựng lại đúng theo gói. Phải xoá cả dict chứ không
    #     chỉ hạ numQuestions: câu ngoài phạm vi vẫn nằm nguyên trong state
    #     (xem hiddenWithData bên FE) và sẽ sống lại ngay khi vòng sau có nhiều
    #     câu hơn - kèm theo đáp án của vòng trước.
    if op_type == "import_package":
        parsed = op.get("items")
        if not isinstance(parsed, list):
            return None
        # Lọc TRƯỚC khi xoá: op rác (list toàn phần tử không phải dict) mà xoá
        # sạch giỏ rồi mới phát hiện không có gì để nạp thì cả phòng mất trắng.
        parsed = [p for p in parsed if isinstance(p, dict)]
        if not parsed:
            return None
        reset = op.get("reset") is True
        if reset:
            state["questions"] = {}
        # Gộp thì số câu chỉ được PHÌNH ra; nhập lại từ đầu thì bám đúng gói mới.
        max_qid = 0 if reset else state["numQuestions"]
        for p in parsed:
            key_q = clamp_q(p.get("qid"))
            key = str(key_q)
            entry = state["questions"].get(key)
            if entry is None:
                entry = default_question(key_q)
                state["questions"][key] = entry
            for src, dst in (("taskType", "taskType"), ("queryId", "queryId")):
                if p.get(src):
                    entry[dst] = p[src]
            # Tên này là của BTC -> khoá lại, không cho set_task_type đổi.
            entry["queryIdLocked"] = bool(p.get("queryId"))
            if p.get("queryText") is not None:
                entry["queryText"] = p["queryText"]
            if p.get("numEvents") is not None:
                entry["numEvents"] = p["numEvents"]
            max_qid = max(max_qid, key_q)
        state["numQuestions"] = clamp_q(max_qid)
        return -1

    qid = clamp_q(op.get("qid"))
    key = str(qid)
    q = state["questions"].get(key)
    if q is None:
        q = default_question(qid)
        state["questions"][key] = q
    items: List[Dict[str, Any]] = q["items"]

    if op_type == "add":
        item = op.get("item")
        if not isinstance(item, dict) or item.get("id") is None:
            return None
        # Idempotent theo id: gửi lại op sau khi mất mạng cũng không nhân đôi.
        if any(it.get("id") == item["id"] for it in items):
            return None
        item = dict(item)
        item["added_by"] = member.get("id")
        item["added_by_name"] = member.get("name")
        item["added_at"] = _now_ms()
        items.append(item)
        return qid

    if op_type == "remove":
        n = len(items)
        q["items"] = [it for it in items if it.get("id") != op.get("id")]
        return qid if len(q["items"]) != n else None

    if op_type == "move":
        idx = next((i for i, it in enumerate(items) if it.get("id") == op.get("id")), -1)
        if idx == -1:
            return None
        target = idx + int(op.get("dir") or 0)
        if target < 0 or target >= len(items) or target == idx:
            return None
        items[idx], items[target] = items[target], items[idx]
        return qid

    if op_type == "reorder":
        src = op.get("from_", op.get("from"))
        dst = op.get("to")
        if src is None or dst is None:
            return None
        src, dst = int(src), int(dst)
        if src == dst or not (0 <= src < len(items)) or not (0 <= dst < len(items)):
            return None
        items.insert(dst, items.pop(src))
        return qid

    if op_type in ("set_answer", "set_note"):
        field = "answer" if op_type == "set_answer" else "note"
        text = op.get("text") or ""
        changed = False
        for it in items:
            if it.get("id") == op.get("id") and it.get(field) != text:
                it[field] = text
                changed = True
        return qid if changed else None

    # Sửa TAY số frame của một mục - xem chú thích dài ở case "set_frame" trong
    # frontend/src/hooks/basketReducer.js. Ba điểm phải khớp từng bước với bên
    # đó: giá trị rác bị bỏ, frame_idx0 chỉ ghi ở LẦN SỬA ĐẦU, timestamp_ms
    # tính lại theo fps còn frame_name giữ nguyên.
    if op_type == "set_frame":
        raw_value = op.get("value")
        # bool là con của int trong Python: float(True) == 1.0, tức là một
        # frame_idx hợp lệ. Bên JS chặn boolean tường minh, ở đây phải chặn theo.
        if isinstance(raw_value, bool):
            return None
        try:
            raw = float(raw_value)
        except (TypeError, ValueError):
            return None
        # json của Python nhận cả NaN/Infinity (JS thì không) - _js_round sẽ ném
        # ValueError trên chúng và làm hỏng cả lượt apply_op.
        if raw != raw or raw in (float("inf"), float("-inf")):
            return None
        n = _js_round(raw)
        if n < 0:
            return None
        for it in items:
            if it.get("id") != op.get("id"):
                continue
            if it.get("frame_idx") == n:
                return None
            if "frame_idx0" not in it:
                it["frame_idx0"] = it.get("frame_idx")
            it["frame_idx"] = n
            try:
                fps = float(it.get("fps") or 0)
            except (TypeError, ValueError):
                fps = 0.0
            if fps > 0:
                it["timestamp_ms"] = _js_round(n / fps * 1000)
            return qid
        return None

    # Đổi task -> tên file nộp phải đổi theo (query-3-qa.csv chứ không còn -kis).
    # Chỉ tự sửa khi queryId vẫn là chuỗi do app sinh VÀ không phải tên BTC phát:
    # "query-3-qa" nạp từ gói đề cũng khớp mẫu tự sinh, tự đổi nó thành
    # "query-3-kis" là đổi luôn tên file nộp sang một truy vấn không tồn tại.
    if op_type == "set_task_type":
        value = op.get("value")
        if q.get("taskType") == value:
            return None
        q["taskType"] = value
        if _is_auto_query_id(q.get("queryId")) and not q.get("queryIdLocked"):
            q["queryId"] = _retarget_query_id(q.get("queryId"), qid, value)
        return qid

    # Sửa tay -> bỏ khoá: từ giờ người dùng tự chịu trách nhiệm cái tên đó.
    if op_type == "set_query_id":
        value = op.get("value")
        if q.get("queryId") == value:
            return None
        q["queryId"] = value
        q["queryIdLocked"] = False
        return qid

    if op_type == "set_max_rows":
        try:
            value = min(MAX_ROWS, max(1, int(op.get("value"))))
        except (TypeError, ValueError):
            value = 1
        if q.get("maxRows") == value:
            return None
        q["maxRows"] = value
        return qid

    # Số event của câu TRAKE; 0 / rác -> None (chưa khai).
    if op_type == "set_num_events":
        try:
            raw_n = int(round(float(op.get("value"))))
        except (TypeError, ValueError):
            raw_n = 0
        value = raw_n if raw_n > 0 else None
        if q.get("numEvents") == value:
            return None
        q["numEvents"] = value
        return qid

    if op_type == "set_query_text":
        value = op.get("value")
        if q.get("queryText") == value:
            return None
        q["queryText"] = value
        return qid

    if op_type == "clear_question":
        if not items:
            return None
        q["items"] = []
        return qid

    return None


class RoomStore:
    """State phòng + khoá + snapshot ra đĩa.

    Mọi endpoint đều `async def` và dùng asyncio.Lock (không phải threading.Lock
    như các service model khác): các thao tác ở đây chỉ đụng dict trong RAM nên
    chạy thẳng trên event loop, trộn hai mô hình khoá chỉ tổ dễ deadlock.
    """

    def __init__(self, path: Path, history_max: int = 200, debounce_s: float = 1.0):
        self._lock = asyncio.Lock()
        self._state: Dict[str, Any] = empty_state()
        self._path = path
        self._history_max = history_max
        self._debounce_s = debounce_s
        self._flush_task: Optional[asyncio.Task] = None
        self._dirty = False

    # --- Nạp / ghi đĩa -------------------------------------------------------
    def load(self) -> None:
        """Nạp snapshot lúc khởi động. File hỏng/thiếu -> phòng rỗng, KHÔNG crash:
        mất giỏ đã đủ tệ, thêm việc backend không lên được thì hết đường cứu."""
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._state = normalize_state(raw)
                n = sum(len(q["items"]) for q in self._state["questions"].values())
                print(f"[room] nạp snapshot: rev={self._state['rev']}, {n} frame trong giỏ")
                return
        except Exception as exc:  # noqa: BLE001 - hỏng kiểu gì cũng phải lên được
            print(f"[room] snapshot hỏng ({exc}) -> khởi tạo phòng rỗng")
        self._state = empty_state()

    def _write_now(self) -> None:
        """Ghi atomic: .tmp rồi os.replace. Ghi đè trực tiếp mà mất điện giữa
        chừng thì file cụt = mất sạch giỏ."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
            self._dirty = False
        except Exception as exc:  # noqa: BLE001
            print(f"[room] ghi snapshot lỗi: {exc}")

    def _schedule_flush(self) -> None:
        """Gom nhiều op liên tiếp (gõ từng chữ trong ô đáp án) thành một lần ghi."""
        self._dirty = True
        if self._flush_task and not self._flush_task.done():
            return

        async def _later():
            await asyncio.sleep(self._debounce_s)
            if self._dirty:
                self._write_now()

        try:
            self._flush_task = asyncio.get_running_loop().create_task(_later())
        except RuntimeError:
            self._write_now()  # không có loop (test đồng bộ) -> ghi luôn

    async def flush(self) -> None:
        """Ghi ngay - gọi lúc shutdown để không mất thao tác trong cửa sổ debounce."""
        async with self._lock:
            if self._dirty:
                self._write_now()

    # --- Đọc -----------------------------------------------------------------
    async def snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            return json.loads(json.dumps(self._state))  # bản sao sâu, tránh lộ dict gốc

    # --- Ghi -----------------------------------------------------------------
    async def apply_op(self, op: Dict[str, Any], member: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Áp dụng op. Trả về message để broadcast, hoặc None nếu state không đổi."""
        async with self._lock:
            changed = _apply(self._state, op, member)
            if changed is None:
                return None
            self._state["rev"] += 1
            rev = self._state["rev"]
            self._schedule_flush()

            by = member.get("name") or ""
            if changed == -1:
                # clear_all / set_num_questions đụng phạm vi rộng -> gửi cả snapshot
                # cho chắc, thay vì cố mô tả delta của 200 câu.
                if op.get("type") == "set_num_questions":
                    return {"type": "meta", "num_questions": self._state["numQuestions"], "rev": rev, "by": by}
                return {"type": "snapshot", "state": json.loads(json.dumps(self._state)), "rev": rev, "by": by}

            question = json.loads(json.dumps(self._state["questions"][str(changed)]))
            return {"type": "question", "qid": changed, "question": question, "rev": rev, "by": by}

    async def add_history(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            entry = {**entry, "id": uuid.uuid4().hex[:12], "ts": _now_ms()}
            hist = self._state["history"]
            # Chống trùng liên tiếp: 5 người thường chạy lại đúng query của nhau.
            if hist and hist[0].get("query") == entry["query"] and hist[0].get("mode") == entry["mode"]:
                hist[0] = entry
            else:
                hist.insert(0, entry)
                del hist[self._history_max:]
            self._schedule_flush()
            return {"type": "history_add", "entry": entry}

    async def add_submission(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Ghi một lượt tải zip nộp bài cho CẢ PHÒNG cùng đếm.

        Khác add_history ở chỗ `id` do client sinh và được giữ nguyên: máy tạo ra
        mục cần khử trùng bản local của chính nó với bản broadcast quay về. Gửi
        lại cùng id (mạng chập chờn, hàng đợi drain lại) không nhân đôi lượt -
        đếm lố lượt nộp cũng tai hại như đếm hụt.
        """
        async with self._lock:
            log: List[Dict[str, Any]] = self._state["submitLog"]
            if any(e.get("id") == entry.get("id") for e in log):
                return None
            log.insert(0, entry)
            del log[SUBMIT_LOG_MAX:]
            self._schedule_flush()
            return {"type": "submitlog_add", "entry": entry}

    async def clear_submissions(self) -> Optional[Dict[str, Any]]:
        """Xoá nhật ký nộp của cả phòng - dùng khi TẠO ĐỀ MỚI cho vòng sau.

        BTC đếm 3 lượt THEO GÓI truy vấn: vòng mới là gói mới nên bộ đếm phải về
        0. Xoá riêng bản local của một máy thì mục của 4 máy kia vẫn được trộn
        ngược vào (xem useSubmissionLog) và thanh "Lượt 2/3" tiếp tục nói dối.
        """
        async with self._lock:
            if not self._state["submitLog"]:
                return None
            self._state["submitLog"] = []
            self._schedule_flush()
            return {"type": "submitlog_clear"}
