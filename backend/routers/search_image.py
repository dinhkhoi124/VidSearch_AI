import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from config import get_settings
from models.schemas import SearchResponse
from services.embedding_service import encode_image
from services.ensemble_service import (
    ensemble_search,
    ensemble_spec,
    is_ensemble,
    primary_model,
)
from services.faiss_service import search_index
from services.graph_service import aggregate_scene_scores, expand_knn
from services.metadata_service import build_search_results
from services.neighbor_service import aggregate_neighbor_scores

router = APIRouter()
settings = get_settings()


@router.post("/search_image", response_model=SearchResponse)
async def search_image(
    image: UploadFile = File(...),
    top_k: int = 25,
    model: str = settings.default_model,
    dedup: bool = True,     # gộp frame trùng thị giác — xem services/dedup_service
    dedup_threshold: float = 0.0,   # <= 0: dùng RESULT_DEDUP_THRESHOLD trong config
):
    try:
        contents = await image.read()
        pil = Image.open(io.BytesIO(contents)).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {e}")

    if is_ensemble(model):
        raw = ensemble_search(lambda m: encode_image(pil, model=m), top_k=top_k * 3,
                              spec=ensemble_spec(model))
    else:
        vec = encode_image(pil, model=model)
        raw = search_index(vec, top_k=top_k * 3, model=model)
    raw = expand_knn(raw, model=primary_model(model))
    raw = aggregate_neighbor_scores(raw)
    raw = aggregate_scene_scores(raw)
    results = build_search_results(
        raw, top_k=top_k,
        dedup_model=primary_model(model) if dedup else "",
        dedup_threshold=dedup_threshold if dedup_threshold > 0 else None,
    )
    return {"results": results}
