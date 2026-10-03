from fastapi import APIRouter, HTTPException

from models.schemas import AsrSearchResponse
from services.asr_service import search_asr
from services.metadata_service import frame_url, frames_in_range, video_url

router = APIRouter()


@router.post("/search_asr", response_model=AsrSearchResponse)
async def search_asr_route(query: str, asr_filter: str = "", rerank: bool = True):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    raw = search_asr(query, asr_filter=asr_filter, rerank=rerank)

    videos = []
    for v in raw:
        video_name = v["video_name"]
        v_url = video_url(video_name)
        segments = []
        for seg in v["segments"]:
            frames = []
            for fr in frames_in_range(video_name, seg["start_ms"], seg["end_ms"]):
                frames.append(
                    {
                        "id": fr["id"],
                        "frame_name": fr["frame_name"],
                        "frame_url": frame_url(video_name, fr["frame_name"]),
                        "video_url": v_url,
                        "timestamp_ms": fr["timestamp_ms"],
                        "fps": fr["fps"],
                        "score": seg["score"],
                    }
                )
            segments.append({"asr_text": seg["text"], "frames": frames})
        videos.append({"video_name": video_name, "segments": segments})

    return {"videos": videos}
