"""Step 02 - Image-embedding extraction (model-agnostic).

Encodes every keyframe with the backbone selected by config.MODEL_KEY
(clip | siglip | jina | beit3 - see utils/encoders.py).

Inputs : media/frames/<video_name>/<frame>.jpg          (from step 01 / 01b)
Outputs: data/features/<MODEL_KEY>/<video_name>/<frame>.npy   L2-normalised float32

Outputs are namespaced per model, so you can extract several backbones without
them clobbering each other. Step 03 builds a FAISS index from one model's folder.
Resumable: existing .npy files are skipped.

Examples:
    python 02_extract_features.py                 # config default (clip)
    MODEL_KEY=siglip python 02_extract_features.py
    MODEL_KEY=jina   python 02_extract_features.py
"""
from glob import glob
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

import config
from utils.encoders import get_encoder


def main() -> None:
    config.ensure_dirs()
    encoder = get_encoder()  # honours config.MODEL_KEY
    out_base = config.model_features_dir()

    video_folders = sorted(p for p in config.FRAMES_DIR.glob("*") if p.is_dir())
    print(f"[INFO] {len(video_folders)} video folders | model={config.MODEL_KEY} "
          f"-> {out_base}")

    for folder in video_folders:
        video_name = folder.name
        keyframe_paths = sorted(glob(str(folder / f"*.{config.FRAME_EXT}")))

        out_folder = out_base / video_name
        out_folder.mkdir(parents=True, exist_ok=True)

        # Only the frames we have not embedded yet.
        todo = [p for p in keyframe_paths if not (out_folder / f"{Path(p).stem}.npy").exists()]
        if not todo:
            continue

        for i in tqdm(range(0, len(todo), config.EMBED_BATCH_SIZE), desc=video_name):
            batch = todo[i:i + config.EMBED_BATCH_SIZE]
            images = [Image.open(p).convert("RGB") for p in batch]
            vecs = encoder.encode_image(images)
            for p, vec in zip(batch, vecs):
                np.save(out_folder / f"{Path(p).stem}.npy", vec.astype(np.float32))


if __name__ == "__main__":
    main()
