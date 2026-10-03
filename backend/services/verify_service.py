"""Kiểm chứng đáp án trước khi nộp: đối chiếu (video, frame, answer) với bằng chứng.

Lõi dùng chung cho CLI (scripts/verify_submission.py) và endpoint /verify_answers
(giao diện gọi từ giỏ đáp án). Tái hiện quy trình điều tra đã bắt được lỗi thật
của bộ đề SOTUYEN2: nộp nhầm video nhìn giống (q24), dòng lạc chủ đề chiếm rank
đầu (q5), đáp án QA đếm theo caption sai (q12).

Hai tầng, đều offline:
  1. ANCHOR (không model): trích tên riêng/số từ đề, grep (bỏ dấu) vào toàn bộ
     ASR + OCR + caption của video được nộp. Anchor vắng mặt ở video nộp nhưng
     có ở video khác -> RED "nghi sai video" kèm gợi ý.
  2. E5: cosine giữa đề và caption của từng frame nộp; dòng tụt hẳn so với
     median -> YELLOW "lệch chủ đề, xem lại rank".

Cảnh báo trả về dạng {level: "red"|"yellow", msg} - RED nghĩa là "dừng lại nhìn
10 giây", không phải "chắc chắn sai": whisper nghe nhầm tên đường, đề viết tắt
còn ASR đọc đầy đủ... đều tạo RED oan (đo được 2/30 câu trên bộ SOTUYEN2).
"""
from __future__ import annotations

import bisect
import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from services.text_norm import fold

# --- Trích anchor từ đề bài ---------------------------------------------------------
# Anchor = bằng chứng "cứng" phải tìm thấy đâu đó trong video: cụm viết hoa giữa
# câu (tên riêng/địa danh) và số >= 3 chữ số. Số 1-2 chữ số bỏ qua ("4 cảnh",
# "3 vận động viên" là mô tả, không định danh video).


def _is_cap(tok: str) -> bool:
    # str.isupper trên ký tự đầu: chuẩn Unicode. KHÔNG dùng range regex [À-Ỹ] -
    # range đó bao cả chữ THƯỜNG có dấu nên "đang"/"được" lọt lưới.
    return bool(tok) and tok[0].isupper()


def extract_anchors(query: str) -> List[str]:
    anchors: List[str] = []
    # bỏ ngày tháng trước khi trích số: "trước ngày 01/7/2025" là ghi chú của đề,
    # không phải bằng chứng nằm trong video
    no_dates = re.sub(r"\b\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\b", " ", query)
    no_dates = re.sub(r"\b(?:năm|ngày|tháng)\s+\d{2,4}\b", " ", no_dates)
    for num in re.findall(r"\d{3,}", no_dates):
        anchors.append(num)
    for sent in re.split(r"(?<=[.!?:;\n])\s+", query):
        toks = sent.split()
        run: List[str] = []
        for i, tok in enumerate(toks):
            clean = tok.strip("“”\"'(),.?!:;")
            if clean and _is_cap(clean) and not (i == 0 and len(run) == 0):
                run.append(clean)
            else:
                if len(run) >= 1 and (len(run) >= 2 or len(run[0]) >= 4):
                    anchors.append(" ".join(run))
                run = []
        if len(run) >= 1 and (len(run) >= 2 or len(run[0]) >= 4):
            anchors.append(" ".join(run))
    seen = set()
    out = []
    for a in anchors:
        f = fold(a)
        if f not in seen:
            seen.add(f)
            out.append(a)
    return out


# --- Kho bằng chứng per-video (fold sẵn, cache process-wide) ------------------------

@lru_cache
def _asr_text() -> Dict[str, str]:
    from services.asr_service import _load_asr

    return {v: fold(" ".join(s["text"] for s in segs))
            for v, segs in _load_asr().items()}


@lru_cache
def _ocr_by_video() -> Dict[str, str]:
    from services.ocr_service import _load_ocr

    agg: Dict[str, List[str]] = {}
    for fid, text in _load_ocr().items():
        agg.setdefault(fid.rsplit("_", 1)[0], []).append(text)
    return {v: fold(" ".join(ts)) for v, ts in agg.items()}


