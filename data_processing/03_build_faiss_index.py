"""Step 03 - Build the FAISS index from image features.

Inputs : data/features/<MODEL_KEY>/<video_name>/<frame>.npy   (from step 02)
Outputs:
    data/indexes/<MODEL_KEY>.index   FAISS index (inner-product over L2-normed = cosine)
    data/indexes/id_map.json         ["<frame_id>", ...] aligned to index rows

Builds the index for the model selected by config.MODEL_KEY. The backend's
faiss_service loads ``data/indexes/<model>.index`` and ``data/indexes/id_map.json``
and returns ids by row, which metadata_service resolves against frames_meta.json.
The frame_id therefore MUST match the keys in frames_meta.json (e.g. "L21_V001_000080").

Near-duplicate filtering (config.DEDUP_THRESHOLD, default 0.9): consecutive
frames of a video whose cosine similarity with the last kept frame exceeds the
threshold are skipped, so the index is not padded with visually identical rows
and top-k results stop being dominated by one static scene. The .npy files and
keyframe images stay on disk - rebuilding with DEDUP_THRESHOLD=0 restores them.

The id_map is written per model (id_map_<MODEL_KEY>.json): dedup decisions
depend on the model's embeddings, so each model keeps its own frame subset.
"""
import json
from glob import glob
from pathlib import Path

import faiss
import numpy as np
from tqdm import tqdm

import config
from utils.frame_extract import frame_id_of


def main() -> None:
    config.ensure_dirs()

    features_dir = config.model_features_dir()
    npy_paths = sorted(glob(str(features_dir / "*" / "*.npy")))
    print(f"[INFO] model={config.MODEL_KEY} | found {len(npy_paths)} vectors in {features_dir}")
    if not npy_paths:
        print("[WARN] Nothing to index. Run step 02 first (matching MODEL_KEY).")
        return

    threshold = config.DEDUP_THRESHOLD
    ids, vectors = [], []
    last_kept: np.ndarray | None = None
    last_video = None
    dropped = 0
    for npy_path in tqdm(npy_paths, desc="loading"):
        path = Path(npy_path)
        video_name = path.parent.name                  # video_name folder
        frame_index = int(path.stem)                   # e.g. "000080" -> 80
        vec = np.load(npy_path).astype(np.float32).reshape(-1)

        if threshold > 0:
            if video_name != last_video:
                last_kept, last_video = None, video_name
            v = vec / (np.linalg.norm(vec) + 1e-9)
            if last_kept is not None and float(np.dot(v, last_kept)) > threshold:
                dropped += 1
                continue
            last_kept = v

        ids.append(frame_id_of(video_name, frame_index))
        vectors.append(vec)

    if dropped:
        print(f"[INFO] dedup: dropped {dropped}/{len(npy_paths)} near-duplicate frames "
              f"(cosine > {threshold})")

    matrix = np.vstack(vectors)
    dim = matrix.shape[1]
    faiss.normalize_L2(matrix)  # guarantee unit norm -> inner product == cosine

    index = faiss.IndexFlatIP(dim)
    index.add(matrix)
    print(f"[INFO] Built IndexFlatIP: {index.ntotal} vectors, dim={dim}")

    index_path = config.index_file()
    faiss.write_index(index, str(index_path))
    id_map_path = config.id_map_file()
    with id_map_path.open("w", encoding="utf-8") as f:
        json.dump(ids, f, ensure_ascii=False)

    print(f"[INFO] Wrote {index_path}")
    print(f"[INFO] Wrote {id_map_path} ({len(ids)} ids)")


if __name__ == "__main__":
    main()
