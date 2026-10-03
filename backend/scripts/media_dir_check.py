"""Kiểm tra MEDIA_DIR trước giờ thi - đường ảnh có thật sự lấy được pixel không.

    python scripts/media_dir_check.py            # dùng MEDIA_DIR trong .env
    python scripts/media_dir_check.py /content/media_root

Đường ảnh là chỗ hỏng ÂM THẦM tệ nhất của hệ thống: sai thì search vẫn trả kết
quả bình thường, chỉ có rerank visual và /agent/qa lặng lẽ chạy mù. Script này
đọc thật 100 keyframe ngẫu nhiên qua đúng hàm mà rerank dùng, rồi báo tốc độ.

Không nạp model, không cần GPU - chạy vài giây.

Chạy sau khi đặt MEDIA_DIR, và so tốc độ để quyết định chỗ đặt kho ảnh:
  < 2s / 100 frame   : tốt
  2-10s              : chậm hơn tunnel lành lặn, cân nhắc chuyển sang đĩa local
  > 10s              : không dùng được (thường là đọc thẳng từ Drive đã mount)
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402

SAMPLE = 100


def main() -> int:
    settings = get_settings()
    if len(sys.argv) > 1:
        # Ghi đè để thử nhanh mà không phải sửa .env. get_settings có lru_cache
        # nên phải đặt trước khi metadata_service đọc - import nằm dưới đây.
        settings.media_dir = sys.argv[1]

    from services import metadata_service as M

    if not settings.media_dir:
        print("MEDIA_DIR trống -> BE lấy ảnh qua HTTP từ MEDIA_BASE_URL =", settings.media_base)
        print("Script này chỉ kiểm đường ĐĨA. Đặt MEDIA_DIR rồi chạy lại,")
        print("hoặc truyền thẳng: python scripts/media_dir_check.py <thu_muc>")
        return 1

    root = settings.media_path
    print(f"MEDIA_DIR      = {root}")
    print(f"MEDIA_BASE_URL = {settings.media_base}   (chỉ dùng cho URL trả về trình duyệt)")

    kf = root / "media" / "frames" / "Keyframes"
    if not kf.is_dir():
        print(f"\nKHÔNG THẤY {kf}")
        print("MEDIA_DIR phải trỏ vào thư mục CHỨA `media/`, không phải chính `media/`.")
        return 1

    batches = sorted(p for p in kf.iterdir() if p.is_dir())
    print(f"\n{len(batches)} batch: {', '.join(p.name for p in batches[:12])}"
          + (" ..." if len(batches) > 12 else ""))

    # Mẫu NGẪU NHIÊN trải khắp video - đọc tuần tự trong một thư mục sẽ được
    # cache che mất và cho ra con số đẹp giả. Rerank lấy 100 frame rải rác.
    pool = []
    for b in batches:
        for v in sorted(p for p in b.iterdir() if p.is_dir()):
            files = list(v.glob("*.webp"))
            if files:
                pool.append((v.name, random.choice(files).name))
    if not pool:
        print("Không tìm thấy file .webp nào.")
        return 1
    random.shuffle(pool)
    sample = pool[:SAMPLE]
    print(f"{len(pool)} video có keyframe; lấy mẫu {len(sample)}")

    M._frame_cache.clear()
    t0 = time.time()
    blobs = M.frame_bytes_many(sample)
    dt = time.time() - t0

    ok = sum(1 for b in blobs if b)
    mb = sum(len(b) for b in blobs if b) / 1e6
    print(f"\n{ok}/{len(sample)} frame, {mb:.1f} MB trong {dt:.2f}s"
          f"  ({dt * 1000 / len(sample):.1f} ms/frame)")

    if ok != len(sample):
        print("\nCÓ FRAME KHÔNG ĐỌC ĐƯỢC -> rerank visual và /agent/qa sẽ chạy mù.")
        print("Xem các dòng [media] ở trên để biết đường dẫn nào sai.")
        return 1
    if dt > 10:
        print("\nCHẬM: >10s cho một lượt rerank. Nếu đang đọc từ Drive đã mount thì")
        print("chuyển kho ảnh sang đĩa local của máy chạy BE (giải nén từ archive).")
        return 1
    if dt > 2:
        print("\nHơi chậm nhưng dùng được. Đĩa local sẽ nhanh hơn đáng kể.")
    else:
        print("\nĐường ảnh TỐT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
