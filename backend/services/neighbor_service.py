"""Neighbor score aggregation - training-free rerank for visual retrieval.

A frame whose temporal neighbours also score high against the query usually
sits inside the true target scene, while an isolated high scorer is more often
retrieval noise (Tran et al., arXiv:2504.08384, Alg. 2). Each candidate gets a
bonus from other candidates of the SAME video within ±neighbor_window_ms,
decayed linearly with the time gap and AVERAGED over the neighbours:

    final_i = s_i + w * mean_j( s_j * (1 − |Δt_ij| / window) )      (j ≠ i)

Mean, not sum: our keyframes are dense (nhiều keyframe/cảnh khi index chưa
dedup), một cụm 15-20 ứng viên mà cộng dồn sẽ tạo bonus lớn gấp nhiều lần điểm
thật - frame KHÔNG liên quan nằm giữa cảnh hot bị bơm thẳng lên hạng 1 (đã xảy
ra thật: khúc gỗ giữa phóng sự hổ, tự xếp hạng 304, cộng dồn đẩy lên hạng 1).
Với mean, bonus bị chặn ở w * max(s_j) - chỉ là cú hích, thứ hạng vẫn do điểm
riêng của frame quyết định.

Only the already-retrieved candidate list is used - no model call, no index
lookup - so this runs in O(k²) per video over small per-video groups and is
effectively free. Disable with settings.neighbor_weight = 0.
"""
from __future__ import annotations

from typing import Dict, List

from config import get_settings

settings = get_settings()


def aggregate_neighbor_scores(raw: List[dict]) -> List[dict]:
    """Re-score [{id, score}, ...] with the neighbour bonus and re-sort."""
    weight = settings.neighbor_weight
    window = settings.neighbor_window_ms
    if weight <= 0 or window <= 0 or len(raw) < 2:
        return raw

    from services.metadata_service import get_meta  # local import: avoid cycle

    by_video: Dict[str, List[int]] = {}
    ts: List[int] = []
    for i, item in enumerate(raw):
        meta = get_meta(item["id"])
        ts.append(meta["timestamp_ms"])
        by_video.setdefault(meta["video_name"], []).append(i)

    out = [dict(item) for item in raw]
    for indices in by_video.values():
        if len(indices) < 2:
            continue
        indices.sort(key=lambda i: ts[i])
        for a, i in enumerate(indices):
            total, cnt = 0.0, 0
            # walk outwards both ways; candidates are time-sorted so we stop early
            for b in range(a - 1, -1, -1):
                dt = ts[i] - ts[indices[b]]
                if dt > window:
                    break
                total += float(raw[indices[b]]["score"]) * (1.0 - dt / window)
                cnt += 1
            for b in range(a + 1, len(indices)):
                dt = ts[indices[b]] - ts[i]
                if dt > window:
                    break
                total += float(raw[indices[b]]["score"]) * (1.0 - dt / window)
                cnt += 1
            if cnt:
                out[i]["score"] = float(raw[i]["score"]) + weight * total / cnt

    out.sort(key=lambda x: x["score"], reverse=True)
    return out
