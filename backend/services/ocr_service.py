"""OCR text search - hybrid semantic + exact.

Backing store: `data/ocr/ocr_data.json` = {frame_id: "ocr text"}

Two signals are combined:
  * semantic - query & OCR text encoded by a sentence model (E5) into a shared
    space; nearest neighbours come from `data/indexes/ocr_text.index` (built offline
    by data_processing step 07, row->frame_id via ocr_text_ids.json).
  * exact    - case-insensitive substring match, the original high-precision signal.

    score = sem_weight * cosine + exact_bonus * (1 if substring present else 0)

If the sentence model or the index is unavailable the semantic pass is skipped and
this degrades gracefully to pure exact substring search (the original behaviour).
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List

from config import get_settings
from services.fuzzy_service import fuzzy_scores, is_available as fuzzy_available
from services.text_embedding_service import encode_query
from services.text_norm import fold
from services.text_faiss_service import load_sidecar, search_text_index

settings = get_settings()


@lru_cache
def _load_ocr() -> Dict[str, str]:
    path = settings.data_path / "ocr" / "ocr_data.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def preload() -> int:
    """Nạp sẵn ocr_data.json vào cache; trả số frame có OCR (warm-up)."""
    return len(_load_ocr())


def frame_has_ocr_text(frame_id: str, keyword: str) -> bool:
    if not keyword:
        return True
    text = _load_ocr().get(frame_id, "")
    return fold(keyword) in fold(text)


def _exact_scores(q: str) -> Dict[str, float]:
    """frame_id -> ĐỘ CHẮC của khớp nguyên văn, trong (0, 1].

    So khớp trên bản fold (bỏ dấu): OCR broadcast mất/sai dấu liên tục, nên
    "Tam Kỳ" phải khớp được text OCR "Tam Ky".

    Cụm nhiều từ còn phải khớp được cả khi các từ KHÔNG liền nhau: chữ chạy trên
    hình hay bị chèn dấu câu và tên khác. Đo trên corpus này, "Tam Kỳ Quảng Nam"
    trượt sạch vì OCR thật là "Da Nang - Tam Ky (Quang Nam)" - dấu ngoặc cắt đôi
    chuỗi liền. Nên khớp liền = 1.0, còn đủ-mọi-từ-nhưng-rời = 0.8: vẫn là bằng
    chứng mạnh, chỉ kém chắc hơn một chút (quét 0.5/0.8/1.0 × bonus 1.0/1.5/2.0
    trên 5 cụm tên riêng: 0.8 là giá trị duy nhất đạt 5/5 ở cả hai mức bonus).

    Trước đây hàm trả TẦN SUẤT nhưng search_ocr vứt đi và chỉ hỏi "có khớp
    không" -> mọi frame khớp cùng một điểm, top-20 hoà nhau tuyệt đối và thứ tự
    hoá ra ngẫu nhiên theo thứ tự dict.
    """
    qf = fold(q)
    tokens = [t for t in qf.split() if t]
    hits: Dict[str, float] = {}
    for frame_id, text in _load_ocr().items():
        text_f = fold(text)
        if qf in text_f:
            hits[frame_id] = 1.0
        elif len(tokens) > 1 and all(t in text_f for t in tokens):
            hits[frame_id] = 0.8
    return hits


def _specificity(n_matched: int, n_total: int) -> float:
    """Cụm chữ khớp CÀNG ÍT frame thì càng đáng tin - IDF chuẩn hoá về (0, 1].

    "Lý Thường Kiệt" khớp vài frame = ghim đúng một video; "NGUYÊN LIỆU" khớp
    hàng trăm frame ở mọi video dạy nấu ăn = gần như không mang thông tin. Không
    có hệ số này thì cả hai cùng được điểm tối đa và cụm vô nghĩa tràn ngập
    fusion đa kênh.
    """
    import math

    if n_matched <= 0 or n_total <= 0:
        return 0.0
    return min(1.0, math.log(1 + n_total / n_matched) / math.log(1 + n_total))


def rescale_semantic(sem: Dict) -> Dict:
    """Kéo giãn điểm E5 về [0, 1] trong phạm vi ứng viên trả về.

    Cosine của E5 có SÀN rất cao và gần như không đổi: đo trên corpus này, query
    vô nghĩa ("xyzzy qwerty không tồn tại") cho max 0.827, còn query thật
    ("Tam Kỳ Quảng Nam") cho max 0.830 - toàn bộ tín hiệu nằm trong dải 0.03,
    còn 0.80 là hằng số cộng vào mọi frame.

    Cộng thẳng điểm thô với thưởng khớp nguyên văn vì thế bị lệch nặng: frame
    KHÔNG nằm trong danh sách ứng viên ngữ nghĩa mặc định nhận 0.0, nên nó phải
    hơn 0.80 chỉ bằng phần thưởng - trong khi mọi frame nhiễu đã có sẵn 0.80 cho
    không. Giãn về [0, 1] đưa hai nguồn điểm về cùng một thang.
    """
    if not sem:
        return {}
    lo = min(sem.values())
    span = max(sem.values()) - lo
    if span <= 1e-9:
        return {k: 0.0 for k in sem}
    return {k: (v - lo) / span for k, v in sem.items()}


def _fallback_scores(q: str) -> Dict[str, float]:
    """Used when semantic search is unavailable: fuzzy (if configured & installed) else exact."""
    if settings.text_fallback_mode == "fuzzy" and fuzzy_available():
        return fuzzy_scores(q, _load_ocr(), cutoff=settings.fuzzy_threshold)
    return _exact_scores(q)


def _semantic_scores(query: str, top_k: int) -> Dict[str, float]:
    """frame_id -> cosine similarity from the OCR text index, or {} if unavailable."""
    vec = encode_query(query)
    if vec is None:
        return {}
    ids = load_sidecar("ocr_text_ids")
    if not ids:
        return {}
    out: Dict[str, float] = {}
    for row, score in search_text_index(vec, top_k, name="ocr_text"):
        if 0 <= row < len(ids):
            out[ids[row]] = score
    return out


def _rerank_hits(query: str, hits: List[dict]) -> List[dict]:
    """Cross-encoder re-rank of the top hits against their OCR text (head only)."""
    from services.rerank_service import blend, rerank_text

    n = min(len(hits), settings.rerank_candidates)
    if n < 2:
        return hits
    head, tail = hits[:n], hits[n:]

    ocr = _load_ocr()
    rr = rerank_text(query, [ocr.get(h["id"], "") for h in head])
    if rr is None:
        return hits

    blended = blend([h["score"] for h in head], rr, settings.text_rerank_alpha)
    head = [{**h, "score": float(s)} for h, s in zip(head, blended)]
    head.sort(key=lambda x: x["score"], reverse=True)
    return head + tail


def search_ocr(query: str, top_k: int, rerank: bool = True) -> List[dict]:
    """Hybrid semantic+exact search; returns [{id, score}, ...] sorted by score desc."""
    q = query.lower().strip()
    if not q:
        return []

    # Over-fetch semantic candidates so exact-only frames can still be re-ranked in.
    sem = rescale_semantic(_semantic_scores(query, top_k=top_k * 4))

    if not sem:  # model/index unavailable -> fuzzy or exact fallback
        hits = [{"id": fid, "score": float(s)} for fid, s in _fallback_scores(q).items()]
    else:
        exact = _exact_scores(q)
        sw, eb = settings.ocr_sem_weight, settings.ocr_exact_bonus
        # Thưởng khớp nguyên văn = bonus × độ hiếm của cụm × độ chắc của kiểu khớp.
        spec = _specificity(len(exact), len(_load_ocr()))
        hits = [
            {
                "id": fid,
                "score": float(sw * sem.get(fid, 0.0) + eb * spec * exact.get(fid, 0.0)),
            }
            for fid in set(sem) | set(exact)
        ]

    hits.sort(key=lambda x: x["score"], reverse=True)
    if rerank:
        hits = _rerank_hits(query, hits)
    return hits[:top_k]
