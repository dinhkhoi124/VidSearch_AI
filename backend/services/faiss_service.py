"""FAISS nearest-neighbour search.

On-disk layout (built by data_processing Step 5 / create-bin):
    data/indexes/<model>.index       # FAISS IndexFlatIP (cosine over L2-normed vecs)
    data/indexes/id_map.json         # ["frame_id_0", "frame_id_1", ...] aligned to index rows

Thiếu index thì KHÔNG có mock: `search_index` ném IndexUnavailable, main.py đổi
thành HTTP 503 kèm tên file còn thiếu.

Trước đây chỗ này rơi về mock search - trả 40 frame_id bịa (`video_L01_V001_*`)
với điểm số ngẫu nhiên. Nhìn từ UI thì y hệt một lượt search thật, chỉ khác là
mọi URL ảnh trỏ vào video không tồn tại nên lưới toàn ô xám. Một dòng .env sai
(DEFAULT_MODEL trỏ vào model chưa build index) mất hàng giờ mới truy ra, và nếu
xảy ra giữa buổi thi thì còn tệ hơn: không ai nghi ngờ kết quả trông có vẻ bình
thường. Thà 503 ngay.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import List, Optional

import numpy as np

from config import get_settings

settings = get_settings()


class IndexUnavailable(RuntimeError):
    """Model được yêu cầu không có index dùng được trên đĩa.

    main.py bắt ngoại lệ này và trả 503 kèm nguyên văn message, nên message phải
    nói rõ THIẾU FILE NÀO - đó là thứ người trực máy cần để sửa ngay.
    """


@lru_cache
def _load_id_map(model: str) -> List[str]:
    # Prefer a per-model id map (id_map_<model>.json), else the shared id_map.json
    base = settings.data_path / "indexes"
    for name in (f"id_map_{model}.json", "id_map.json"):
        path = base / name
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    return []


@lru_cache
def _load_index(model: str):
    """Load <model>.index once, or None if missing / faiss unavailable."""
    path = settings.data_path / "indexes" / f"{model}.index"
    if not path.exists():
        # Log giu ASCII: console Windows mac dinh cp1252, in tieng Viet co dau
        # se nem UnicodeEncodeError ngay trong duong search. Message cua
        # IndexUnavailable thi khong sao - no di ra JSON (UTF-8).
        print(f"[faiss] THIEU index: {path} - model '{model}' se tra 503")
        return None
    try:
        import faiss
        index = faiss.read_index(str(path))
        print(f"[faiss] loaded {path} ({index.ntotal} vectors, dim={index.d})")
        return index
    except Exception as e:
        print(f"[faiss] khong doc duoc {path} ({e!r}) - model '{model}' se tra 503")
        return None


def preload(model: str) -> Optional[dict]:
    """Nạp sẵn index + id map của `model` vào cache (dùng lúc warm-up).

    Trả {vectors, dim, ids} khi index có thật, None khi thiếu file/faiss.
    """
    ids = _load_id_map(model)
    index = _load_index(model)
    if index is None:
        return None
    return {"vectors": int(index.ntotal), "dim": int(index.d), "ids": len(ids)}


@lru_cache
def _row_of(model: str) -> dict:
    """{frame_id: row} - reverse of the id map, for reconstructing by frame_id."""
    return {fid: i for i, fid in enumerate(_load_id_map(model))}


def reconstruct_vectors(frame_ids: List[str], model: str = "siglip") -> Optional[np.ndarray]:
    """(N, dim) vectors of the given frames straight from the flat index.

    Frames dropped from the index by dedup (step 03) are skipped. Returns None
    when the index is unavailable or none of the ids is indexed.
    """
    index = _load_index(model)
    if index is None:
        return None
    rows = _row_of(model)
    hit = [rows[fid] for fid in frame_ids if fid in rows]
    if not hit:
        return None
    return np.stack([index.reconstruct(r) for r in hit]).astype(np.float32)


def reconstruct_matrix(frame_ids: List[str], model: str = "siglip"):
    """(rows, matrix): `rows` là các frame CÓ trong index, `matrix[i]` là vector của rows[i].

    Khác `reconstruct_vectors`: hàm kia trả mảng đã lặng lẽ bỏ id không nằm
    trong index nhưng KHÔNG nói bỏ id nào, nên người gọi ghép vector với
    frame_ids theo thứ tự sẽ ghép lệch — mà id thiếu là chuyện thường: bước 03
    dedup giữ tập frame khác nhau cho từng model, còn ứng viên có thể do một
    thành viên ensemble khác lôi về. Trả kèm danh sách id thì không lệch được.

    ([], None) khi index không dùng được hoặc không id nào nằm trong index.
    """
    index = _load_index(model)
    if index is None:
        return [], None
    rows = _row_of(model)
    pairs = [(fid, rows[fid]) for fid in frame_ids if fid in rows]
    if not pairs:
        return [], None
    matrix = np.stack([index.reconstruct(r) for _, r in pairs]).astype(np.float32)
    return [fid for fid, _ in pairs], matrix


def search_index(query_vector: np.ndarray, top_k: int, model: str = "siglip") -> List[dict]:
    """Return [{id, score}, ...] sorted by score desc (cosine similarity).

    Ném IndexUnavailable khi model chưa có index hoặc chưa có id map.
    """
    base = settings.data_path / "indexes"
    index = _load_index(model)
    if index is None:
        raise IndexUnavailable(
            f"Model '{model}' chưa có index: thiếu {base / f'{model}.index'}. "
            f"Chạy data_processing bước 05 để build, hoặc đổi DEFAULT_MODEL/"
            f"ENSEMBLE_MODELS sang model đã có index."
        )

    ids = _load_id_map(model)
    if not ids:
        raise IndexUnavailable(
            f"Model '{model}' có index nhưng thiếu id map: cần "
            f"{base / f'id_map_{model}.json'} (hoặc {base / 'id_map.json'})."
        )

    import faiss

    q = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
    if q.shape[1] != index.d:
        raise ValueError(
            f"Query dim {q.shape[1]} != index dim {index.d} for model '{model}'. "
            f"The query encoder and the index must be the same backbone."
        )
    faiss.normalize_L2(q)  # cosine == inner product on unit vectors

    k = min(top_k, index.ntotal)
    scores, idxs = index.search(q, k)

    out: List[dict] = []
    for score, i in zip(scores[0], idxs[0]):
        if i < 0 or i >= len(ids):
            continue
        out.append({"id": ids[i], "score": float(score)})
    return out
