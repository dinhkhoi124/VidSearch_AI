"""Graph layer: scene-aware rerank, object filter/boost, kNN expansion.

Loads the heterogeneous graph built by data_processing step 08:

    data/graph/graph.json          Video -> Scene -> Frame -> Object
    data/graph/knn_<model>.json    frame -> [(frame, cosine), ...] similarity edges

Every public function degrades to a no-op when the graph files are missing, so
the backend runs unchanged without step 08.

Three training-free uses, all on the already-retrieved candidate list:

  aggregate_scene_scores  Like neighbor_service but grouped by SHOT boundaries
                          instead of a fixed time window: a candidate whose
                          scene-mates also score high is likelier to sit in the
                          target scene. Bonus = w * mean(scene-mates' scores),
                          mean not sum for the same inflation reason as
                          neighbor_service.
  apply_object_filter     "person, motorcycle" -> keep (mode=filter) or boost
                          (mode=boost) candidates whose SCENE contains all the
                          requested OpenImages labels. Scene-level, not
                          frame-level: detections only exist on the official
                          keyframes, the query object may be visible a few
                          frames away from the candidate.
  expand_knn              1-step walk over similarity edges: neighbours of the
                          top candidates enter the pool with w * sim * score.
                          Recovers near-duplicate frames dropped from the index
                          by dedup (step 03) and visually-identical shots in
                          other videos.
  apply_scene_text_filter "60 giây, bão" -> keep/boost candidates whose scene
                          TEXT (OCR of member frames + ASR overlapping the shot)
                          contains the keywords. Finer than the existing
                          filters: ocr_keywords is per-frame (the banner may sit
                          on a neighbouring frame), asr_keywords is per-VIDEO.
                          Fuzzy (rapidfuzz partial_ratio >= fuzzy_threshold)
                          when available, exact substring otherwise.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional

from config import get_settings

settings = get_settings()


# --- Loading -------------------------------------------------------------------

@lru_cache
def _load_graph() -> Optional[dict]:
    path = settings.data_path / "graph" / "graph.json"
    if not path.exists():
        return None
    import json
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def _load_knn(model: str) -> Optional[Dict[str, list]]:
    path = settings.data_path / "graph" / f"knn_{model}.json"
    if not path.exists():
        return None
    import json
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def graph_available() -> bool:
    return _load_graph() is not None


def preload(models: List[str] | None = None) -> Optional[dict]:
    """Nạp sẵn graph.json (+ knn_<model>.json) và index token của scene text.

    Trả {scenes, frames, knn: {model: nodes}} hoặc None khi chưa build graph.
    """
    g = _load_graph()
    if g is None:
        return None
    _scene_token_index()  # dựng sẵn index token - bước nặng nhất của graph
    knn = {}
    for model in models or []:
        data = _load_knn(model)
        if data is not None:
            knn[model] = len(data)
    return {
        "scenes": len(g.get("scenes", {}) or {}),
        "frames": len(g.get("frame_scene", {}) or {}),
        "knn": knn,
    }


def _scene_of(frame_id: str) -> Optional[str]:
    g = _load_graph()
    return g["frame_scene"].get(frame_id) if g else None


# --- Scene-aware score aggregation ----------------------------------------------

def aggregate_scene_scores(raw: List[dict]) -> List[dict]:
    """Re-score [{id, score}, ...] with a same-scene bonus and re-sort."""
    weight = settings.graph_scene_weight
    g = _load_graph()
    if weight <= 0 or g is None or len(raw) < 2:
        return raw

    by_scene: Dict[str, List[int]] = {}
    for i, item in enumerate(raw):
        scene = g["frame_scene"].get(item["id"])
        if scene:
            by_scene.setdefault(scene, []).append(i)

    out = [dict(item) for item in raw]
    for indices in by_scene.values():
        if len(indices) < 2:
            continue
        total = sum(float(raw[i]["score"]) for i in indices)
        for i in indices:
            mates_mean = (total - float(raw[i]["score"])) / (len(indices) - 1)
            out[i]["score"] = float(raw[i]["score"]) + weight * mates_mean

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# --- Object filter / boost -------------------------------------------------------

def _parse_labels(objects_query: str) -> List[str]:
    return [t.strip().lower() for t in objects_query.split(",") if t.strip()]


def _scene_matches(scene: dict, labels: List[str]) -> float:
    """Fraction of requested labels present in the scene (substring match)."""
    scene_labels = [l.lower() for l in scene["objects"]]
    hit = sum(
        1 for q in labels
        if any(q in sl or sl in q for sl in scene_labels)
    )
    return hit / len(labels)


def apply_object_filter(raw: List[dict], objects_query: str, mode: str = "boost") -> List[dict]:
    """Filter or boost candidates by OpenImages labels found in their scene.

    mode=filter: keep only candidates whose scene contains ALL requested labels.
    mode=boost : score += graph_object_bonus * matched_fraction.
    """
    labels = _parse_labels(objects_query)
    g = _load_graph()
    if not labels or g is None:
        return raw

    out: List[dict] = []
    for item in raw:
        scene_id = g["frame_scene"].get(item["id"])
        frac = _scene_matches(g["scenes"][scene_id], labels) if scene_id else 0.0
        if mode == "filter":
            if frac >= 1.0:
                out.append(item)
        else:
            boosted = dict(item)
            boosted["score"] = float(item["score"]) + settings.graph_object_bonus * frac
            out.append(boosted)

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# --- Scene text (OCR + ASR) filter / boost -----------------------------------------

def _keyword_in_text(keyword: str, text: str, text_folded: str) -> bool:
    # Exact thử cả bản fold (bỏ dấu): OCR broadcast rớt dấu, "Tam Kỳ" phải khớp
    # "Tam Ky". Fuzzy vẫn chạy trên bản CÓ dấu - fold + threshold 0.6 với chuỗi
    # ngắn sẽ khớp bừa ("tam ky" ~ "ham...").
    if keyword in text or _fold(keyword) in text_folded:
        return True
    from services.fuzzy_service import fuzzy_scores, is_available
    if not is_available():
        return False
    # Keyword ngắn thì partial_ratio khớp bừa (đo được: "tam kỳ" ~ text bóng đá
    # bất kỳ = 0.67) - nâng cutoff cho chuỗi < 12 ký tự thay vì tin threshold chung.
    cutoff = settings.fuzzy_threshold if len(keyword) >= 12 else max(
        settings.fuzzy_threshold, 0.85)
    return bool(fuzzy_scores(keyword, {0: text}, cutoff=cutoff))


def _scene_text_frac(scene: dict, keywords: List[str]) -> float:
    text = f"{scene.get('ocr', '')} {scene.get('asr', '')}".lower()
    if not text.strip():
        return 0.0
    text_folded = _fold(text)
    return sum(1 for q in keywords if _keyword_in_text(q, text, text_folded)) / len(keywords)


def _fold(s: str) -> str:
    """Thường hoá + bỏ dấu - OCR/ASR tiếng Việt hay rớt dấu ("nạc" -> "nac")."""
    import unicodedata

    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


@lru_cache
def _scene_token_index():
    """Inverted index token (đã bỏ dấu) -> [scene_id]; build 1 lần, dùng cho QA.

    Scene text < 20 ký tự bị loại - OCR rác 1-2 ký tự khớp fuzzy với mọi thứ.
    """
    g = _load_graph()
    if g is None:
        return {}, []
    vocab: Dict[str, List[str]] = {}
    for sid, s in g["scenes"].items():
        text = f"{s.get('ocr', '')} {s.get('asr', '')}".strip()
        if len(text) < 20:
            continue
        for tok in set(_fold(text).split()):
            if len(tok) >= 2:
                vocab.setdefault(tok, []).append(sid)
    return vocab, list(vocab)


def search_scene_text(keywords_query: str, limit: int = 30) -> List[dict]:
    """Kênh QA "chi tiết đặc trưng": scene chứa cụm chữ/lời nói được trích từ câu hỏi.

    Điểm scene theo keyword = |token của keyword có trong scene| / |token keyword|
    (token so bỏ dấu + gần đúng rapidfuzz - chịu lỗi OCR "tht"/"200 gr"), lấy max
    qua các keyword, giữ scene khớp QUÁ NỬA token. Bất biến thứ tự từ - OCR bảng
    chữ hay đảo dòng nên partial_ratio nguyên cụm trượt ("Nạc dăm xay 200 gr" vs
    "200g thịt nạc xay"). Trả frame của các scene mạnh nhất: [{id, score}].
    """
    labels = _parse_labels(keywords_query)
    g = _load_graph()
    if not labels or g is None:
        return []
    vocab, vocab_tokens = _scene_token_index()
    if not vocab:
        return []
    from services.fuzzy_service import is_available as fuzzy_available
    use_fuzzy = fuzzy_available()

    best: Dict[str, float] = {}
    n_kw_matched: Dict[str, int] = {}
    for kw in labels:
        toks = [t for t in _fold(kw).split() if len(t) >= 2]
        if not toks:
            continue
        hits: Dict[str, int] = {}
        for qt in toks:
            sids = set(vocab.get(qt, ()))
            if use_fuzzy:
                from rapidfuzz import fuzz, process
                for tok, _score, _ in process.extract(
                    qt, vocab_tokens, scorer=fuzz.ratio, score_cutoff=80, limit=30
                ):
                    sids.update(vocab[tok])
            for sid in sids:
                hits[sid] = hits.get(sid, 0) + 1
        for sid, n_hit in hits.items():
            s = n_hit / len(toks)
            if s <= 0.5:
                continue
            # + 0.02/token khớp: cụm DÀI khớp đủ ("trao kinh phí hỗ trợ...")
            # phải thắng cụm 1 token ("1975") - cùng frac 1.0 nhưng bằng chứng
            # mạnh hơn hẳn; đồng thời phá thế hoà điểm hàng loạt.
            s += 0.02 * n_hit
            n_kw_matched[sid] = n_kw_matched.get(sid, 0) + 1
            if s > best.get(sid, 0.0):
                best[sid] = s
    for sid, n in n_kw_matched.items():
        if n > 1:  # trúng NHIỀU keyword độc lập -> bằng chứng cộng hưởng
            best[sid] += 0.05 * (n - 1)

    top = sorted(best, key=best.get, reverse=True)[:limit]
    out: List[dict] = []
    for sid in top:
        for fid in g["scenes"][sid].get("frames", []):
            out.append({"id": fid, "score": best[sid]})
    return out


def apply_scene_text_filter(raw: List[dict], keywords_query: str, mode: str = "boost") -> List[dict]:
    """Filter or boost candidates by keywords in their scene's OCR+ASR text.

    mode=filter: keep only candidates whose scene text contains ALL keywords.
    mode=boost : score += graph_scene_text_bonus * matched_fraction.
    """
    labels = _parse_labels(keywords_query)
    g = _load_graph()
    if not labels or g is None:
        return raw

    frac_cache: Dict[str, float] = {}
    out: List[dict] = []
    for item in raw:
        scene_id = g["frame_scene"].get(item["id"])
        if scene_id is None:
            frac = 0.0
        elif scene_id in frac_cache:
            frac = frac_cache[scene_id]
        else:
            frac = frac_cache[scene_id] = _scene_text_frac(g["scenes"][scene_id], labels)
        if mode == "filter":
            if frac >= 1.0:
                out.append(item)
        else:
            boosted = dict(item)
            boosted["score"] = float(item["score"]) + settings.graph_scene_text_bonus * frac
            out.append(boosted)

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# --- kNN expansion ---------------------------------------------------------------

def expand_knn(raw: List[dict], model: str) -> List[dict]:
    """Add similarity-edge neighbours of the top candidates to the pool."""
    weight = settings.graph_knn_weight
    knn = _load_knn(model)
    if weight <= 0 or knn is None or not raw:
        return raw

    present = {item["id"] for item in raw}
    added: Dict[str, float] = {}
    for item in raw[: settings.graph_knn_expand_top]:
        for nb_id, sim in knn.get(item["id"], []):
            if nb_id in present:
                continue
            s = weight * float(sim) * float(item["score"])
            if s > added.get(nb_id, 0.0):
                added[nb_id] = s

    if not added:
        return raw
    out = list(raw) + [{"id": fid, "score": s} for fid, s in added.items()]
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# --- Introspection (graph router) -------------------------------------------------

def frame_node(frame_id: str) -> Optional[dict]:
    """Everything the graph knows about one frame, or None."""
    g = _load_graph()
    if g is None:
        return None
    scene_id = g["frame_scene"].get(frame_id)
    knn = _load_knn(settings.default_model) or {}
    return {
        "frame_id": frame_id,
        "scene_id": scene_id,
        "scene": g["scenes"].get(scene_id) if scene_id else None,
        "objects": g["frame_objects"].get(frame_id, {}),
        "neighbors": knn.get(frame_id, []),
    }


def shot_range(frame_id: str) -> Optional[dict]:
    """Khoảng thời gian của SHOT chứa frame: {scene_id, start_ms, end_ms}, hoặc None.

    Rẻ hơn frame_node() vì không đụng tới file kNN (hàng trăm MB) - dùng được
    trong build_search_results, tức là trên mọi kết quả của mọi loại truy vấn.
    Trả None khi chưa build graph.json để backend chạy y như cũ.
    """
    g = _load_graph()
    if g is None:
        return None
    scene_id = g["frame_scene"].get(frame_id)
    if not scene_id:
        return None
    scene = g["scenes"].get(scene_id)
    if not scene:
        return None
    return {
        "scene_id": scene_id,
        "start_ms": scene.get("start_ms"),
        "end_ms": scene.get("end_ms"),
    }


def scene_frame_ids(frame_id: str) -> List[str]:
    """All frames of the scene containing frame_id (time-ordered), or []."""
    g = _load_graph()
    if g is None:
        return []
    scene_id = g["frame_scene"].get(frame_id)
    return g["scenes"][scene_id]["frames"] if scene_id else []


def label_stats() -> List[dict]:
    """Available object labels with scene counts, most frequent first."""
    g = _load_graph()
    if g is None:
        return []
    stats = [
        {"label": label, "scene_count": len(scene_ids)}
        for label, scene_ids in g["object_scenes"].items()
    ]
    stats.sort(key=lambda x: x["scene_count"], reverse=True)
    return stats
