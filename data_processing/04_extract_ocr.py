"""Step 04 - OCR extraction (EasyOCR).

Adapted from AIC-HCMC-2025/data_processing/stuff/ocr_extraction.py, but written in
the shape the backend's ocr_service expects: a single flat dict

    data/ocr/ocr_data.json = { "<frame_id>": "joined ocr text", ... }

Inputs : media/frames/<video_name>/<frame>.jpg
Resumable: frames already present in ocr_data.json are skipped; the file is
checkpointed every OCR_BATCH_SIZE frames.
"""
import json
from glob import glob
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

import config
from utils.frame_extract import frame_id_of


def load_existing() -> dict:
    if config.OCR_FILE.exists():
        with config.OCR_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(ocr_data: dict) -> None:
    with config.OCR_FILE.open("w", encoding="utf-8") as f:
        json.dump(ocr_data, f, ensure_ascii=False, indent=2)


def main() -> None:
    config.ensure_dirs()
    import easyocr

    reader = easyocr.Reader(config.OCR_LANGS)
    ocr_data = load_existing()

    keyframe_paths = sorted(glob(str(config.FRAMES_DIR / "*" / f"*.{config.FRAME_EXT}")))
    todo = []
    for p in keyframe_paths:
        path = Path(p)
        frame_id = frame_id_of(path.parent.name, int(path.stem))
        if frame_id not in ocr_data:
            todo.append((frame_id, p))

    print(f"[INFO] {len(keyframe_paths)} keyframes, {len(todo)} need OCR "
          f"(batch={config.OCR_BATCH_SIZE}, langs={config.OCR_LANGS})")

    for i in tqdm(range(0, len(todo), config.OCR_BATCH_SIZE), desc="ocr"):
        batch = todo[i:i + config.OCR_BATCH_SIZE]
        images, valid = [], []
        for frame_id, p in batch:
            try:
                images.append(np.array(Image.open(p).convert("RGB")))
                valid.append((frame_id, p))
            except Exception as exc:
                print(f"[WARN] open {p}: {exc}")

        results = reader.readtext_batched([img for img in images], detail=1) if images else []
        for (frame_id, _), res in zip(valid, results):
            lines = [line[1] for line in res if isinstance(line, (list, tuple)) and len(line) >= 2]
            ocr_data[frame_id] = " ".join(lines).strip()

        save(ocr_data)  # checkpoint

    print(f"[INFO] Wrote {len(ocr_data)} OCR entries -> {config.OCR_FILE}")


if __name__ == "__main__":
    main()
