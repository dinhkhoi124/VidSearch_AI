"""Step 01 - Keyframe extraction (TransNetV2 shot detection).

Ported from AIC-HCMC-2025/data_processing/keyframes_extraction.py and extended to
emit the backend's metadata file.

Inputs : raw videos matched by config.RAW_VIDEOS_GLOB
Outputs:
    media/frames/<video_name>/<frame>.jpg      one image per selected keyframe
    data/metadata/frames_meta.json             {frame_id: {video_name, frame_name,
                                                            timestamp_ms, fps}}

The pipeline is resumable: existing keyframe images are skipped and the metadata
file is merged, so it can be re-run after adding new videos.

Tip: if you trust the official map-keyframes CSVs more than re-running shot
detection, use 01b_keyframes_from_map.py instead - it produces the same outputs.
"""
import json
import os
from glob import glob

from tqdm import tqdm

import config
from utils.frame_extract import (
    extract_resize_and_save_frame,
    frame_id_of,
    frame_name_of,
    get_video_fps,
    video_name_of,
)
from utils.transnet import load_transnetv2, scenes_to_keyframe_indices


def load_existing_meta() -> dict:
    if config.FRAMES_META_FILE.exists():
        with config.FRAMES_META_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_meta(meta: dict) -> None:
    with config.FRAMES_META_FILE.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def main() -> None:
    config.ensure_dirs()

    video_paths = sorted(glob(config.RAW_VIDEOS_GLOB))
    print(f"[INFO] Found {len(video_paths)} videos via {config.RAW_VIDEOS_GLOB}")
    if not video_paths:
        return

    model = load_transnetv2()
    frames_meta = load_existing_meta()

    for video_path in video_paths:
        video_name = video_name_of(video_path)
        fps = get_video_fps(video_path)
        print(f"[INFO] Shot detection for {video_name} (fps={fps:.3f})")

        _, single_frame_predictions, _ = model.predict_video(video_path)
        frame_ranges = model.predictions_to_scenes(single_frame_predictions)
        keyframe_indices = scenes_to_keyframe_indices(frame_ranges)

        save_folder = config.FRAMES_DIR / video_name
        save_folder.mkdir(parents=True, exist_ok=True)

        for frame_index in tqdm(sorted(set(keyframe_indices)), desc=video_name):
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
                "timestamp_ms": int(frame_index / fps * 1000),
                "fps": fps,
            }

        save_meta(frames_meta)  # checkpoint after every video

    print(f"[INFO] Wrote {len(frames_meta)} frame entries -> {config.FRAMES_META_FILE}")


if __name__ == "__main__":
    main()
