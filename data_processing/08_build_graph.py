"""Step 08 - Build the graph layer: Video -> Scene -> Frame -> Object (+ kNN).

Everything is derived from data that already exists - no model inference:

    frames_meta.json                     frame nodes + timestamps (step 01)
    SceneJSON/<batch>/<Vxxx>.json        scene nodes: [[start_idx, end_idx], ...]
    objects/<video>/<n>.json             object detections on OFFICIAL keyframes
    map-keyframes/<video>.csv            maps official keyframe n -> frame_idx
    data/objects/objects_data.json       optional per-frame detections on OUR
                                         keyframes (kaggle/08_extract-objects.ipynb)
    data/ocr/ocr_data.json               scene-level OCR text (step 04)
    data/asr/asr_data.json               scene-level ASR text (step 05)
    indexes/<model>.index (IndexFlatIP)  optional kNN similarity edges (--knn)

Outputs (loaded lazily by backend services/graph_service.py):

    data/graph/graph.json
        scenes        {scene_id: {video_name, start_ms, end_ms, frames, objects,
                                  ocr, asr}}
        frame_scene   {frame_id: scene_id}
        frame_objects {frame_id: {label: score}}   (frames near an official keyframe)
        object_scenes {label_lower: [scene_id, ...]}
    data/graph/knn_<model>.json          (--knn only)
        {frame_id: [[neighbour_frame_id, cosine], ...]}

Scene ids are "<video_name>:<k>". Videos missing from SceneJSON fall back to
splitting at temporal gaps > SCENE_FALLBACK_GAP_MS between keyframes.

Run after step 01 (and 03 if using --knn):
    python 08_build_graph.py            # graph only
    python 08_build_graph.py --knn      # graph + kNN edges from <MODEL_KEY>.index
"""
import argparse
import csv
import json
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tqdm import tqdm

import config


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# --- Frames -------------------------------------------------------------------

def load_frames_by_video() -> Dict[str, dict]:
    """{video_name: {"fps": float, "frames": [(frame_idx, ts_ms, frame_id), ...]}}."""
    meta = _load_json(config.FRAMES_META_FILE)
    by_video: Dict[str, dict] = {}
    for frame_id, m in meta.items():
        idx = int(Path(m["frame_name"]).stem)
        v = by_video.setdefault(m["video_name"], {"fps": float(m.get("fps") or 25.0),
                                                  "frames": []})
        v["frames"].append((idx, int(m["timestamp_ms"]), frame_id))
    for v in by_video.values():
        v["frames"].sort()
    return by_video


# --- Scenes -------------------------------------------------------------------

def load_scene_ranges(video_name: str) -> Optional[List[Tuple[int, int]]]:
    """Official scene ranges [[start_idx, end_idx], ...] or None if unavailable."""
    batch, _, tail = video_name.partition("_")          # L21_V001 -> L21 / V001
    path = config.SCENE_JSON_DIR / batch / f"{tail}.json"
    if not path.exists():
        return None
    ranges = _load_json(path)
    return [(int(s), int(e)) for s, e in ranges] if ranges else None


def fallback_scene_ranges(frames: List[Tuple[int, int, str]]) -> List[Tuple[int, int]]:
    """Split at gaps > SCENE_FALLBACK_GAP_MS when no SceneJSON exists."""
    ranges, start = [], frames[0][0]
    for (idx, ts, _), (nidx, nts, _) in zip(frames, frames[1:]):
        if nts - ts > config.SCENE_FALLBACK_GAP_MS:
            ranges.append((start, idx))
            start = nidx
    ranges.append((start, frames[-1][0]))
    return ranges


def assign_scene(starts: List[int], ranges: List[Tuple[int, int]], idx: int) -> int:
    """Scene position for a frame_idx: containing range, else nearest one."""
    k = bisect_right(starts, idx) - 1
    if k < 0:
        return 0
    if idx <= ranges[k][1] or k == len(ranges) - 1:
        return k
    # idx falls in the gap between scene k and k+1 -> closer boundary wins
    return k if idx - ranges[k][1] <= ranges[k + 1][0] - idx else k + 1


# --- Objects ------------------------------------------------------------------

def load_keyframe_map(video_name: str) -> Dict[int, int]:
    """{n: frame_idx} from the official map-keyframes CSV, or {}."""
    path = config.MAP_KEYFRAMES_DIR / f"{video_name}.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return {int(row["n"]): int(row["frame_idx"]) for row in csv.DictReader(f)}


