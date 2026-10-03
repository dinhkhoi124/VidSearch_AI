"""Trả về các keyframe liên tiếp quanh một frame trong cùng một video.

Dùng cho tính năng "xem chuỗi frame": đọc danh sách frame từ
`data/metadata/keyframe_index.json` (sinh bởi data_processing) thay vì
đọc trực tiếp thư mục keyframe trên disk - media giờ nằm trên FE.
"""
from fastapi import APIRouter, HTTPException, Query

from services.metadata_service import frame_url, frames_in_video, get_meta, video_url

router = APIRouter()


def _stem_int(name: str):
    stem = name.rsplit(".", 1)[0]
    return int(stem) if stem.isdigit() else None


@router.get("/frame_neighbors")
def frame_neighbors(
    video_name: str,
    frame_name: str,
    window: int = Query(40, ge=1, le=500),
):
    """Lấy `window` frame trước và `window` frame sau frame_name (cùng video).

    Trả về danh sách đã sắp xếp theo thứ tự frame, đánh dấu frame hiện tại.
    """
    files = frames_in_video(video_name)
    if not files:
        raise HTTPException(
            status_code=404,
            detail=(f"No keyframe_index entry for video: {video_name}. "
                    "Run data_processing step to build keyframe_index.json."),
        )

    if frame_name in files:
        center = files.index(frame_name)
    else:
        target = _stem_int(frame_name)
        if target is not None:
            center = min(
                range(len(files)),
                key=lambda i: abs((_stem_int(files[i]) or 0) - target),
            )
        else:
            center = 0

    start = max(0, center - window)
    end = min(len(files), center + window + 1)

    # Trả về ĐỦ trường của một SearchResult (id, timestamp_ms, fps, video_url)
    # chứ không chỉ ảnh: nhờ vậy frontend dùng thẳng ResultItem cho từng frame
    # lân cận, thêm được vào giỏ đáp án (giỏ chống trùng bằng `id`) và mở video
    # đúng đoạn. Trước đây payload thiếu id/timestamp_ms nên bấm vào chỉ zoom ảnh.
    frames = []
    for i, name in enumerate(files[start:end]):
        stem = name.rsplit(".", 1)[0]
        frame_id = f"{video_name}_{stem}"
        meta = get_meta(frame_id)
        frames.append(
            {
                "index": start + i,
                "id": frame_id,
                "frame_name": name,
                "video_name": video_name,
                "timestamp_ms": meta["timestamp_ms"],
                "fps": meta["fps"],
                "frame_url": frame_url(video_name, name),
                "video_url": video_url(video_name),
                "is_current": name == frame_name,
            }
        )

    return {
        "video_name": video_name,
        "total": len(files),
        "center_index": center,
        "frames": frames,
    }