"""ASR (speech transcript) search - hybrid semantic + exact.

Backing store: `data/asr/asr_data.json` =
{
    "video_name": [
        {"start_ms": 0, "end_ms": 5000, "text": "..."},
        ...
    ]
}

Two signals are combined per segment:
  * semantic - query & segment text encoded by a sentence model (E5); nearest
    neighbours come from `data/indexes/asr_text.index` (built offline by
    data_processing step 07, row->segment via asr_text_meta.json).
  * exact    - case-insensitive substring match over a 2-segment window (a phrase
    can straddle an ASR sentence boundary), the original high-precision signal.

    score = sem_weight * cosine + exact_bonus * (1 if substring present else 0)

If the sentence model or the index is unavailable the semantic pass is skipped and
this degrades gracefully to pure exact substring search (the original behaviour).
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List, Tuple

from config import get_settings
from services.fuzzy_service import fuzzy_scores, is_available as fuzzy_available
from services.text_embedding_service import encode_query
from services.text_faiss_service import load_sidecar, search_text_index

settings = get_settings()

# How many semantic neighbours to pull before merging with exact matches.
_SEM_TOP_K = 200


@lru_cache
def _load_asr() -> Dict[str, List[dict]]:
    path = settings.data_path / "asr" / "asr_data.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def preload() -> int:
    """Nạp sẵn asr_data.json vào cache; trả số video có ASR (warm-up)."""
    return len(_load_asr())


def _window_text(segs: List[dict], i: int) -> str:
    """Lowercased text of segment `i` joined with the next one.

    ASR cuts roughly per sentence, so a queried phrase can straddle a segment
    boundary. Matching each segment glued to its successor catches those without
    re-running ASR; the match is still attributed to segment `i` for timing.
    """
    text = segs[i].get("text", "")
    if i + 1 < len(segs):
        text = f"{text} {segs[i + 1].get('text', '')}"
    return text.lower()


def asr_context(video_name: str, ms: int, before_ms: int = 20000, after_ms: int = 40000) -> str:
    """Ghép text các segment ASR quanh mốc thời gian của một frame.

    Bằng chứng nói thường nằm CẠNH shot chứ không trùng đúng shot - vd người
    dẫn giới thiệu "đã viết hai câu thơ đó là" rồi mới đọc thơ ở 5-10s sau;
    scene của frame (vài giây) không chứa câu thơ. Cửa sổ lệch về sau (nghe
    tiếp) rộng hơn về trước.
    """
    segs = _load_asr().get(video_name, [])
    lo, hi = ms - before_ms, ms + after_ms
    return " ".join(
        s.get("text", "") for s in segs
        if s.get("end_ms", 0) >= lo and s.get("start_ms", 0) <= hi
    ).strip()


def video_has_asr_text(video_name: str, keyword: str) -> bool:
    if not keyword:
        return True
    segs = _load_asr().get(video_name, [])
    k = keyword.lower()
    return any(k in _window_text(segs, i) for i in range(len(segs)))


def _exact_scores(q: str, af: str) -> Dict[Tuple[str, int], float]:
    """(video, seg_idx) -> ĐỘ CHẮC của khớp nguyên văn, tôn trọng bộ lọc af.

    Cụm nhiều từ khớp cả khi các từ RỜI NHAU trong cửa sổ (0.8 thay vì 1.0):
    người dẫn hiếm khi đọc liền một cụm do người dùng gõ ("tay đua Estonia"
    thực tế là "tay đua ... người Estonia"), mà cửa sổ 2 segment vẫn chứa đủ từ.
    Xem ocr_service._exact_scores - trước đây trả tần suất rồi bị vứt đi.
    """
    tokens = [t for t in q.split() if t]
    hits: Dict[Tuple[str, int], float] = {}
    for video, segs in _load_asr().items():
        for i in range(len(segs)):
            window = _window_text(segs, i)
            if af and af not in window:
                continue
            if q in window:
                hits[(video, i)] = 1.0
            elif len(tokens) > 1 and all(t in window for t in tokens):
                hits[(video, i)] = 0.8
    return hits


def _total_windows() -> int:
    """Tổng số cửa sổ ASR trong corpus - mẫu số cho độ hiếm của một cụm."""
    return sum(len(segs) for segs in _load_asr().values())


def _windows(af: str) -> Dict[Tuple[str, int], str]:
    """(video, seg_idx) -> lowercased 2-segment window, respecting the af filter."""
    out: Dict[Tuple[str, int], str] = {}
    for video, segs in _load_asr().items():
        for i in range(len(segs)):
            window = _window_text(segs, i)
            if af and af not in window:
                continue
            out[(video, i)] = window
    return out


def _fallback_scores(q: str, af: str) -> Dict[Tuple[str, int], float]:
    """Used when semantic search is unavailable: fuzzy (if configured & installed) else exact."""
    if settings.text_fallback_mode == "fuzzy" and fuzzy_available():
        # Cap candidates (ASR has no top_k at the router) so the response stays sane.
        return fuzzy_scores(q, _windows(af), cutoff=settings.fuzzy_threshold, limit=_SEM_TOP_K)
    return _exact_scores(q, af)


def _semantic_scores(query: str, af: str) -> Dict[Tuple[str, int], float]:
    """(video, seg_idx) -> cosine similarity from the ASR text index, or {}."""
    vec = encode_query(query)
    if vec is None:
        return {}
    meta = load_sidecar("asr_text_meta")
    if not meta:
        return {}
    data = _load_asr()
    out: Dict[Tuple[str, int], float] = {}
    for row, score in search_text_index(vec, _SEM_TOP_K, name="asr_text"):
        if not (0 <= row < len(meta)):
            continue
        m = meta[row]
        video, i = m["video_name"], m["seg_idx"]
        segs = data.get(video, [])
        if not (0 <= i < len(segs)):
            continue
        if af and af not in _window_text(segs, i):
            continue
        out[(video, i)] = score
    return out


def _rerank_scored(
    query: str, scored: Dict[Tuple[str, int], float], data: Dict[str, List[dict]]
) -> Dict[Tuple[str, int], float]:
    """Cross-encoder re-rank of the top segments against their 2-segment window."""
    from services.rerank_service import blend, rerank_text

    keys = sorted(scored, key=scored.get, reverse=True)[: settings.rerank_candidates]
    if len(keys) < 2:
        return scored

    rr = rerank_text(query, [_window_text(data[v], i) for v, i in keys])
    if rr is None:
        return scored

    blended = blend([scored[k] for k in keys], rr, settings.text_rerank_alpha)
    return {**scored, **{k: float(s) for k, s in zip(keys, blended)}}


def locate_in_video(video_name: str, query: str, top: int = 3) -> List[dict]:
    """Mốc ASR khớp `query` nhất TRONG MỘT video: [{start_ms, end_ms, text, score}].

    Dành cho agent định vị thời điểm trong video đã biết là đúng nhưng không có
    keyframe ở đoạn đó (bài giảng slide tĩnh bị dedup). Điểm = max(
      semantic theo search_asr lọc về video này,
      tỉ lệ token của query có mặt trong cửa sổ segment i + i+1 (bỏ dấu)).
    Không có ASR cho video -> [].
    """
    from services.text_norm import tokens

    segs = _load_asr().get(video_name, [])
    if not segs or not query.strip():
        return []
    qtok = set(tokens(query))
    scores: Dict[int, float] = {}
    if qtok:
        for i in range(len(segs)):
            wt = set(tokens(_window_text(segs, i)))
            scores[i] = len(qtok & wt) / len(qtok)
    try:
        for v in search_asr(query, "", rerank=False):
            if v["video_name"] != video_name:
                continue
            for seg in v["segments"]:
                idx = next((i for i, s in enumerate(segs)
                            if s.get("start_ms") == seg.get("start_ms")), None)
                if idx is not None:
                    scores[idx] = max(scores.get(idx, 0.0), float(seg["score"]))
    except Exception:  # noqa: BLE001 - index text thiếu thì còn nhánh token
        pass
    best = sorted((i for i in scores if scores[i] > 0), key=lambda i: -scores[i])[:top]
    return [{**segs[i], "score": round(scores[i], 3)} for i in best]


def search_asr(query: str, asr_filter: str = "", rerank: bool = True) -> List[dict]:
    """Return list of {video_name, segments:[{start_ms, end_ms, text, score}]}."""
    q = query.lower().strip()
    if not q:
        return []

    af = asr_filter.lower()
    data = _load_asr()

    from services.ocr_service import rescale_semantic

    sem = rescale_semantic(_semantic_scores(query, af))

    if not sem:  # model/index unavailable -> fuzzy or exact fallback
        scored = {key: float(s) for key, s in _fallback_scores(q, af).items()}
    else:
        exact = _exact_scores(q, af)
        sw, eb = settings.asr_sem_weight, settings.asr_exact_bonus
        # Thưởng khớp nguyên văn = bonus × độ hiếm của cụm × độ chắc của kiểu khớp.
        from services.ocr_service import _specificity

        spec = _specificity(len(exact), _total_windows())
        scored = {
            key: float(sw * sem.get(key, 0.0) + eb * spec * exact.get(key, 0.0))
            for key in set(sem) | set(exact)
        }

    if rerank and scored:
        scored = _rerank_scored(query, scored, data)

    by_video: Dict[str, List[dict]] = {}
    for (video, i), score in scored.items():
        by_video.setdefault(video, []).append({**data[video][i], "score": score})

    out: List[dict] = []
    for video, matched in by_video.items():
        matched.sort(key=lambda s: s["start_ms"])
        out.append({"video_name": video, "segments": matched})
    # Surface the strongest videos first (original returned dict insertion order).
    out.sort(key=lambda v: max(s["score"] for s in v["segments"]), reverse=True)
    return out
