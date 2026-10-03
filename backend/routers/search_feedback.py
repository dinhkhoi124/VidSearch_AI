"""Relevance feedback search - refine results from user-picked frames.

MemoriEase 3.0 (Tran et al., LSC'25, §3.5): pooling only the picked images
drifts away from the original intent, so the pooled visual embedding is BLENDED
with the original query embedding:

    v = w * encode_text(query) + (1 - w) * mean(vectors of picked frames)

with w = settings.feedback_query_weight (query="" -> pure visual pooling).
Frame vectors come straight out of the flat FAISS index (no re-encoding of
images), so a feedback round costs one text encode + one index search.
The picked frames themselves are excluded from the response.
"""
from typing import List

from fastapi import APIRouter, HTTPException

from config import get_settings
from models.schemas import FeedbackSearchRequest, SearchResponse
from services.embedding_service import encode_text
from services.ensemble_service import primary_model
from services.faiss_service import reconstruct_vectors, search_index
from services.graph_service import aggregate_scene_scores, expand_knn
from services.metadata_service import build_search_results
from services.neighbor_service import aggregate_neighbor_scores

router = APIRouter()
settings = get_settings()


@router.post("/search_feedback", response_model=SearchResponse)
async def search_feedback(req: FeedbackSearchRequest):
    if not req.frame_ids:
        raise HTTPException(status_code=400, detail="frame_ids cannot be empty")

    import numpy as np

    # Feedback dựng lại vector TỪ index nên phải nằm trong đúng một không gian
    # vector: "ensemble" (và tổ hợp "siglip512+metaclip" của UI) không có index
    # riêng, quy về member trọng số cao nhất.
    model = primary_model(req.model)

    vecs = reconstruct_vectors(req.frame_ids, model=model)
    if vecs is None:
        raise HTTPException(
            status_code=404,
            detail="None of the frame_ids is in the index (check model / ids)",
        )
    pooled = vecs.mean(axis=0)
    pooled /= np.linalg.norm(pooled) or 1.0

    w = settings.feedback_query_weight
    if req.query.strip() and w > 0:
        qvec = np.asarray(encode_text(req.query, model=model), dtype=np.float32).ravel()
        qvec /= np.linalg.norm(qvec) or 1.0
        pooled = w * qvec + (1.0 - w) * pooled

    picked = set(req.frame_ids)
    raw = search_index(pooled, top_k=req.top_k * 3 + len(picked), model=model)
    raw = [r for r in raw if r["id"] not in picked]

    raw = expand_knn(raw, model=model)
    raw = aggregate_neighbor_scores(raw)
    raw = aggregate_scene_scores(raw)
    return {"results": build_search_results(raw, top_k=req.top_k, dedup_model=model)}
