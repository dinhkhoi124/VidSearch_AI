"""Temporal search: find ordered sequences of up to 3 events within the same video."""
import math
from typing import Dict, List

from fastapi import APIRouter, HTTPException

from config import get_settings
from models.schemas import TemporalSearchResponse
from services.embedding_service import encode_text
from services.ensemble_service import primary_model
from services.faiss_service import search_index
from services.metadata_service import frame_url, get_meta, video_url
from services.ocr_service import frame_has_ocr_text
from services.asr_service import video_has_asr_text

router = APIRouter()
settings = get_settings()


def _event_asr_scores(query: str) -> Dict[str, float]:
    """{frame_id: điểm ASR đã chuẩn hoá * temporal_asr_weight} cho một event.

    Semantic search trên index ASR (E5) rồi trải điểm segment xuống các keyframe
    trong khoảng thời gian của segment; mỗi frame giữ segment mạnh nhất. ASR
    thiếu index / lỗi -> {} (event về thuần visual, không bao giờ vỡ).
    """
    w = float(settings.temporal_asr_weight)
    if w <= 0 or not query.strip():
        return {}
    try:
        from services.asr_service import search_asr
        from services.metadata_service import frames_in_range

        videos = search_asr(query, "", False)
        segs = [
            (v["video_name"], seg)
            for v in videos[:15]
            for seg in v["segments"][:10]
        ]
        smax = max((float(s["score"]) for _, s in segs), default=1.0) or 1.0
        out: Dict[str, float] = {}
        for vname, seg in segs:
            boost = w * float(seg["score"]) / smax
            for fr in frames_in_range(vname, seg["start_ms"], seg["end_ms"]):
                if boost > out.get(fr["id"], 0.0):
                    out[fr["id"]] = boost
        return out
    except Exception as e:  # noqa: BLE001 - kênh phụ, hỏng thì bỏ qua
        print(f"[temporal] asr channel failed: {e!r}")
        return {}


def _event_caption_scores(query: str) -> Dict[str, float]:
    """{frame_id: điểm caption chuẩn hoá * temporal_caption_weight} cho một event.

    Caption là kênh frame-level sẵn - chỉ cần max-norm rồi nhân trọng số.
    Thiếu data caption / lỗi -> {} (không bao giờ vỡ).
    """
    w = float(settings.temporal_caption_weight)
    if w <= 0 or not query.strip():
        return {}
    try:
        from services.caption_service import captions_available, search_captions

        if not captions_available():
            return {}
        raw = search_captions(query, 200, rerank=False)
        smax = max((float(r["score"]) for r in raw), default=1.0) or 1.0
        return {r["id"]: w * float(r["score"]) / smax for r in raw}
    except Exception as e:  # noqa: BLE001 - kênh phụ, hỏng thì bỏ qua
        print(f"[temporal] caption channel failed: {e!r}")
        return {}


def _event_text_boosts(query: str) -> Dict[str, float]:
    """Gộp điểm mềm ASR + caption cho một event (cộng dồn theo frame)."""
    boosts = _event_asr_scores(query)
    for fid, s in _event_caption_scores(query).items():
        boosts[fid] = boosts.get(fid, 0.0) + s
    return boosts


def _event_candidates_by_video(
    query: str, ocr: str, asr: str, model: str, topk_per_event: int
) -> Dict[str, List[dict]]:
    """Ứng viên của một event, gom theo video: {video: [cand theo thời gian]}.

    Lấy pool SÂU (temporal_pool) thay vì top-k nông: event mô tả mịn ("bột chạm
    tô") thường nằm sâu dưới top vài trăm toàn cục, nhưng vẫn thuộc nhóm điểm
    cao nhất trong chính video đúng. Mỗi video giữ tối đa temporal_per_video
    frame điểm cao nhất để beam search không phình.
    """
    if not query.strip():
        return {}
    vec = encode_text(query, model=model)
    pool = max(int(settings.temporal_pool), topk_per_event * 3)
    raw = search_index(vec, top_k=pool, model=model)
    vmax = max((float(r["score"]) for r in raw), default=1.0) or 1.0

    # Điểm mềm ASR + caption per event: visual thuần không phân biệt được video
    # khớp hình nhưng sai bản chất (slide bài giảng trông như thắng cảnh) với
    # video có lời thuyết minh / caption khớp event. Điểm = visual/max +
    # Σ w*text/max - cộng hưởng chứ không loại cứng như filter ocr/asr phía
    # dưới. Frame chỉ trúng kênh text (visual trượt khỏi pool) cũng vào ứng viên.
    asr_boost = _event_text_boosts(query)

    per_video: Dict[str, List[dict]] = {}
    seen_ids = set()
    for r in raw:
        if ocr and not frame_has_ocr_text(r["id"], ocr):
            continue
        meta = get_meta(r["id"])
        if asr and not video_has_asr_text(meta["video_name"], asr):
            continue
        seen_ids.add(r["id"])
        per_video.setdefault(meta["video_name"], []).append(
            {
                "id": r["id"],
                "score": float(r["score"]) / vmax + asr_boost.get(r["id"], 0.0),
                "video_name": meta["video_name"],
                "frame_name": meta["frame_name"],
                "timestamp_ms": meta["timestamp_ms"],
                "fps": meta["fps"],
            }
        )
    for fid, boost in asr_boost.items():
        if fid in seen_ids:
            continue
        if ocr and not frame_has_ocr_text(fid, ocr):
            continue
        meta = get_meta(fid)
        if asr and not video_has_asr_text(meta["video_name"], asr):
            continue
        per_video.setdefault(meta["video_name"], []).append(
            {
                "id": fid,
                "score": boost,
                "video_name": meta["video_name"],
                "frame_name": meta["frame_name"],
                "timestamp_ms": meta["timestamp_ms"],
                "fps": meta["fps"],
            }
        )
    cap = max(int(settings.temporal_per_video), 1)
    for lst in per_video.values():
        lst.sort(key=lambda x: x["score"], reverse=True)
        del lst[cap:]
        lst.sort(key=lambda x: x["timestamp_ms"])
    return per_video


