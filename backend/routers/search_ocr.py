from fastapi import APIRouter, HTTPException

from config import get_settings
from models.schemas import SearchResponse
from services.ensemble_service import primary_model
from services.metadata_service import build_search_results
from services.ocr_service import search_ocr

router = APIRouter()
settings = get_settings()


@router.post("/search_ocr", response_model=SearchResponse)
async def search_ocr_route(
    query: str,
    top_k: int = 25,
    model: str = "beit3",  # accepted for API parity; unused unless you add re-ranking
    ocr_keywords: str = "",
    asr_keywords: str = "",
    rerank: bool = True,
    dedup: bool = True,     # gộp frame trùng thị giác — xem services/dedup_service
    dedup_threshold: float = 0.0,   # <= 0: dùng RESULT_DEDUP_THRESHOLD trong config
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    raw = search_ocr(query, top_k=top_k * 3, rerank=rerank)
    results = build_search_results(
        raw, top_k=top_k, ocr_filter=ocr_keywords, asr_filter=asr_keywords,
        # Kênh này không dùng backbone visual, nhưng gộp trùng thì cần vector —
        # lấy ở model mặc định của backend (chắc chắn có index).
        dedup_model=primary_model(settings.default_model) if dedup else "",
        dedup_threshold=dedup_threshold if dedup_threshold > 0 else None,
    )
    return {"results": results}
