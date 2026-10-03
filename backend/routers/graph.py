"""Graph introspection endpoints (data/graph, built by data_processing step 08).

GET /graph/labels            OpenImages labels usable in the `objects` filter
GET /graph/frame/{frame_id}  scene + objects + similarity neighbours of a frame
GET /graph/scene/{frame_id}  all keyframes of the scene containing frame_id
"""
from fastapi import APIRouter, HTTPException

from models.schemas import SearchResponse
from services.graph_service import frame_node, graph_available, label_stats, scene_frame_ids
from services.metadata_service import build_search_results

router = APIRouter()


def _require_graph() -> None:
    if not graph_available():
        raise HTTPException(
            status_code=503,
            detail="Graph not built - run data_processing/08_build_graph.py",
        )


@router.get("/graph/labels")
async def get_labels():
    _require_graph()
    return {"labels": label_stats()}


@router.get("/graph/frame/{frame_id}")
async def get_frame_node(frame_id: str):
    _require_graph()
    node = frame_node(frame_id)
    if node is None or node["scene_id"] is None:
        raise HTTPException(status_code=404, detail=f"Frame not in graph: {frame_id}")
    return node


@router.get("/graph/scene/{frame_id}", response_model=SearchResponse)
async def get_scene_frames(frame_id: str):
    _require_graph()
    frame_ids = scene_frame_ids(frame_id)
    if not frame_ids:
        raise HTTPException(status_code=404, detail=f"Frame not in graph: {frame_id}")
    raw = [{"id": fid, "score": 1.0} for fid in frame_ids]
    return {"results": build_search_results(raw, top_k=len(raw))}
