"""Caption search - semantic retrieval over Qwen2.5-VL keyframe captions.

Backing store: `data/captions/caption_data.json` = {frame_id: "English caption"}
(kaggle step 9). Semantic index: `data/indexes/caption_text.index` (step 07).

Captions are a retrieval channel that survives where visual embeddings fail -
unusual objects or abstract queries the backbone never learned (Vortex,
arXiv:2606.19682; the "rat trap" failure in MemoriEase). Scoring mirrors
ocr_service but with a smaller exact bonus: captions are GENERATED text, so a
verbatim substring match means much less than it does for OCR.

Missing files degrade gracefully: no captions -> [] (callers skip the channel).
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List

from config import get_settings
from services.fuzzy_service import fuzzy_scores, is_available as fuzzy_available
from services.text_embedding_service import encode_query
from services.text_faiss_service import load_sidecar, search_text_index

settings = get_settings()


@lru_cache
def _load_captions() -> Dict[str, str]:
    path = settings.data_path / "captions" / "caption_data.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def captions_available() -> bool:
    return bool(_load_captions())


def preload() -> int:
    """Nạp sẵn caption_data.json vào cache; trả số frame có caption (warm-up)."""
    return len(_load_captions())


def get_caption(frame_id: str) -> str:
    return _load_captions().get(frame_id, "")


def frame_has_caption_text(frame_id: str, keywords) -> bool:
    """Bộ lọc hậu kỳ theo caption — song song frame_has_ocr_text.

    Khác OCR một điểm có chủ đích: caption là câu VĂN XUÔI do Qwen2.5-VL sinh
    ("a man in a blue shirt riding a motorbike past a market"), nên so khớp cả
    cụm như OCR gần như không bao giờ trúng. Ở đây mọi TỪ trong một bộ từ khoá
    đều phải xuất hiện (AND), thứ tự tuỳ ý — gõ "man motorbike" là lọc được.

    `keywords` nhận một chuỗi, HOẶC danh sách các bộ thay thế nhau — khớp MỘT bộ
    là đủ (OR). Router dùng dạng danh sách khi bộ lọc tiếng Việt được LLM dịch:
    giữ cả bản gốc lẫn bản dịch thì bản dịch tồi cũng không xoá sạch kết quả,
    và từ khoá vốn đã là tiếng Anh vẫn chạy y như cũ.
    """
    variants = [keywords] if isinstance(keywords, str) else list(keywords or [])
    variants = [v for v in variants if v and v.strip()]
    if not variants:
        return True
    text = _load_captions().get(frame_id, "").lower()
    if not text:
        return False
    for variant in variants:
        tokens = [t for t in variant.lower().replace(",", " ").split() if t]
        if tokens and all(t in text for t in tokens):
            return True
    return False


def _exact_scores(q: str) -> Dict[str, float]:
    hits: Dict[str, float] = {}
    for frame_id, text in _load_captions().items():
        text_l = text.lower()
        if q in text_l:
            hits[frame_id] = text_l.count(q) / max(len(text_l.split()), 1)
    return hits


def _fallback_scores(q: str) -> Dict[str, float]:
    if settings.text_fallback_mode == "fuzzy" and fuzzy_available():
        return fuzzy_scores(q, _load_captions(), cutoff=settings.fuzzy_threshold)
    return _exact_scores(q)


def _semantic_scores(query: str, top_k: int) -> Dict[str, float]:
    vec = encode_query(query)
    if vec is None:
        return {}
    ids = load_sidecar("caption_text_ids")
    if not ids:
        return {}
    out: Dict[str, float] = {}
    for row, score in search_text_index(vec, top_k, name="caption_text"):
        if 0 <= row < len(ids):
            out[ids[row]] = score
    return out


def search_captions(query: str, top_k: int, rerank: bool = True) -> List[dict]:
    """Hybrid semantic+exact caption search; [{id, score}, ...] sorted desc."""
    q = query.lower().strip()
    if not q or not captions_available():
        return []

    sem = _semantic_scores(query, top_k=top_k * 4)
    if not sem:
        hits = [{"id": fid, "score": float(s)} for fid, s in _fallback_scores(q).items()]
    else:
        exact = _exact_scores(q)
        sw, eb = settings.caption_sem_weight, settings.caption_exact_bonus
        hits = [
            {
                "id": fid,
                "score": float(sw * sem.get(fid, 0.0) + eb * (1.0 if fid in exact else 0.0)),
            }
            for fid in set(sem) | set(exact)
        ]

    hits.sort(key=lambda x: x["score"], reverse=True)
    if rerank:
        hits = _rerank_hits(query, hits)
    return hits[:top_k]


def _rerank_hits(query: str, hits: List[dict]) -> List[dict]:
    """Cross-encoder re-rank of the top hits against their caption (head only)."""
    from services.rerank_service import blend, rerank_text

    n = min(len(hits), settings.rerank_candidates)
    if n < 2:
        return hits
    head, tail = hits[:n], hits[n:]

    captions = _load_captions()
    rr = rerank_text(query, [captions.get(h["id"], "") for h in head])
    if rr is None:
        return hits

    blended = blend([h["score"] for h in head], rr, settings.text_rerank_alpha)
    head = [{**h, "score": float(s)} for h, s in zip(head, blended)]
    head.sort(key=lambda x: x["score"], reverse=True)
    return head + tail
