"""Central configuration for the HCM-AIC-2026 data-processing pipeline.

All paths can be overridden via environment variables so the same scripts run
on a laptop, a Kaggle/Colab notebook or the competition server without edits.

Output paths point straight at the backend so that after running the pipeline
the FastAPI server in ``HCM-AIC-2026/backend`` can serve the results with no
extra copying:

    media/frames/<video_name>/<frame>.jpg     keyframe images
    data/metadata/frames_meta.json            {frame_id: {...}}
    data/indexes/<model>.index + id_map.json  FAISS index
    data/ocr/ocr_data.json                    {frame_id: "text"}
    data/asr/asr_data.json                    {video_name: [{start_ms,...}]}
"""
import os
from pathlib import Path

# --- Anchors -----------------------------------------------------------------
# data_processing/ ; repo root is two levels up (…/HCM_AI)
DATA_PROCESSING_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DATA_PROCESSING_DIR.parent              # …/HCM-AIC-2026
REPO_ROOT = PROJECT_DIR.parent                        # …/HCM_AI


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).resolve()


# --- Inputs (raw competition data) -------------------------------------------
# Glob that matches every source video. The videos live under the backend media
# tree, grouped by batch, e.g.
#     backend/media/videos/Videos_L21/video/L21_V025.mp4
RAW_VIDEOS_GLOB = os.environ.get(
    "RAW_VIDEOS_GLOB",
    str(PROJECT_DIR / "backend" / "media" / "videos" / "*" / "video" / "*.mp4"),
)
# Official keyframe maps: <name>.csv with columns n,pts_time,fps,frame_idx
MAP_KEYFRAMES_DIR = _env_path(
    "MAP_KEYFRAMES_DIR", PROJECT_DIR / "backend" / "data" / "map-keyframes-aic25-b1" / "map-keyframes"
)
# Per-video YouTube metadata (author, length, watch_url, ...)
MEDIA_INFO_DIR = _env_path(
    "MEDIA_INFO_DIR", REPO_ROOT / "media-info-aic25-b1" / "media-info"
)
# TransNetV2 inference package (TF SavedModel + weights) shipped in the repo
TRANSNETV2_INFERENCE_DIR = _env_path(
    "TRANSNETV2_INFERENCE_DIR", REPO_ROOT / "results" / "TransNetV2" / "inference"
)
# Official scene segmentation: <batch>/<Vxxx>.json = [[start_frame_idx, end_frame_idx], ...]
SCENE_JSON_DIR = _env_path(
    "SCENE_JSON_DIR", PROJECT_DIR / "backend" / "data" / "SceneJSON"
)
# Official object detections (OpenImages labels): <video>/<n>.json keyed by the
# keyframe number `n` of the official map-keyframes CSVs. Lives inside the backend
# data tree (copied from the competition bundle).
OBJECTS_DIR = _env_path("OBJECTS_DIR", PROJECT_DIR / "backend" / "data" / "objects-aic25-b1" / "objects")

# --- Outputs (consumed directly by the backend) ------------------------------
BACKEND_DIR = _env_path("BACKEND_DIR", PROJECT_DIR / "backend")
# Media nằm ở FE (Vite serve public/); pipeline chỉ ĐỌC từ đây lúc build index.
# BE không còn mount/đọc media - mọi URL do BE trả về trỏ về FE qua MEDIA_BASE_URL.
MEDIA_DIR = _env_path("MEDIA_DIR", PROJECT_DIR / "frontend" / "public" / "media")
DATA_DIR = _env_path("DATA_DIR", BACKEND_DIR / "data")

FRAMES_DIR = MEDIA_DIR / "frames"                      # media/frames/<video>/<f>.jpg
FEATURES_DIR = DATA_DIR / "features"                   # features/<model>/<video>/<f>.npy
INDEXES_DIR = DATA_DIR / "indexes"                     # <model>.index + id_map.json
METADATA_DIR = DATA_DIR / "metadata"
OCR_DIR = DATA_DIR / "ocr"
ASR_DIR = DATA_DIR / "asr"

