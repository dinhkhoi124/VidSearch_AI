# HCM-AIC-2026 - Data Processing

Turns raw competition videos into everything the `backend/` needs to serve
search.

There are two interchangeable ways to run it:

- **Local scripts** (`*.py`, this folder) - one resumable script per stage, writes
  straight into `backend/{media,data}`. Best when you have a local GPU.
- **Kaggle notebooks** (`kaggle/`) - the same stages split into notebooks so each
  GPU/CPU step fits Kaggle limits and passes its output as a dataset to the next.
  Best when you process on Kaggle. See [kaggle/](kaggle/) and the "Kaggle pipeline"
  section below.

Both produce the **same** flat `frame_id` / `frames_meta.json` / `id_map.json`
contract, so the backend is agnostic to which you used.

## Pipeline (local scripts)

| Stage | Script | Output | Consumed by |
|-------|--------|--------|-------------|
| 01 | `01_extract_keyframes.py` (TransNetV2) | `media/frames/Keyframes/<batch>/<video>/<frame>.jpg`, `data/metadata/frames_meta.json` | static mount + `metadata_service` |
| 01b | `01b_keyframes_from_map.py` (official CSVs) | same as 01 | - |
| 02 | `02_extract_features.py` (clip/siglip/jina/beit3) | `data/features/<model>/<video>/<frame>.npy` | step 03 |
| 03 | `03_build_faiss_index.py` | `data/indexes/<model>.index`, `data/indexes/id_map.json` | `faiss_service` |
| 04 | `04_extract_ocr.py` (EasyOCR) | `data/ocr/ocr_data.json` | `ocr_service` |
| 05 | `05_extract_asr.py` (faster-whisper) | `data/asr/asr_data.json` | `asr_service` |
| 07 | `07_build_text_indexes.py` (E5) | `data/indexes/{ocr,asr,caption}_text.index` + sidecar | `text_faiss_service` |
| 08 | `08_build_graph.py` (`--knn` tuỳ chọn) | `data/graph/graph.json`, `data/graph/knn_<model>.json` | `graph_service` |

(All output paths are relative to `backend/`.)

---

## Data contract - output JSON / files

This is the **single source of truth** for what each stage writes and how the
backend reads it back. Every file is keyed so the pieces join together via one
identifier - the `frame_id`.

### Identifiers

| Name | Example | Definition |
|------|---------|------------|
| `video_name` | `L21_V001` | mp4 basename. Leading token (`L21`) is the **batch**. |
| `frame_name` | `000080.jpg` | zero-padded frame index + extension (`.jpg` local, `.webp` Kaggle). |
| `frame_id` | `L21_V001_000080` | `<video_name>_<index>` - the **join key** across every file below. The backend recovers `video_name` via `frame_id.rsplit("_", 1)`, so the trailing segment must stay purely numeric. |

### 1. `data/metadata/frames_meta.json` - the hub

Flat dict, **key = `frame_id`**. Every other artifact is joined back to a video /
timestamp through this file, so it must exist for any search to return metadata.

