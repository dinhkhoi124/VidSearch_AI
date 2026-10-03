"""Step 03b - Build `data/metadata/keyframe_index.json`.

Sinh manifest `{ "<video_name>": ["000000.webp", "000025.webp", ...], ... }`
từ thư mục keyframe trên disk. BE `/frame_neighbors` đọc file này để liệt kê
frame (giờ BE không còn quyền truy cập trực tiếp thư mục media vì media đã
chuyển sang FE).

Chạy sau step 01 (extract_keyframes) hoặc 01b (keyframes_from_map), KHÔNG cần
chạy lại khi đã có file - manifest phản ánh trạng thái hiện tại của
`backend/media/frames/Keyframes/<batch>/<video_name>/*.webp` (hoặc thư mục
đích tương đương). Nếu sau này keyframe chuyển sang thư mục khác (vd
`frontend/public/media/frames/...`), truyền `--frames-root` để trỏ tới đó.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import config


def collect(frames_root: Path) -> dict:
    """Quét frames_root/<batch>/<video_name>/*.webp -> {video_name: [names]}.

    Bỏ qua video rỗng. Tên frame giữ nguyên dạng zero-padded để lexical sort
    tương đương sort theo số - đúng như router `frames.py` đang dựa.
    """
    out: dict[str, list[str]] = defaultdict(list)
    if not frames_root.is_dir():
        return {}
    for batch_dir in sorted(frames_root.iterdir()):
        if not batch_dir.is_dir():
            continue
        for video_dir in sorted(batch_dir.iterdir()):
            if not video_dir.is_dir():
                continue
            names = sorted(
                p.name for p in video_dir.iterdir()
                if p.suffix.lower() == ".webp"
            )
            if names:
                out[video_dir.name] = names
    return dict(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build keyframe_index.json manifest")
    ap.add_argument(
        "--frames-root",
        type=Path,
        default=config.MEDIA_DIR / "frames" / "Keyframes",
        help="Thư mục gốc chứa <batch>/<video_name>/*.webp "
             "(mặc định: backend/media/frames/Keyframes)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=config.KEYFRAME_INDEX_FILE,
        help="Đường dẫn file JSON đầu ra",
    )
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    index = collect(args.frames_root)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)

    total_videos = len(index)
    total_frames = sum(len(v) for v in index.values())
    print(f"[INFO] wrote {args.out}")
    print(f"[INFO] {total_videos} videos, {total_frames} keyframes")


if __name__ == "__main__":
    main()