FRAMES_META_FILE = METADATA_DIR / "frames_meta.json"
ID_MAP_FILE = INDEXES_DIR / "id_map.json"
# Manifest: { "<video_name>": ["000000.webp", "000025.webp", ...], ... } sorted
# theo số. BE dùng thay cho việc iterdir() thư mục keyframe trên disk (giờ
# media nằm ở FE). Sinh bởi 03b_build_keyframe_index.py.
KEYFRAME_INDEX_FILE = METADATA_DIR / "keyframe_index.json"
OCR_FILE = OCR_DIR / "ocr_data.json"
ASR_FILE = ASR_DIR / "asr_data.json"
# Caption per-frame từ kaggle/09_extract-ocr-caption-qwen.ipynb (tuỳ chọn):
# {frame_id: "<English caption>"} - kênh retrieval thứ 4 bên cạnh visual/ocr/asr
CAPTION_DIR = DATA_DIR / "captions"
CAPTION_FILE = CAPTION_DIR / "caption_data.json"

# --- Graph layer (step 08) - consumed by backend graph_service ----------------
# Heterogeneous graph Video -> Scene -> Frame -> Object built from data that
# already exists (frames_meta + SceneJSON + objects + map-keyframes), plus an
# optional kNN similarity graph reconstructed from the flat FAISS index.
GRAPH_DIR = DATA_DIR / "graph"
GRAPH_FILE = GRAPH_DIR / "graph.json"
KNN_GRAPH_FILE = GRAPH_DIR / "knn_{model}.json"        # .format(model=MODEL_KEY)
# Per-frame detections from kaggle/08_extract-objects.ipynb (optional):
# {frame_id: {label: score}} over OUR extracted keyframes - merged into the
# graph alongside the official objects when present.
OBJECTS_DATA_FILE = DATA_DIR / "objects" / "objects_data.json"
# Keep a detection only when its confidence reaches this threshold
OBJECT_SCORE_THRESHOLD = float(os.environ.get("OBJECT_SCORE_THRESHOLD", "0.3"))
# Match an official keyframe to our nearest extracted frame within this gap
OBJECT_MATCH_TOLERANCE_MS = int(os.environ.get("OBJECT_MATCH_TOLERANCE_MS", "2000"))
# Fallback scene split (no SceneJSON): cut when consecutive keyframes are
# further apart than this gap
SCENE_FALLBACK_GAP_MS = int(os.environ.get("SCENE_FALLBACK_GAP_MS", "3000"))
KNN_K = int(os.environ.get("KNN_K", "10"))             # neighbours per frame
KNN_SIM_THRESHOLD = float(os.environ.get("KNN_SIM_THRESHOLD", "0.6"))
KNN_BATCH_SIZE = int(os.environ.get("KNN_BATCH_SIZE", "2048"))

# --- Semantic text indexes (step 07) - consumed by backend text_faiss_service --
# Hybrid OCR/ASR search embeds the OCR/ASR text with a sentence model and stores a
# FAISS index + a row-aligned sidecar. Must match backend settings.text_embed_model.
OCR_TEXT_INDEX_FILE = INDEXES_DIR / "ocr_text.index"
OCR_TEXT_IDS_FILE = INDEXES_DIR / "ocr_text_ids.json"      # ["<frame_id>", ...]
ASR_TEXT_INDEX_FILE = INDEXES_DIR / "asr_text.index"
ASR_TEXT_META_FILE = INDEXES_DIR / "asr_text_meta.json"    # [{video_name,seg_idx,...}]
CAPTION_TEXT_INDEX_FILE = INDEXES_DIR / "caption_text.index"
CAPTION_TEXT_IDS_FILE = INDEXES_DIR / "caption_text_ids.json"
TEXT_EMBED_MODEL = os.environ.get("TEXT_EMBED_MODEL", "intfloat/multilingual-e5-base")
TEXT_EMBED_BATCH_SIZE = int(os.environ.get("TEXT_EMBED_BATCH_SIZE", "64"))

