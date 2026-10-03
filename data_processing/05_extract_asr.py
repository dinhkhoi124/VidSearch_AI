"""Step 05 - ASR transcription (faster-whisper).

New for HCM-AIC-2026 (the 2025 pipeline had no ASR). Produces exactly what the
backend's asr_service consumes:

    data/asr/asr_data.json = {
        "<video_name>": [
            {"start_ms": 0, "end_ms": 5000, "text": "..."},
            ...
        ],
        ...
    }

Inputs : raw videos matched by config.RAW_VIDEOS_GLOB (audio is decoded directly).
Resumable: videos already present in asr_data.json are skipped; checkpointed per
video. faster-whisper accepts media files directly, so no manual audio extraction
is needed (ffmpeg must be installed).
"""
import json
from glob import glob

from tqdm import tqdm

import config
from utils.frame_extract import video_name_of


def load_existing() -> dict:
    if config.ASR_FILE.exists():
        with config.ASR_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(asr_data: dict) -> None:
    with config.ASR_FILE.open("w", encoding="utf-8") as f:
        json.dump(asr_data, f, ensure_ascii=False, indent=2)


def main() -> None:
    config.ensure_dirs()
    from faster_whisper import WhisperModel

    import torch  # only to pick device/compute type
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"[INFO] Loading faster-whisper '{config.ASR_MODEL_SIZE}' on {device} ({compute_type})")
    model = WhisperModel(config.ASR_MODEL_SIZE, device=device, compute_type=compute_type)

    asr_data = load_existing()
    video_paths = sorted(glob(config.RAW_VIDEOS_GLOB))
    print(f"[INFO] {len(video_paths)} videos; {len(asr_data)} already transcribed")

    for video_path in tqdm(video_paths, desc="asr"):
        video_name = video_name_of(video_path)
        if video_name in asr_data:
            continue

        segments, _ = model.transcribe(
            video_path, language=config.ASR_LANGUAGE, vad_filter=True
        )
        asr_data[video_name] = [
            {
                "start_ms": int(seg.start * 1000),
                "end_ms": int(seg.end * 1000),
                "text": seg.text.strip(),
            }
            for seg in segments
        ]
        save(asr_data)  # checkpoint per video

    print(f"[INFO] Wrote ASR for {len(asr_data)} videos -> {config.ASR_FILE}")


if __name__ == "__main__":
    main()
