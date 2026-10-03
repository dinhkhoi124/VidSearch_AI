"""Step 01b - Keyframe extraction from the OFFICIAL map-keyframes CSVs.

Alternative to 01_extract_keyframes.py. Instead of re-running TransNetV2, it uses
the organiser-provided keyframe maps (config.MAP_KEYFRAMES_DIR), one CSV per video
with columns:  n,pts_time,fps,frame_idx

Using these guarantees our frame indices match the official keyframe ids that the
submission format is graded against. Produces the exact same outputs as step 01:

    media/frames/<video_name>/<frame>.jpg
    data/metadata/frames_meta.json

A source .mp4 (matched by RAW_VIDEOS_GLOB) is still required to read the pixels.
"""
import csv
import json
from glob import glob

from tqdm import tqdm

import config
from utils.frame_extract import (
    extract_resize_and_save_frame,
    frame_id_of,
    frame_name_of,
    video_name_of,
)

# 01_extract_keyframes shares the same metadata helpers.
from importlib import import_module

_kf = import_module("01_extract_keyframes")
load_existing_meta = _kf.load_existing_meta
save_meta = _kf.save_meta


def index_videos_by_name() -> dict:
    """Map "L21_V001" -> absolute .mp4 path."""
    return {video_name_of(p): p for p in glob(config.RAW_VIDEOS_GLOB)}


def main() -> None:
    config.ensure_dirs()

    videos_by_name = index_videos_by_name()
    csv_files = sorted(config.MAP_KEYFRAMES_DIR.glob("*.csv"))
    print(f"[INFO] Found {len(csv_files)} map-keyframe CSVs in {config.MAP_KEYFRAMES_DIR}")

    frames_meta = load_existing_meta()

    for csv_file in csv_files:
        video_name = csv_file.stem
        video_path = videos_by_name.get(video_name)
        if video_path is None:
            print(f"[WARN] No source video for {video_name}, skipping")
            continue

        save_folder = config.FRAMES_DIR / video_name
        save_folder.mkdir(parents=True, exist_ok=True)

        with csv_file.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        for row in tqdm(rows, desc=video_name):
            frame_index = int(row["frame_idx"])
            fps = float(row["fps"])
            pts_time = float(row["pts_time"])

            frame_name = frame_name_of(frame_index, config.FRAME_EXT)
            frame_path = save_folder / frame_name
            if not frame_path.exists():
                try:
                    extract_resize_and_save_frame(
                        video_path, frame_index, str(frame_path), scale=config.FRAME_SCALE
                    )
                except (IndexError, RuntimeError) as exc:
                    print(f"[WARN] {video_name} frame {frame_index}: {exc}")
                    continue

            frame_id = frame_id_of(video_name, frame_index)
            frames_meta[frame_id] = {
                "video_name": video_name,
                "frame_name": frame_name,
                "timestamp_ms": int(pts_time * 1000),
                "fps": fps,
            }

        save_meta(frames_meta)

    print(f"[INFO] Wrote {len(frames_meta)} frame entries -> {config.FRAMES_META_FILE}")


if __name__ == "__main__":
    main()
