"""FAISS search over the OCR/ASR *text* indexes (semantic search).

On-disk layout (built by data_processing Step 07):
    data/indexes/ocr_text.index        FAISS IndexFlatIP over passage embeddings
    data/indexes/ocr_text_ids.json     ["<frame_id>", ...] aligned to index rows
    data/indexes/asr_text.index        FAISS IndexFlatIP over passage embeddings
    data/indexes/asr_text_meta.json    [{video_name,start_ms,end_ms,text}, ...] per row

Không có mock fallback (giống `faiss_service`, khác ở cách báo): thiếu index thì
caller bỏ qua lượt semantic và dùng exact substring - vẫn ra kết quả dùng được
nên không cần 503 như bên visual.
`search_text_index` returns row numbers + cosine scores; the caller resolves rows
against the matching ids/meta file.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import List, Optional, Tuple

import numpy as np

from config import get_settings

settings = get_settings()


@lru_cache
def load_sidecar(name: str) -> Optional[list]:
    """Load the ids/meta JSON aligned to <name>.index rows (e.g. 'ocr_text_ids')."""
    path = settings.data_path / "indexes" / f"{name}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def _load_index(name: str):
    """Load <name>.index once, or None if missing / faiss unavailable."""
    path = settings.data_path / "indexes" / f"{name}.index"
    if not path.exists():
        return None
    try:
        import faiss

        index = faiss.read_index(str(path))
        print(f"[text-faiss] loaded {path} ({index.ntotal} vectors, dim={index.d})")
        return index
    except Exception as e:  # noqa: BLE001
        print(f"[text-faiss] could not load {path} ({e!r})")
        return None


# Tên file sidecar đi kèm mỗi index (rows của index ánh xạ sang phần tử nào).
SIDECAR_OF = {
    "ocr_text": "ocr_text_ids",
    "asr_text": "asr_text_meta",
    "caption_text": "caption_text_ids",
}


def preload(name: str) -> Optional[dict]:
    """Nạp sẵn <name>.index + sidecar vào cache (dùng lúc warm-up).

    Trả {vectors, dim, rows} khi index tồn tại, None khi thiếu file/faiss.
    """
    index = _load_index(name)
    if index is None:
        return None
    sidecar = load_sidecar(SIDECAR_OF.get(name, f"{name}_ids"))
    return {
        "vectors": int(index.ntotal),
        "dim": int(index.d),
        "rows": len(sidecar or []),
    }


def search_text_index(
    query_vector: np.ndarray, top_k: int, name: str
) -> List[Tuple[int, float]]:
    """Return [(row, cosine_score), ...] for <name>.index, or [] if unavailable."""
    index = _load_index(name)
    if index is None or index.ntotal == 0:
        return []

    import faiss

    q = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
    if q.shape[1] != index.d:
        print(
            f"[text-faiss] query dim {q.shape[1]} != index dim {index.d} for '{name}'; "
            f"skipping semantic pass (rebuild index with the active text model)"
        )
        return []
    faiss.normalize_L2(q)  # cosine == inner product on unit vectors

    k = min(top_k, index.ntotal)
    scores, idxs = index.search(q, k)
    return [(int(i), float(s)) for s, i in zip(scores[0], idxs[0]) if i >= 0]