def _best_sequence(event_groups: List[List[dict]]):
    """Beam search with exponential temporal decay (Ngo et al., arXiv:2512.12935).

    Sequence score = Σ sᵢ·e^(−α·Δtᵢ) - events close in time keep full weight,
    large gaps (Δt ≫ 1/α seconds) are softly penalised instead of the previous
    greedy sum that treated a 10s gap and a 20-minute gap the same. The beam
    keeps the top-B partial sequences per step, so a slightly weaker event-0
    pick can still win via a tighter overall chain.

    Returns (total_score, [picked_event0, picked_event1, ...]) or (None, []).
    """
    if not event_groups or not event_groups[0]:
        return None, []

    alpha = settings.temporal_decay_alpha
    beam_width = settings.temporal_beam_width

    beams = [(float(c["score"]), [c]) for c in event_groups[0]]
    beams.sort(key=lambda b: b[0], reverse=True)
    beams = beams[:beam_width]

    for eg in event_groups[1:]:
        candidates = sorted(eg, key=lambda x: x["timestamp_ms"])
        nxt_beams = []
        for score, picks in beams:
            last_ts = picks[-1]["timestamp_ms"]
            for x in candidates:
                if x["timestamp_ms"] <= last_ts:
                    continue
                dt_s = (x["timestamp_ms"] - last_ts) / 1000.0
                nxt_beams.append(
                    (score + float(x["score"]) * math.exp(-alpha * dt_s), picks + [x])
                )
        if not nxt_beams:
            return None, []
        nxt_beams.sort(key=lambda b: b[0], reverse=True)
        beams = nxt_beams[:beam_width]

    return beams[0]


@router.post("/search_temporal", response_model=TemporalSearchResponse)
async def search_temporal(
    q1: str = "",
    ocr1: str = "",
    asr1: str = "",
    q2: str = "",
    ocr2: str = "",
    asr2: str = "",
    q3: str = "",
    ocr3: str = "",
    asr3: str = "",
    q4: str = "",
    ocr4: str = "",
    asr4: str = "",
    model: str = settings.default_model,
    topk_per_event: int = 25,
):
    # Temporal search chấm điểm trên MỘT index (encode_text không hiểu key
    # "ensemble" hay tổ hợp "siglip512+metaclip" -> sẽ rơi vào mock vector im
    # lặng). Quy tổ hợp về member trọng số cao nhất làm đại diện.
    model = primary_model(model)

    events = [(q1, ocr1, asr1), (q2, ocr2, asr2), (q3, ocr3, asr3), (q4, ocr4, asr4)]
    active = [(i, q, o, a) for i, (q, o, a) in enumerate(events) if q.strip()]
    if not active:
        raise HTTPException(
            status_code=400, detail="At least one event query (q1..q4) is required"
        )

    # Per-event candidates, grouped by video (pool sâu - xem _event_candidates_by_video)
    per_event_by_video: List[Dict[str, List[dict]]] = []
    event_indices: List[int] = []
    for ev_idx, q, o, a in active:
        per_event_by_video.append(
            _event_candidates_by_video(q, o, a, model, topk_per_event)
        )
        event_indices.append(ev_idx)

    # Video hợp lệ: có ứng viên cho đủ mọi event là lý tưởng; từ 3 event trở
    # lên chấp nhận thiếu đúng 1 (giao tuyệt đối hay rỗng khi event mô tả mịn).
    # Chuỗi phủ nhiều event hơn luôn xếp trên chuỗi thiếu, bất kể điểm.
    coverage: Dict[str, int] = {}
    for g in per_event_by_video:
        for vname in g:
            coverage[vname] = coverage.get(vname, 0) + 1
    n_active = len(active)
    # Chấp nhận thiếu 1 event với MỌI n >= 2 (trước đây 2 event bắt đủ 2/2):
    # sort cuối ưu tiên coverage trước điểm, nên video phủ đủ vẫn luôn đứng
    # trên - video 1/2 event chỉ lấp phần đuôi. Bằng chứng cần nới: p2-7, video
    # đúng là nơi DUY NHẤT toàn corpus có caption "snowman" (event 1 khớp hạng
    # 25/200) nhưng bị loại thẳng vì event 2 không trúng nó.
    floor = max(1, n_active - 1)

    out_videos = []
    for vname, cov in coverage.items():
        if cov < floor:
            continue
        groups, idxs = [], []
        for g, ev_idx in zip(per_event_by_video, event_indices):
            if vname in g:
                groups.append(g[vname])
                idxs.append(ev_idx)
        total, picks = _best_sequence(groups)
        if total is None:
            continue
        events_out = []
        for ev_idx, p in zip(idxs, picks):
            events_out.append(
                {
                    "id": p["id"],
                    "event_index": ev_idx,
                    "frame_name": p["frame_name"],
                    "frame_url": frame_url(p["video_name"], p["frame_name"]),
                    "video_url": video_url(p["video_name"]),
                    "timestamp_ms": p["timestamp_ms"],
                    "fps": p["fps"],
                    "score": p["score"],
                }
            )
        out_videos.append(
            {
                "video_name": vname,
                "best_sequence": {"total_score": float(total), "events": events_out},
            }
        )

    out_videos.sort(
        key=lambda v: (len(v["best_sequence"]["events"]),
                       v["best_sequence"]["total_score"]),
        reverse=True,
    )
    return {"videos": out_videos}
