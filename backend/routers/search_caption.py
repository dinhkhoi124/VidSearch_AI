from fastapi import APIRouter, HTTPException

from config import get_settings
from models.schemas import SearchResponse
from services.caption_service import captions_available, search_captions
from services.ensemble_service import primary_model
from services.metadata_service import build_search_results

router = APIRouter()
settings = get_settings()


@router.post("/search_caption", response_model=SearchResponse)
async def search_caption_route(
    query: str,
    top_k: int = 25,
    ocr_keywords: str = "",
    asr_keywords: str = "",
    # Mặc định TẮT — đo trên 23 query test (26/8): bge-m3 chấm lại caption không
    # thêm được gì (@1/@5 còn -1), chỉ tốn ~0.3s/query. Caption là văn model
    # sinh nên E5 semantic đã khớp đủ; khác hẳn kênh OCR (@5 1->5-7, giữ rerank).
    rerank: bool = False,
    dedup: bool = True,     # gộp frame trùng thị giác — xem services/dedup_service
    dedup_threshold: float = 0.0,   # <= 0: dùng RESULT_DEDUP_THRESHOLD trong config
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    if not captions_available():
        raise HTTPException(
            status_code=503,
            detail="Captions not built - run kaggle step 9 then data_processing step 07",
        )

    raw = search_captions(query, top_k=top_k * 3, rerank=rerank)
    results = build_search_results(
        raw, top_k=top_k, ocr_filter=ocr_keywords, asr_filter=asr_keywords,
        # Như /search_ocr: kênh chữ, nhưng gộp trùng cần vector của model mặc định.
        dedup_model=primary_model(settings.default_model) if dedup else "",
        dedup_threshold=dedup_threshold if dedup_threshold > 0 else None,
    )
    return {"results": results}
