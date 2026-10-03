"""Frame metadata loader + URL builder + HTTP frame fetcher.

Loads `data/metadata/frames_meta.json` shape:
{
    "<frame_id>": {
        "video_name": "video_L01_V001",
        "frame_name": "000125.webp",
        "timestamp_ms": 5000,
        "fps": 25.0
    },
    ...
}

If the file is missing, falls back to inferring metadata from the frame_id
(`<video_name>_<frame_number>`) with default fps=25.

Media lives on the FE - BE no longer reads images from disk. URL helpers point
at `MEDIA_BASE_URL`; `frame_bytes()` fetches via HTTP (LRU cached) for the
reranker / agent which need the actual pixels.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from config import get_settings

settings = get_settings()

# Per-process LRU of decoded image bytes. Visual rerank reads ~100 frames/request
# so we cap aggressively; oldest frames drop on overflow.
_FRAME_CACHE_MAX = 256
_frame_cache: Dict[str, bytes] = {}
_frame_lock = threading.Lock()

# Số kết nối song song khi kéo keyframe từ FE. 16 đủ che RTT của ngrok mà không
# làm ngợp Vite dev server (node đơn luồng) ở đầu bên kia.
_FETCH_WORKERS = 16
_http: Optional[httpx.Client] = None

# URL đã kêu rồi - chỉ log một lần mỗi URL. Chặn trần để một buổi chạy dài không
# phình bộ nhớ vì toàn URL hỏng khác nhau.
_WARNED_MAX = 64
_warned_urls: set[str] = set()


def _warn_fetch_failed(url: str, reason: object) -> None:
    """Cảnh báo KHÔNG DẤU và không bao giờ ném lỗi.

    Console Windows mặc định là cp1252: print() chuỗi có dấu tiếng Việt ném
    UnicodeEncodeError. Ở đây lỗi đó sẽ nổ GIỮA một request search - tức dòng log
    chẩn đoán lại làm sập đúng thứ nó đang chẩn đoán. Nên: ASCII thuần + bọc try.
    """
    with _frame_lock:
        if url in _warned_urls:
            return
        if len(_warned_urls) < _WARNED_MAX:
            _warned_urls.add(url)
    try:
        print(f"[media] KHONG lay duoc keyframe: {url} ({reason})")
        print("[media]   -> rerank visual va /agent/qa se chay MU. Kiem tra "
              "MEDIA_BASE_URL va thu muc frontend/public/media/frames/Keyframes/.")
    except Exception:  # noqa: BLE001 - log hỏng thì thôi, không được chặn search
        pass


@lru_cache
def _load_frames_meta() -> Dict[str, dict]:
    path = settings.data_path / "metadata" / "frames_meta.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def _load_keyframe_index() -> Dict[str, List[str]]:
    """Map video_name -> danh sách frame_name đã sort. Đứng thay cho việc
    đọc trực tiếp thư mục media trên disk (giờ media nằm ở FE)."""
    path = settings.data_path / "metadata" / "keyframe_index.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def frames_in_video(video_name: str) -> List[str]:
    """Danh sách frame_name của 1 video, đã sort theo số (zero-padded)."""
    return _load_keyframe_index().get(video_name, [])


def preload() -> dict:
    """Nạp sẵn frames_meta + keyframe_index vào cache (dùng lúc warm-up)."""
    return {
        "frames": len(_load_frames_meta()),
        "videos": len(_load_keyframe_index()),
    }


def _infer_meta(frame_id: str) -> dict:
    # frame_id convention: "<video_name>_<frame_number>", e.g. "video_L01_V001_000125"
    parts = frame_id.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        video_name, frame_num = parts
        fps = 25.0
        return {
            "video_name": video_name,
            "frame_name": f"{frame_num}.webp",
            "timestamp_ms": int(int(frame_num) / fps * 1000),
            "fps": fps,
        }
    return {
        "video_name": frame_id,
        "frame_name": f"{frame_id}.webp",
        "timestamp_ms": 0,
        "fps": 25.0,
    }


def get_meta(frame_id: str) -> dict:
    meta = _load_frames_meta().get(frame_id)
    return meta if meta else _infer_meta(frame_id)


def frame_rel_path(video_name: str, frame_name: str) -> str:
    """Đường dẫn tương đối của keyframe - CÔNG THỨC DUY NHẤT.

    URL cho trình duyệt và path trên đĩa của BE đều dựng từ đây. Tách ra thành
    một hàm để hai đường không thể trôi khỏi nhau: lệch nhau thì bên đĩa lặng lẽ
    không thấy file, rerank chạy mù, mà URL trên màn hình vẫn đúng nên không ai
    nghi ngờ gì.
    """
    batch = video_name.split("_")[0]
    return f"media/frames/Keyframes/{batch}/{video_name}/{frame_name}"


def frame_url(video_name: str, frame_name: str) -> str:
    """Public URL của keyframe - trỏ về MEDIA_BASE_URL (FE serve static).

    LUÔN là URL, kể cả khi MEDIA_DIR được đặt: trình duyệt của thí sinh không
    đọc được đĩa của máy chạy backend.
    """
    return f"{settings.media_base}/{frame_rel_path(video_name, frame_name)}"


def frame_bytes_url(video_name: str, frame_name: str) -> str:
    """URL tuyệt đối tới keyframe để BE fetch bytes (rerank / agent vision)."""
    return frame_url(video_name, frame_name)


def local_frame_path(video_name: str, frame_name: str) -> Optional[Path]:
    """Path trên đĩa của BE, hoặc None khi chưa cấu hình MEDIA_DIR."""
    if not settings.media_dir:
        return None
    return settings.media_path / frame_rel_path(video_name, frame_name)


def _client() -> httpx.Client:
    """Client dùng CHUNG, giữ kết nối sống giữa các lần fetch.

    Trước đây mỗi keyframe mở một httpx.Client riêng: bắt tay TCP + TLS lại từ
    đầu cho từng ảnh. Chạy localhost thì không thấy gì, nhưng khi backend ở
    Colab còn media ở máy nhà qua ngrok thì mỗi ảnh tốn vài vòng RTT chỉ để
    bắt tay - và rerank đọc 100 ảnh một lượt.
    """
    global _http
    if _http is None:
        with _frame_lock:
            if _http is None:
                # 30s chứ không phải 10s: khi FE ở sau tunnel (ngrok/cloudflared)
                # lúc nguội, một lô rerank 100 ảnh dễ chạm trần rồi rơi về None.
                # ngrok-skip-browser-warning: xem TUNNEL_HEADERS bên
                # frontend/src/api/apiClient.js - giữ cùng giá trị "true".
                _http = httpx.Client(
                    timeout=30.0,
                    limits=httpx.Limits(max_connections=_FETCH_WORKERS,
                                        max_keepalive_connections=_FETCH_WORKERS),
                    headers={"ngrok-skip-browser-warning": "true"},
                )
    return _http


def _cache_frame(key: str, data: bytes) -> None:
    with _frame_lock:
        if len(_frame_cache) >= _FRAME_CACHE_MAX:
            # evict FIFO đơn giản (LRU không cần chính xác - chỉ chặn phình)
            _frame_cache.pop(next(iter(_frame_cache)))
        _frame_cache[key] = data


def frame_bytes(video_name: str, frame_name: str) -> Optional[bytes]:
    """Lấy bytes keyframe (LRU cache). Trả None nếu lỗi.

    Hai đường: MEDIA_DIR đặt rồi thì đọc thẳng đĩa của máy chạy BE; không thì
    fetch HTTP từ MEDIA_BASE_URL.


    None ở đây HỎNG ÂM THẦM ở tầng trên: rerank_service coi là ảnh trống, còn
    agent_service bỏ qua frame đó - cả hai không log gì, nên hệ thống vẫn "chạy"
    trong khi rerank visual mất tác dụng và QA trả lời không nhìn ảnh nào. Vì
    vậy phải kêu ở ĐÂY, mỗi URL đúng một lần (lỗi hay gặp là cả kho ảnh sai chỗ
    -> 100 frame/request sẽ ngập log nếu kêu mọi lần).
    """
    key = f"{video_name}/{frame_name}"
    with _frame_lock:
        if key in _frame_cache:
            return _frame_cache[key]

    # MEDIA_DIR đặt rồi -> đọc thẳng đĩa, KHÔNG có đường lui về HTTP. Fallback ở
    # đây sẽ biến "cấu hình sai đường dẫn" thành "chạy chậm bí ẩn qua tunnel",
    # đúng kiểu hỏng mà cả file này đang cố tránh. Sai thì phải kêu.
    local = local_frame_path(video_name, frame_name)
    if local is not None:
        try:
            data = local.read_bytes()
        except OSError as exc:
            _warn_fetch_failed(str(local), f"{exc} (MEDIA_DIR dat roi - sai duong dan?)")
            return None
        _cache_frame(key, data)
        return data

    url = frame_bytes_url(video_name, frame_name)
    try:
        r = _client().get(url)
        r.raise_for_status()
        data = r.content
    except Exception as exc:  # noqa: BLE001 - hỏng kiểu gì cũng không được chặn search
        _warn_fetch_failed(url, exc)
        return None
    # FE trả index.html (SPA fallback) khi đường dẫn không có thật -> vẫn 200,
    # vẫn có bytes, nhưng PIL sẽ ngã ở tầng trên mà không ai biết vì sao.
    ctype = r.headers.get("content-type", "")
    if not ctype.startswith("image/"):
        _warn_fetch_failed(url, f"content-type={ctype!r} (khong phai anh - sai MEDIA_BASE_URL?)")
        return None
    _cache_frame(key, data)
    return data


def frame_bytes_many(pairs: List[tuple]) -> List[Optional[bytes]]:
    """frame_bytes cho nhiều (video_name, frame_name) - tải SONG SONG.

    Đường nóng của BLIP rerank (100 ảnh) và agent QA (12 ảnh). Tải tuần tự thì
    tổng thời gian = số ảnh × RTT, mà RTT qua ngrok là hàng trăm ms: 100 ảnh
    thành hàng chục giây. Fetch là I/O nên thread nhả GIL, chạy song song thật.
    Thứ tự trả về khớp thứ tự đầu vào; phần tử lỗi là None.
    """
    if not pairs:
        return []
    if len(pairs) == 1:
        return [frame_bytes(*pairs[0])]
    with ThreadPoolExecutor(max_workers=min(_FETCH_WORKERS, len(pairs))) as pool:
        return list(pool.map(lambda p: frame_bytes(*p), pairs))


@lru_cache(maxsize=4096)
def _watch_url(video_name: str) -> Optional[str]:
    """watch_url (YouTube...) lấy từ data/metadata/media-info/<video_name>.json, hoặc None."""
    path = settings.data_path / "metadata" / "media-info" / f"{video_name}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f).get("watch_url") or None
    except Exception:
        return None


def video_url(video_name: str) -> str:
    # Video nằm trên FE (public/media/videos/<video_name>.mp4). Nếu thiếu file,
    # fallback sang watch_url (YouTube) lấy từ data/metadata/media-info/*.json.
    watch = _watch_url(video_name)
    if watch:
        return watch
    return f"{settings.media_base}/media/videos/{video_name}.mp4"


def _result_dict(frame_id: str, score: float) -> dict:
    from services.graph_service import shot_range  # local import to avoid cycle

    meta = get_meta(frame_id)
    # Khoảng shot chứa frame - sửa Ở ĐÂY là mọi loại truy vấn đều có, vì tất cả
    # endpoint đều đi qua hàm này. None khi chưa build graph.json.
    shot = shot_range(frame_id)
    return {
        "id": frame_id,
        "score": float(score),
        "frame_name": meta["frame_name"],
        "video_name": meta["video_name"],
        "timestamp_ms": meta["timestamp_ms"],
        "fps": meta["fps"],
        # Frame ẢO (register_virtual_frame) không có ảnh: hiện keyframe thật gần
        # nhất, còn frame_name giữ chỉ số ảo để FE tính frame_idx nộp bài.
        "frame_url": frame_url(meta["video_name"], meta.get("display_frame") or meta["frame_name"]),
        "video_url": video_url(meta["video_name"]),
        "scene_id": shot["scene_id"] if shot else None,
        "shot_start_ms": shot["start_ms"] if shot else None,
        "shot_end_ms": shot["end_ms"] if shot else None,
    }


def filter_candidates(
    raw_results: List[dict],
    ocr_filter: str = "",
    asr_filter: str = "",
    # str, hoặc danh sách các bộ từ khoá thay thế nhau (gốc + bản dịch) -
    # xem caption_service.frame_has_caption_text.
    caption_filter="",
) -> List[dict]:
    """Bỏ ứng viên không qua bộ lọc OCR/ASR/caption. Giữ nguyên mọi khoá khác.

    Tách khỏi build_search_results để router CÓ RERANK gọi được sớm: lọc sau
    rerank nghĩa là BLIP đã tốn lượt chấm cho những frame sắp bị vứt.
    """
    from services.ocr_service import frame_has_ocr_text  # local import to avoid cycle
    from services.asr_service import video_has_asr_text
    from services.caption_service import frame_has_caption_text

    if not (ocr_filter or asr_filter or caption_filter):
        return list(raw_results)

    out: List[dict] = []
    for item in raw_results:
        frame_id = item["id"]
        if ocr_filter and not frame_has_ocr_text(frame_id, ocr_filter):
            continue
        if asr_filter and not video_has_asr_text(get_meta(frame_id)["video_name"], asr_filter):
            continue
        if caption_filter and not frame_has_caption_text(frame_id, caption_filter):
            continue
        out.append(item)
    return out


def build_search_results(
    raw_results: List[dict],
    top_k: int,
    ocr_filter: str = "",
    asr_filter: str = "",
    caption_filter="",
    # Tên model ĐƠN để lấy vector gộp frame trùng (xem dedup_service). "" = tắt.
    # Ensemble phải quy về primary_model trước khi truyền vào đây. Router nào đã
    # tự gộp trước rerank thì để trống, đừng gộp hai lần.
    dedup_model: str = "",
    dedup_threshold: Optional[float] = None,
) -> List[dict]:
    """Convert [{id, score}, ...] into full SearchResult dicts, applying post-filters."""
    # Lọc TRƯỚC, gộp SAU. Ngược lại thì đại diện của một cụm có thể bị bộ lọc
    # loại và kéo theo cả cụm biến mất, dù trong cụm còn frame hợp lệ.
    passed = filter_candidates(raw_results, ocr_filter, asr_filter, caption_filter)

    if dedup_model:
        from services.dedup_service import group_duplicates
        passed = group_duplicates(passed, model=dedup_model, threshold=dedup_threshold)

    # top_k đếm theo ĐẠI DIỆN, không đếm bản trùng: bật gộp mà vẫn đếm cả bản
    # trùng thì trang kết quả co lại đúng bằng phần vừa gộp, tức là chẳng lợi gì.
    out: List[dict] = []
    for item in passed[:top_k]:
        dups = item.get("duplicates") or []
        out.append({
            **_result_dict(item["id"], item["score"]),
            "duplicates": [_result_dict(d["id"], d["score"]) for d in dups],
            "duplicate_count": len(dups),
        })
    return out


def video_fps(video_name: str) -> float:
    """fps của video, lấy từ keyframe đầu tiên trong frames_meta (mặc định 25)."""
    names = frames_in_video(video_name)
    if names:
        stem = names[0].rsplit(".", 1)[0]
        meta = _load_frames_meta().get(f"{video_name}_{stem}")
        if meta and meta.get("fps"):
            return float(meta["fps"])
    return 25.0


def nearest_keyframe(video_name: str, frame_idx: int) -> Optional[str]:
    """frame_name của keyframe THẬT gần chỉ số frame_idx nhất (để hiện ảnh)."""
    names = frames_in_video(video_name)
    if not names:
        return None
    idxs = [int(n.rsplit(".", 1)[0]) for n in names if n.rsplit(".", 1)[0].isdigit()]
    if not idxs:
        return None
    i = min(range(len(idxs)), key=lambda k: abs(idxs[k] - frame_idx))
    return names[i]


def register_virtual_frame(video_name: str, frame_idx: int) -> str:
    """Đăng ký một frame KHÔNG có keyframe (vd mốc ASR trong bài giảng slide) để
    nó đi qua build_search_results / nộp bài như frame thường.

    Trả frame_id "<video>_<idx:06d>". Chỉ sống trong RAM của tiến trình; không
    ghi frames_meta.json. Ảnh hiển thị = keyframe thật gần nhất (display_frame).
    """
    frame_idx = max(int(frame_idx), 0)
    fid = f"{video_name}_{frame_idx:06d}"
    meta = _load_frames_meta()
    if fid not in meta:
        fps = video_fps(video_name)
        meta[fid] = {
            "video_name": video_name,
            "frame_name": f"{frame_idx:06d}.webp",
            "timestamp_ms": int(frame_idx / fps * 1000),
            "fps": fps,
            "virtual": True,
            "display_frame": nearest_keyframe(video_name, frame_idx),
        }
    return fid


def frames_in_range(video_name: str, start_ms: int, end_ms: int) -> List[dict]:
    """Return all frames of a video whose timestamp falls in [start_ms, end_ms]."""
    out: List[dict] = []
    for frame_id, meta in _load_frames_meta().items():
        if meta.get("video_name") != video_name:
            continue
        ts = meta.get("timestamp_ms", 0)
        if start_ms <= ts <= end_ms:
            out.append({"id": frame_id, **meta})
    out.sort(key=lambda x: x["timestamp_ms"])
    return out