# --- Embedding models --------------------------------------------------------
# Every supported backbone. `kind` selects the encoder implementation in
# utils/encoders.py; `dim` is the embedding size (informational - step 03 reads
# the true dim from the vectors, but the backend's embedding_service._DIMS must
# match these). Pick one with MODEL_KEY; outputs are namespaced per model so
# several can coexist:
#     data/features/<MODEL_KEY>/<video>/<frame>.npy
#     data/indexes/<MODEL_KEY>.index
MODEL_REGISTRY = {
    # OpenAI CLIP ViT-L/14-336 - English only, baseline (AIC-HCMC-2025).
    "clip":   {"kind": "clip",   "hf_name": "openai/clip-vit-large-patch14-336", "dim": 768},
    # SigLIP 2 so400m - multilingual, strong; recommended upgrade.
    "siglip": {"kind": "siglip", "hf_name": "google/siglip2-so400m-patch14-384", "dim": 1152},
    # Jina-CLIP v2 - multilingual incl. Vietnamese, Matryoshka 1024-d.
    "jina":   {"kind": "jina",   "hf_name": "jinaai/jina-clip-v2",               "dim": 1024},
    # BEiT-3 large retrieval - needs extra setup (see BEIT3_* below + README).
    "beit3":  {"kind": "beit3",  "hf_name": "beit3_large_patch16_384_retrieval", "dim": 768},
}
MODEL_KEY = os.environ.get("MODEL_KEY", "clip")
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "64"))

# BEiT-3 only - paths to the vendored unilm/beit3 code, checkpoint and tokenizer.
BEIT3_REPO_DIR = os.environ.get("BEIT3_REPO_DIR", str(REPO_ROOT / "results" / "unilm" / "beit3"))
BEIT3_CKPT = os.environ.get("BEIT3_CKPT", str(REPO_ROOT / "results" / "beit3" / "beit3_large_itc_patch16_224.pth"))
BEIT3_SPM = os.environ.get("BEIT3_SPM", str(REPO_ROOT / "results" / "beit3" / "beit3.spm"))


def active_model() -> dict:
    if MODEL_KEY not in MODEL_REGISTRY:
        raise ValueError(f"Unknown MODEL_KEY={MODEL_KEY!r}; choose from {list(MODEL_REGISTRY)}")
    return MODEL_REGISTRY[MODEL_KEY]


def model_features_dir(model_key: str | None = None) -> "Path":
    return FEATURES_DIR / (model_key or MODEL_KEY)


def index_file(model_key: str | None = None) -> "Path":
    return INDEXES_DIR / f"{model_key or MODEL_KEY}.index"


def id_map_file(model_key: str | None = None) -> "Path":
    # Per-model id map: with dedup on (DEDUP_THRESHOLD > 0) each model keeps a
    # different frame subset, so the id_map can no longer be shared. The backend
    # prefers id_map_<model>.json and falls back to the shared id_map.json.
    return INDEXES_DIR / f"id_map_{model_key or MODEL_KEY}.json"


FRAME_SCALE = float(os.environ.get("FRAME_SCALE", "0.5"))    # keyframe downscale
FRAME_EXT = os.environ.get("FRAME_EXT", "jpg")               # keyframe image format

# Step 03 - near-duplicate keyframe filtering (Tran et al., arXiv:2504.08384).
# A frame is dropped from the index when its cosine similarity with the last
# KEPT frame of the same video exceeds this threshold (frames iterated in
# temporal order). 0 disables. Only affects the index, not files on disk.
DEDUP_THRESHOLD = float(os.environ.get("DEDUP_THRESHOLD", "0.9"))

# OCR
OCR_LANGS = os.environ.get("OCR_LANGS", "en,vi").split(",")
OCR_BATCH_SIZE = int(os.environ.get("OCR_BATCH_SIZE", "16"))

# ASR (faster-whisper)
ASR_MODEL_SIZE = os.environ.get("ASR_MODEL_SIZE", "large-v3")
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "vi")


def ensure_dirs() -> None:
    """Create every output directory used by the pipeline."""
    for d in (FRAMES_DIR, model_features_dir(), INDEXES_DIR, METADATA_DIR, OCR_DIR, ASR_DIR):
        d.mkdir(parents=True, exist_ok=True)