```json
{
  "L21_V001_000000": {
    "video_name": "L21_V001",
    "frame_name": "000000.jpg",
    "timestamp_ms": 0,
    "fps": 30.0
  },
  "L21_V001_000004": {
    "video_name": "L21_V001",
    "frame_name": "000004.jpg",
    "timestamp_ms": 133,
    "fps": 30.0
  }
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `video_name` | str | source video |
| `frame_name` | str | image filename on disk (matters: `.jpg` vs `.webp`) |
| `timestamp_ms` | int | position of the frame in the video, in milliseconds |
| `fps` | float | source video frame rate (used to convert index ↔ time) |

### 2. `data/features/<model>/<video>/<frame>.npy` - embeddings

One `float32` vector **per keyframe**, L2-normalised, in the model's space
(`clip` 768, `siglip` 1152, `jina` 1024, `beit3` 768). Namespaced per model so
several backbones coexist. These are consumed only by step 03 and never served
directly.

### 3. `data/indexes/<model>.index` + `data/indexes/id_map.json`

- `<model>.index` - a FAISS `IndexFlatIP` (inner product over L2-normed vectors =
  cosine). Row `i` is the embedding of `id_map[i]`.
- `id_map.json` - a **flat array**, position-aligned to the index rows:

```json
["L21_V001_000000", "L21_V001_000004", "L21_V001_000008", "..."]
```

The id map is the same across models (same frames), so it can be shared. The
backend loads `id_map_<model>.json` if present, otherwise falls back to
`id_map.json`.

### 4. `data/ocr/ocr_data.json` - text burned into frames

Flat dict, **key = `frame_id`**, value = the OCR text read off that keyframe
(empty string when nothing was detected).

```json
{
  "L21_V001_000000": "BẢN TIN THỜI SỰ 18H",
  "L21_V001_000004": "HÀ NỘI VTV1",
  "L21_V003_000151": ""
}
```

### 5. `data/asr/asr_data.json` - speech transcript

Dict **key = `video_name`**, value = a list of spoken segments with millisecond
time bounds. Unlike OCR, ASR is **per video, not per frame** - frames are matched
to a segment later, by timestamp.

```json
{
  "L21_V001": [
    { "start_ms": 0,    "end_ms": 5000, "text": "Kính chào quý vị" },
    { "start_ms": 5000, "end_ms": 9200, "text": "đang theo dõi bản tin" }
  ],
  "L21_V003": [
    { "start_ms": 1200, "end_ms": 4800, "text": "..." }
  ]
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `start_ms` / `end_ms` | int | segment time bounds in the video (ms) |
| `text` | str | transcribed speech for that segment |

---

### 6. `data/graph/graph.json` (+ `knn_<model>.json`) - graph layer

Step 08 builds a heterogeneous graph **Video → Scene → Frame → Object** purely
from data that already exists - SceneJSON shot boundaries, official OpenImages
detections keyed via map-keyframes, and `frames_meta.json`. No model inference.

```json
{
  "version": 1,
  "scenes":        { "L21_V001:0": { "video_name": "L21_V001", "start_ms": 0,
                                     "end_ms": 266, "frames": ["L21_V001_000000"],
                                     "objects": { "Lantern": 0.7967 },
                                     "ocr": "06,30,41 79D giây",
                                     "asr": "Chào mừng quý vị ..." } },
  "frame_scene":   { "L21_V001_000000": "L21_V001:0" },
  "frame_objects": { "L21_V001_000000": { "Lantern": 0.7967 } },
  "object_scenes": { "lantern": ["L21_V001:0"] }
}
```

Object sources, merged per scene/frame (a missing source is simply skipped):

- **official** `objects-aic25-b1` detections, joined via the map-keyframes CSVs
  (only covers the ~300 official keyframes per video);
- **custom** `data/objects/objects_data.json` = `{frame_id: {label: score}}`
  from `kaggle/08_extract-objects.ipynb` - same OpenImages label space, but over
  ALL of our extracted keyframes.

Scene ids are `<video_name>:<k>`. Videos missing from `SCENE_JSON_DIR` fall back
to splitting at keyframe gaps > `SCENE_FALLBACK_GAP_MS`. With `--knn` the script
also self-searches the flat FAISS index and writes similarity edges
`{frame_id: [[neighbour_id, cosine], ...]}` (top `KNN_K`, cosine ≥
`KNN_SIM_THRESHOLD`) to `data/graph/knn_<MODEL_KEY>.json`.

The backend's `graph_service` uses this for scene-aware score aggregation, the
`objects` filter/boost on `/search_text`, kNN candidate expansion and the
`GET /graph/*` endpoints. Missing files simply disable those features.

---

## Search API responses

How the backend turns the files above into HTTP responses. Endpoints live in
`backend/routers/`; the response shapes are defined in `backend/models/schemas.py`.

### Shared building blocks

- `frame_url` → `"{base}/media/frames/Keyframes/{batch}/{video_name}/{frame_name}"`
- `video_url` → local `"{base}/media/videos/{video_name}.mp4"`, else the YouTube
  `watch_url` from `data/metadata/media-info/<video_name>.json`.
- `score` → higher = better; meaning depends on the endpoint (cosine for
  vector search, keyword frequency for OCR/ASR).

### `POST /search_text`, `/search_image`, `/search_ocr` → `SearchResponse`

A **flat list** of frames. Each item is one keyframe with its metadata and URLs.

```json
{
  "results": [
    {
      "id": "L21_V001_000000",
      "score": 0.83,
      "frame_name": "000000.jpg",
      "video_name": "L21_V001",
      "timestamp_ms": 0,
      "fps": 30.0,
      "frame_url": "http://.../media/frames/Keyframes/L21/L21_V001/000000.jpg",
      "video_url": "http://.../media/videos/L21_V001.mp4"
    }
  ]
}
```

How each endpoint fills it:

- **text / image** - embed the query (or image) → FAISS search → row ids via
  `id_map` → metadata via `frames_meta.json`.
- **ocr** - substring match over `ocr_data.json` (score = keyword frequency ÷
  word count) → metadata via `frames_meta.json`.

> OCR & ASR also work as **post-filters** on text/image results: pass
> `ocr_keywords` / `asr_keywords` and only frames whose OCR text (resp. whose
> video's ASR transcript) contains the keyword are kept.

### `POST /search_asr` → `AsrSearchResponse`

Nested **video → segment → frames**, because a transcript hit is a time span, not
a single frame. For every matching segment, all keyframes whose `timestamp_ms`
falls inside `[start_ms, end_ms]` are attached.

```json
{
  "videos": [
    {
      "video_name": "L21_V001",
      "segments": [
        {
          "asr_text": "đang theo dõi bản tin",
          "frames": [
            {
              "id": "L21_V001_000150",
              "frame_name": "000150.jpg",
              "frame_url": "http://.../media/frames/Keyframes/L21/L21_V001/000150.jpg",
              "video_url": "http://.../media/videos/L21_V001.mp4",
              "timestamp_ms": 5000,
              "fps": 30.0,
              "score": 0.20
            }
          ]
        }
      ]
    }
  ]
}
```

### `POST /search_temporal` → `TemporalSearchResponse`

Same idea as ASR but for a multi-event text query: per video it returns the
best-scoring **ordered sequence** of frames (`best_sequence.events`, each with an
`event_index`). See `schemas.py` for the full shape.

### OCR vs ASR at a glance

| | OCR | ASR |
|---|---|---|
| Unit | one keyframe | one video (time segments) |
| JSON key | `frame_id` | `video_name` |
| Frame linkage | direct, via `frame_id` | indirect, via timestamp → `frames_in_range` |
| Response | flat `SearchResponse` | nested `AsrSearchResponse` |

---

## Setup

```bash
cd HCM-AIC-2026/data_processing
pip install -r requirements.txt
# For step 01 only: install TensorFlow + TransNetV2 weights.
# See ../../AIC-HCMC-2025/data_processing/transnetv2_setup.md
# Step 04 needs easyocr; step 05 needs faster-whisper + ffmpeg on PATH.
```

## Run

Run from this directory (so `config` / `utils` import correctly):

```bash
python run_all.py                 # full pipeline (TransNetV2 keyframes)
python run_all.py --from-map      # use official map-keyframes CSVs instead
python run_all.py --skip ocr asr  # skip stages

# or run any stage on its own:
python 01_extract_keyframes.py
python 02_extract_features.py
python 03_build_faiss_index.py
python 04_extract_ocr.py
python 05_extract_asr.py

# pick the embedding backbone (default clip) - see "Embedding models":
MODEL_KEY=siglip python run_all.py --skip keyframes ocr asr   # features + faiss only
```

Every stage is **resumable** - already-produced frames/features/entries are
skipped, so you can stop and restart or add new videos and re-run.

## Configuration

All paths and model choices live in `config.py` and are overridable via env vars,
e.g.:

```bash
RAW_VIDEOS_GLOB="/data/videos/**/*.mp4" \
MODEL_KEY="siglip" \
ASR_MODEL_SIZE="medium" \
python run_all.py
```

Defaults assume the repo layout where the source videos live under
`backend/media/videos/<batch>/video/*.mp4` and outputs are written straight into
`HCM-AIC-2026/backend/{media,data}`.

## Embedding models

Steps 02 + 03 are backbone-agnostic. Choose one with `MODEL_KEY`; each model's
features and index are namespaced (`data/features/<key>/…`, `data/indexes/<key>.index`)
so several can coexist and be A/B-tested. All encoders live in
[utils/encoders.py](utils/encoders.py) and expose the same `encode_image` /
`encode_text` interface (image & text land in the same cosine space).

| `MODEL_KEY` | Backbone | Dim | Vietnamese | Notes |
|-------------|----------|-----|-----------|-------|
| `clip` (default) | `openai/clip-vit-large-patch14-336` | 768 | ❌ English |
| `siglip` | `google/siglip2-so400m-patch14-384` | 1152 | ✅ multilingual | **recommended upgrade**, plug-and-play |
| `jina` | `jinaai/jina-clip-v2` | 1024 | ✅ incl. Vietnamese | `trust_remote_code`; query text uses task `retrieval.query` |
| `beit3` | `beit3_large_patch16_384_retrieval` | 768 | partial | needs manual setup (below) |

```bash
MODEL_KEY=siglip python 02_extract_features.py   # -> data/features/siglip/...
MODEL_KEY=siglip python 03_build_faiss_index.py  # -> data/indexes/siglip.index
```

**BEiT-3 setup** (only if `MODEL_KEY=beit3`):
```bash
git clone https://github.com/microsoft/unilm   # BEIT3_REPO_DIR=<unilm>/beit3
# download a retrieval checkpoint + tokenizer:
#   beit3_large_itc_patch16_224.pth   -> BEIT3_CKPT
#   beit3.spm                         -> BEIT3_SPM
pip install torchscale
```

> **Two things must match the index you build:**
> 1. **Query encoder** - the backend's `embedding_service.encode_text` must use the
>    *same* model. The easiest path is to import `utils/encoders.py` there and call
>    `get_encoder(model).encode_text(query)`.
> 2. **Backend `_DIMS`** in `embedding_service.py` must list the model's dim
>    (e.g. `siglip: 1152`), and you must call the API with `model=<MODEL_KEY>`
>    (so `faiss_service` loads `data/indexes/<MODEL_KEY>.index`).

## Kaggle pipeline (`kaggle/`)

Same stages, as five notebooks chained via Kaggle datasets (each notebook's output
becomes the next one's input dataset). Edit the path constants at the top of each
notebook to your dataset names.

| # | Notebook | HW | Output | = local stage |
|---|----------|----|--------|---------------|
| 1 | `keyframes-extract-transnet2.ipynb` | GPU | `SceneJSON/<batch>/<video_id>.json` | 01 (shots) |
| 2 | `cut-frame-video-aicaic.ipynb` | CPU | `Keyframes/<video_name>/<idx>.jpg` + `frames_meta.json` | 01 (frames + meta) |
| 3 | `keyframe-extra-reduced.ipynb` | CPU | `Keyframes/<video_name>/<idx>.webp` (downscaled) | - |
| 4 | `infer-openai-clip.ipynb` | GPU | `clip-features/<MODEL_KEY>/<video_name>/<idx>.npy` | 02 |
| 5 | `create-bin.ipynb` | CPU | `<MODEL_KEY>.index` + `id_map.json` | 03 |
| 6 | `06_extract-ocr.ipynb` | GPU | `OCR/<video_name>.json` → `ocr_data.json` | 04 |
| 7 | `07_extract-asr.ipynb` | GPU | `ASR/<video_name>.json` → `asr_data.json` | 05 |
| 8 | `08_extract-objects.ipynb` | GPU | `objects/<video_name>.json` → `objects_data.json` | 08 (input) |
| 9 | `09_extract-ocr-caption-qwen.ipynb` (Qwen2.5-VL, OCR + caption) | GPU | `ocr_caption/<video>.json` → `ocr_data.json` (thay step 6) + `caption_data.json` | 04 + 07 (input) |
| 10 | `10_extract-ocr-qwen.ipynb` (Qwen2.5-VL, OCR only) | GPU | `OCR/<video>.json` → `ocr_data.json` (drop-in thay step 6) | 04 (replacement) |

Notebooks 4–5 have a `MODEL_KEY` switch at the top (`clip` / `siglip` / `jina`),
matching the local pipeline. Set the same value in both. (BEiT-3 needs the unilm
repo + checkpoint, so run it via the local `02_extract_features.py` instead.)

Then copy the artifacts into the backend (see the last cell of `create-bin.ipynb`):

```text
<MODEL_KEY>.index -> backend/data/indexes/<MODEL_KEY>.index
id_map.json       -> backend/data/indexes/id_map.json
frames_meta.json  -> backend/data/metadata/frames_meta.json
Keyframes/*       -> backend/media/frames/
```

Notes / fixes applied vs. the original notebooks:
- **Flat layout** `Keyframes/<video_name>/<idx>.{jpg,webp}` (was nested
  `L<>_extra/V<>/`), so `frame_id = <video_name>_<idx>` matches the backend.
- **`frames_meta.json`** is now generated (Step 2) with real `fps`/`timestamp_ms`.
- **`id_map.json`** is now generated (Step 5); without it the backend cannot map a
  FAISS row back to a frame.
- **Image features** use `get_image_features()` (projected, comparable to the text
  encoder) instead of `vision_model.pooler_output` (un-projected, wrong dim), and
  the notebook is now **multi-model** (`clip` / `siglip` / `jina`).
- The Kaggle path serves `.webp` keyframes; the local scripts serve `.jpg`. Each
  writes its own `frames_meta.json` with the correct extension, so either is fine -
  just don't mix outputs from both into the same backend instance.