@lru_cache
def _caption_frames(video: str) -> List[int]:
    from services.caption_service import _load_captions

    pre = video + "_"
    out = [int(fid.rsplit("_", 1)[1]) for fid in _load_captions()
           if fid.startswith(pre)]
    out.sort()
    return out


@lru_cache
def _caption_video_text(video: str) -> str:
    from services.caption_service import get_caption

    return fold(" ".join(
        get_caption(f"{video}_{fr:06d}") for fr in _caption_frames(video)))


def nearest_caption(video: str, frame: int) -> Tuple[Optional[int], str]:
    from services.caption_service import get_caption

    fl = _caption_frames(video)
    if not fl:
        return None, ""
    i = bisect.bisect_left(fl, frame)
    cand = fl[max(0, i - 1):i + 1]
    kf = min(cand, key=lambda c: abs(c - frame))
    return kf, get_caption(f"{video}_{kf:06d}")


def video_known(video: str) -> bool:
    return video in _asr_text() or video in _ocr_by_video()


def anchor_in_video(anchor: str, video: str) -> bool:
    af = fold(anchor)
    return (af in _asr_text().get(video, "")
            or af in _ocr_by_video().get(video, "")
            or af in _caption_video_text(video))


def find_anchor_elsewhere(anchor: str, exclude: str) -> List[str]:
    """Video khác chứa anchor (chỉ ASR+OCR - caption toàn corpus quá nặng)."""
    af = fold(anchor)
    hits = [v for v, t in _asr_text().items() if af in t and v != exclude]
    hits += [v for v, t in _ocr_by_video().items() if af in t and v != exclude
             and v not in hits]
    return hits[:5]


def e5_scores(query: str, captions: List[str]) -> Optional[List[float]]:
    from services.text_embedding_service import encode_passages, encode_query

    qv = encode_query(query)
    if qv is None or not captions:
        return None
    pv = encode_passages([c or " " for c in captions])
    if pv is None:
        return None
    return [float(x) for x in (pv @ qv)]


# --- Kiểm chứng một câu -------------------------------------------------------------
# row = {"video_name": str, "frames": [int, ...], "answer": str}

def verify_rows(query: str, rows: List[dict], task_type: str = "") -> List[dict]:
    """Trả [{level: 'red'|'yellow', msg}] - rỗng nghĩa là không thấy mâu thuẫn."""
    warns: List[dict] = []
    if not query.strip() or not rows:
        return warns
    anchors = extract_anchors(query)

    # tầng 1: anchor per video
    for video in {r["video_name"] for r in rows}:
        if not video_known(video):
            warns.append({"level": "red", "msg": f"video {video} không có trong index"})
            continue
        for a in anchors:
            if anchor_in_video(a, video):
                continue
            elsewhere = find_anchor_elsewhere(a, video)
            if elsewhere:
                warns.append({"level": "red", "msg":
                              f"'{a}' KHÔNG có trong {video} nhưng có ở "
                              f"{', '.join(elsewhere)} → nghi sai video"})
            else:
                warns.append({"level": "yellow", "msg":
                              f"'{a}' không thấy trong {video} (cũng không thấy ở "
                              f"video khác - có thể chỉ nhìn thấy, không nói/hiện chữ)"})

    # tầng 2: E5 cosine đề <-> caption từng frame
    caps, tags = [], []
    for r in rows:
        for fr in r.get("frames", []):
            kf, cap = nearest_caption(r["video_name"], int(fr))
            caps.append(cap)
            tags.append((r["video_name"], int(fr)))
    scores = e5_scores(query, caps)
    if scores and len(scores) >= 3:
        med = sorted(scores)[len(scores) // 2]
        for (video, fr), s in zip(tags, scores):
            if s < med - 0.04 and s < 0.80:
                warns.append({"level": "yellow", "msg":
                              f"{video},{fr} caption lệch chủ đề "
                              f"(cosine {s:.3f} / median {med:.3f}) → xem lại rank"})
    return warns