def load_objects(video_name: str, n: int) -> Dict[str, float]:
    """{label: max_score} of detections above threshold for official keyframe n."""
    path = config.OBJECTS_DIR / video_name / f"{n:03d}.json"
    if not path.exists():
        return {}
    d = _load_json(path)
    out: Dict[str, float] = {}
    for label, score in zip(d.get("detection_class_entities", []),
                            d.get("detection_scores", [])):
        s = float(score)
        if s >= config.OBJECT_SCORE_THRESHOLD:
            out[label] = max(out.get(label, 0.0), s)
    return out


def load_optional_json(path: Path) -> dict:
    return _load_json(path) if path.exists() else {}


def scene_asr_text(segments: List[dict], start_ms: int, end_ms: int) -> str:
    """Speech overlapping [start_ms, end_ms], in order (segments are sorted)."""
    return " ".join(
        seg["text"].strip()
        for seg in segments
        if seg["start_ms"] < end_ms and seg["end_ms"] > start_ms and seg.get("text")
    ).strip()


def load_custom_objects() -> Dict[str, Dict[str, float]]:
    """{frame_id: {label: score}} detected on OUR keyframes (notebook step 8)."""
    if not config.OBJECTS_DATA_FILE.exists():
        return {}
    data = _load_json(config.OBJECTS_DATA_FILE)
    out: Dict[str, Dict[str, float]] = {}
    for frame_id, objs in data.items():
        kept = {l: round(float(s), 4) for l, s in objs.items()
                if float(s) >= config.OBJECT_SCORE_THRESHOLD}
        if kept:
            out[frame_id] = kept
    return out


def nearest_frame(frames: List[Tuple[int, int, str]], idx: int) -> Tuple[int, int, str]:
    """Frame of the video whose frame_idx is closest to idx (frames idx-sorted)."""
    pos = bisect_right([f[0] for f in frames], idx)
    best = min(
        (frames[p] for p in (pos - 1, pos) if 0 <= p < len(frames)),
        key=lambda f: abs(f[0] - idx),
    )
    return best


# --- Build --------------------------------------------------------------------

