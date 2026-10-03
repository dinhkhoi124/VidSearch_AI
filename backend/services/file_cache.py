"""Cache dữ liệu đọc từ đĩa, TỰ NẠP LẠI khi file đổi.

Thay cho `@lru_cache` trên các hàm `_load_*()`. `lru_cache` giữ kết quả vĩnh viễn
trong tiến trình, nên quy trình cập nhật dữ liệu thường gặp:

    cp ocr_data.json backend/data/ocr/    # ghi đè bằng output Qwen
    curl .../search_ocr?query=...          # vẫn ra kết quả EasyOCR cũ

lại im lặng phục vụ dữ liệu cũ cho tới khi có người nghĩ ra là phải restart. Ở đây
mỗi lần lấy dữ liệu ta `stat()` file (rẻ, ~µs) và chỉ nạp lại khi
`(st_mtime_ns, st_size)` đổi.

`stamp()` được export để các cấu trúc PHÁI SINH từ file (ví dụ BM25 index trong
`lexical_service`) gắn theo và tự vô hiệu cùng lúc - nếu không, dữ liệu nạp lại
nhưng index cũ vẫn còn thì còn khó hiểu hơn cả bug ban đầu.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

# path -> (stamp, value). Khoá riêng vì uvicorn có thể chạy nhiều thread.
_CACHE: Dict[str, Tuple[Optional[tuple], Any]] = {}
_LOCK = threading.Lock()

Stamp = Optional[Tuple[int, int]]


def stamp(path: Path) -> Stamp:
    """(mtime_ns, size) của file, hoặc None nếu chưa tồn tại.

    None cũng là một trạng thái hợp lệ và được cache: file thiếu -> giá trị mặc
    định. Khi file được tạo ra sau đó, stamp đổi từ None -> tuple nên cache tự
    vô hiệu (quan trọng với caption_data.json - hiện chưa có, sẽ có sau khi
    chạy Qwen).
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def cached(path: Path, loader: Callable[[Path], Any], default: Any = None) -> Any:
    """Gọi `loader(path)` một lần cho mỗi phiên bản của file.

    File thiếu -> trả `default` mà không gọi loader.
    """
    key = str(path)
    cur = stamp(path)

    hit = _CACHE.get(key)
    if hit is not None and hit[0] == cur:
        return hit[1]

    with _LOCK:
        hit = _CACHE.get(key)  # có thể thread khác đã nạp xong khi ta chờ khoá
        if hit is not None and hit[0] == cur:
            return hit[1]
        value = default if cur is None else loader(path)
        _CACHE[key] = (cur, value)
        return value


def cached_json(path: Path, default: Any = None) -> Any:
    """JSON đọc theo mtime. `default` được dùng khi file chưa tồn tại."""

    def _load(p: Path) -> Any:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    return cached(path, _load, default)


def clear(path: Optional[Path] = None) -> None:
    """Xoá cache (một file hoặc tất cả). Dùng cho test."""
    with _LOCK:
        if path is None:
            _CACHE.clear()
        else:
            _CACHE.pop(str(path), None)


def describe(paths: Dict[str, Path]) -> Dict[str, dict]:
    """Mô tả trạng thái file cho /health: có tồn tại không, đổi lần cuối lúc nào.

    Đây là cách nhanh nhất để trả lời "dữ liệu Qwen mới đã vào production chưa?"
    mà không phải đoán.
    """
    import datetime

    out: Dict[str, dict] = {}
    for name, p in paths.items():
        s = stamp(p)
        if s is None:
            out[name] = {"present": False}
            continue
        mtime_ns, size = s
        out[name] = {
            "present": True,
            "size_bytes": size,
            "modified": datetime.datetime.fromtimestamp(
                mtime_ns / 1e9, tz=datetime.timezone.utc
            ).isoformat(timespec="seconds"),
        }
    return out
