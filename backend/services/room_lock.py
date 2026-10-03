"""Khoá "đúng một tiến trình được sở hữu file state phòng".

VÌ SAO CẦN: state phòng nằm trong MỘT file JSON, mỗi tiến trình giữ một bản
trong RAM và ghi đè cả file mỗi lần flush (xem services/room_store.py). Lỡ chạy
hai tiến trình cùng trỏ vào file đó - main.py và scripts/room_server.py, hay hai
lần bấm chạy - thì bên flush sau xoá sạch việc của bên kia: cả giỏ đáp án của
phòng biến mất giữa lúc thi. Rẻ hơn nhiều là bên thứ hai tự tắt /room ngay.

CÁCH LÀM: khoá của HỆ ĐIỀU HÀNH trên file `<state>.lock` cạnh file state, và
GIỮ NGUYÊN fd cho tới lúc tiến trình chết. Cố ý không có release() công khai:
khoá phải sống đúng bằng đời tiến trình, mở một hàm nhả khoá ra chỉ tạo cơ hội
cho ai đó gọi nhầm giữa lúc chạy thật. Tiến trình chết kiểu gì - kể cả kill -9
- HĐH cũng tự nhả, nên không có chuyện khoá chết kẹt lại.

LƯU Ý: khoá HĐH luôn cho CHÍNH CHỦ lấy lại, nên gọi acquire() lần hai trong
cùng tiến trình sẽ trả None. Chỉ tiến trình KHÁC mới bị từ chối.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, IO, Optional

# Giữ tham chiếu tới fd đang cầm khoá: rơi khỏi đây là bị GC đóng file, và HĐH
# nhả khoá ngay lúc đó - tiến trình thứ hai vào ghi đè trong khi ta vẫn chạy.
_held: Dict[str, IO[str]] = {}


def _lock_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.name + ".lock")


def _lock_exclusive(fh: IO[str]) -> None:
    """Khoá độc quyền, KHÔNG chờ. Ném OSError nếu bên khác đang giữ."""
    try:
        import fcntl  # noqa: PLC0415 - POSIX

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        import msvcrt  # noqa: PLC0415 - Windows

        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)


def _read_holder(lock_file: Path) -> Dict[str, Any]:
    """Đọc danh tính bên đang giữ khoá. Mở fd RIÊNG: fd của ta có thể đang ở
    trạng thái dở dang, còn trên Windows vùng byte bị khoá có thể không đọc được
    - thiếu thông tin thì báo chung chung, đừng để hỏng luôn thông báo lỗi."""
    try:
        return json.loads(lock_file.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}


def acquire(state_path: Path, label: str) -> Optional[str]:
    """Giành quyền sở hữu file state.

    Trả None nếu giành được. Nếu thua, trả câu giải thích ĐỌC ĐƯỢC cho người
    chạy: phải nói rõ ai đang giữ và PID nào, vì cách sửa duy nhất là đi tắt
    tiến trình kia.
    """
    lock_file = _lock_path(state_path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # "a+" chứ không "w": "w" cắt file NGAY lúc mở, tức xoá danh tính của bên
    # đang giữ khoá trước cả khi biết mình có giành được hay không.
    fh = open(lock_file, "a+", encoding="utf-8")
    try:
        _lock_exclusive(fh)
    except OSError:
        fh.close()
        holder = _read_holder(lock_file)
        who = holder.get("label") or "một tiến trình khác"
        pid = holder.get("pid", "?")
        return (
            f"Một tiến trình khác đang giữ state phòng ({state_path.name}): "
            f"{who}, PID {pid}. Tắt tiến trình đó rồi chạy lại, "
            f"hoặc đặt ROOM_ENABLED=false cho tiến trình này."
        )

    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps({"label": label, "pid": os.getpid()}, ensure_ascii=False))
    fh.flush()
    _held[str(lock_file)] = fh
    return None