def build_graph() -> dict:
    by_video = load_frames_by_video()
    custom_objects = load_custom_objects()
    ocr_data: Dict[str, str] = load_optional_json(config.OCR_FILE)
    asr_data: Dict[str, list] = load_optional_json(config.ASR_FILE)
    scenes: Dict[str, dict] = {}
    frame_scene: Dict[str, str] = {}
    frame_objects: Dict[str, Dict[str, float]] = {}
    object_scenes: Dict[str, List[str]] = defaultdict(list)
    n_official_scenes = n_kf_with_objects = 0

    for video_name, video in tqdm(sorted(by_video.items()), desc="graph"):
        frames, meta_fps = video["frames"], video["fps"]
        ranges = load_scene_ranges(video_name)
        if ranges:
            n_official_scenes += 1
        else:
            ranges = fallback_scene_ranges(frames)
        starts = [r[0] for r in ranges]

        # scene nodes + frame -> scene edges
        scene_ids = [f"{video_name}:{k}" for k in range(len(ranges))]
        segments = sorted(asr_data.get(video_name, []), key=lambda x: x["start_ms"])
        for k, (s, e) in enumerate(ranges):
            start_ms, end_ms = int(s / meta_fps * 1000), int(e / meta_fps * 1000)
            scenes[scene_ids[k]] = {
                "video_name": video_name,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "frames": [],
                "objects": {},
                "ocr": "",
                "asr": scene_asr_text(segments, start_ms, end_ms),
            }
        for idx, ts, frame_id in frames:
            k = assign_scene(starts, ranges, idx)
            frame_scene[frame_id] = scene_ids[k]
            scenes[scene_ids[k]]["frames"].append(frame_id)
            # per-frame detections on our own keyframes (notebook step 8)
            objs = custom_objects.get(frame_id)
            if objs:
                merged = frame_objects.setdefault(frame_id, {})
                scene_objs = scenes[scene_ids[k]]["objects"]
                for label, s in objs.items():
                    merged[label] = max(merged.get(label, 0.0), s)
                    scene_objs[label] = max(scene_objs.get(label, 0.0), s)

        # scene OCR = member frames' OCR joined, exact duplicates dropped
        # (consecutive keyframes usually re-read the same banner/caption)
        for scene_id in scene_ids:
            seen, parts = set(), []
            for frame_id in scenes[scene_id]["frames"]:
                text = (ocr_data.get(frame_id) or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    parts.append(text)
            scenes[scene_id]["ocr"] = " ".join(parts)

        # object edges: official keyframe n -> (scene, nearest extracted frame)
        kf_map = load_keyframe_map(video_name)
        for n, kf_idx in kf_map.items():
            objs = load_objects(video_name, n)
            if not objs:
                continue
            n_kf_with_objects += 1
            k = assign_scene(starts, ranges, kf_idx)
            scene_objs = scenes[scene_ids[k]]["objects"]
            for label, s in objs.items():
                scene_objs[label] = max(scene_objs.get(label, 0.0), round(s, 4))
            fidx, fts, frame_id = nearest_frame(frames, kf_idx)
            if abs(fidx - kf_idx) / meta_fps * 1000 <= config.OBJECT_MATCH_TOLERANCE_MS:
                merged = frame_objects.setdefault(frame_id, {})
                for label, s in objs.items():
                    merged[label] = max(merged.get(label, 0.0), round(s, 4))

    for scene_id, sc in scenes.items():
        for label in sc["objects"]:
            object_scenes[label.lower()].append(scene_id)

    print(f"[INFO] {len(scenes)} scenes ({n_official_scenes} videos with official "
          f"SceneJSON), {len(frame_scene)} frames, "
          f"{n_kf_with_objects} official keyframes with objects, "
          f"{len(custom_objects)} frames with custom detections, "
          f"{len(object_scenes)} distinct object labels")
    return {
        "version": 1,
        "scenes": scenes,
        "frame_scene": frame_scene,
        "frame_objects": frame_objects,
        "object_scenes": dict(object_scenes),
    }


def build_knn(model_key: str) -> Optional[dict]:
    """kNN similarity edges from the flat FAISS index (cosine, unit vectors)."""
    import faiss
    import numpy as np

    index_path = config.index_file(model_key)
    id_map_path = config.id_map_file(model_key)
    if not id_map_path.exists():
        id_map_path = config.ID_MAP_FILE
    if not index_path.exists() or not id_map_path.exists():
        print(f"[WARN] Missing {index_path} or id map - skipping kNN graph")
        return None

    index = faiss.read_index(str(index_path))
    ids: List[str] = _load_json(id_map_path)
    assert index.ntotal == len(ids), "index / id_map size mismatch"

    k = config.KNN_K + 1  # +1: the query itself comes back as its own neighbour
    edges: Dict[str, List[Tuple[str, float]]] = {}
    for lo in tqdm(range(0, index.ntotal, config.KNN_BATCH_SIZE), desc=f"knn:{model_key}"):
        hi = min(lo + config.KNN_BATCH_SIZE, index.ntotal)
        block = index.reconstruct_n(lo, hi - lo)
        sims, nbrs = index.search(np.ascontiguousarray(block), k)
        for row, (srow, nrow) in enumerate(zip(sims, nbrs), start=lo):
            out = [
                (ids[j], round(float(s), 4))
                for s, j in zip(srow, nrow)
                if j >= 0 and j != row and s >= config.KNN_SIM_THRESHOLD
            ]
            if out:
                edges[ids[row]] = out
    print(f"[INFO] kNN graph: {len(edges)} frames with >=1 edge "
          f"(k={config.KNN_K}, sim>={config.KNN_SIM_THRESHOLD})")
    return edges


def main(knn: bool = False) -> None:
    config.GRAPH_DIR.mkdir(parents=True, exist_ok=True)

    graph = build_graph()
    with config.GRAPH_FILE.open("w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False)
    print(f"[INFO] Wrote {config.GRAPH_FILE}")

    if knn:
        edges = build_knn(config.MODEL_KEY)
        if edges is not None:
            path = Path(str(config.KNN_GRAPH_FILE).format(model=config.MODEL_KEY))
            with path.open("w", encoding="utf-8") as f:
                json.dump(edges, f, ensure_ascii=False)
            print(f"[INFO] Wrote {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build graph layer (step 08)")
    parser.add_argument("--knn", action="store_true",
                        help="also build kNN similarity edges from the FAISS index")
    args = parser.parse_args()
    main(knn=args.knn)
