# Backend API Specification
# Ho Chi Minh AI Challenge

> Tài liệu này mô tả toàn bộ API mà frontend đang gọi.  
> Backend chạy tại `http://localhost:8000` (có thể thay đổi qua biến môi trường).

---

## Mục lục

- [Backend API Specification](#backend-api-specification)
- [Ho Chi Minh AI Challenge](#ho-chi-minh-ai-challenge)
  - [Mục lục](#mục-lục)
  - [1. Tổng quan hệ thống](#1-tổng-quan-hệ-thống)
  - [2. Stack công nghệ đề xuất](#2-stack-công-nghệ-đề-xuất)
  - [3. Cấu trúc thư mục đề xuất](#3-cấu-trúc-thư-mục-đề-xuất)
  - [4. Data Models](#4-data-models)
    - [4.1 SearchResult (response cho text / image / ocr)](#41-searchresult-response-cho-text--image--ocr)
    - [4.2 AsrFrame (frame bên trong segment ASR)](#42-asrframe-frame-bên-trong-segment-asr)
    - [4.3 AsrSegment](#43-asrsegment)
    - [4.4 AsrVideoGroup (response cho /search\_asr)](#44-asrvideogroup-response-cho-search_asr)
    - [4.5 TemporalEvent (frame trong kết quả temporal)](#45-temporalevent-frame-trong-kết-quả-temporal)
    - [4.6 TemporalBestSequence](#46-temporalbestsequence)
    - [4.7 TemporalVideoGroup (response cho /search\_temporal)](#47-temporalvideogroup-response-cho-search_temporal)
  - [5. API Endpoints](#5-api-endpoints)
    - [5.1 `POST /search_text`](#51-post-search_text)
    - [5.2 `POST /search_image`](#52-post-search_image)
    - [5.3 `POST /search_ocr`](#53-post-search_ocr)
    - [5.4 `POST /search_asr`](#54-post-search_asr)
    - [5.5 `POST /search_temporal`](#55-post-search_temporal)
    - [5.6 `GET /graph/*` - graph introspection](#56-get-graph--graph-introspection)
    - [5.7 `POST /search_feedback` - relevance feedback](#57-post-search_feedback--relevance-feedback)
    - [5.8 `POST /agent/chat` - conversational search](#58-post-agentchat--conversational-search)
    - [5.9 `POST /agent/qa` - RAG question answering](#59-post-agentqa--rag-question-answering)
    - [5.10 `POST /agent/ask` - một cửa cho cả ba dạng đề](#510-post-agentask--một-cửa-cho-cả-ba-dạng-đề)
  - [6. File Serving (Static Assets)](#6-file-serving-static-assets)
    - [6.1 Frames (ảnh thumbnail)](#61-frames-ảnh-thumbnail)
    - [6.2 Videos](#62-videos)
  - [7. CORS Configuration](#7-cors-configuration)
  - [8. Error Handling](#8-error-handling)
  - [9. Luồng xử lý từng loại search](#9-luồng-xử-lý-từng-loại-search)
  - [10. Ví dụ triển khai với FastAPI](#10-ví-dụ-triển-khai-với-fastapi)
    - [`main.py`](#mainpy)
    - [`models/schemas.py`](#modelsschemaspy)
    - [`routers/search_text.py`](#routerssearch_textpy)
    - [`routers/search_image.py`](#routerssearch_imagepy)
    - [Khởi động server](#khởi-động-server)
  - [Checklist triển khai](#checklist-triển-khai)

---

## 1. Tổng quan hệ thống

Đây là hệ thống **Video Retrieval** (tìm kiếm video theo nội dung) phục vụ cho AIC.  
Người dùng có thể tìm kiếm frame video thông qua 5 chế độ:

| Mode | Mô tả |
|------|-------|
| `text` | Tìm kiếm bằng mô tả văn bản tự nhiên (CLIP/BEiT3 embedding) |
| `image` | Tìm kiếm bằng hình ảnh tải lên (image-to-image similarity) |
| `ocr` | Tìm kiếm text xuất hiện trong frame video |
| `asr` | Tìm kiếm theo lời thoại/phụ đề trong video |
| `temporal` | Tìm kiếm chuỗi sự kiện theo thứ tự thời gian (tối đa 3 sự kiện) |

---

## 2. Stack công nghệ đề xuất

```
Backend Framework : FastAPI (Python 3.10+)
Embedding Models  : CLIP, BEiT3 (tùy cấu hình)
Vector Database   : FAISS hoặc Qdrant hoặc Chroma
OCR Index         : Elasticsearch hoặc SQLite FTS5
ASR Index         : Elasticsearch hoặc SQLite FTS5
Media Storage     : Local filesystem hoặc MinIO/S3
```

**Cài đặt dependencies cơ bản:**

```bash
pip install fastapi uvicorn python-multipart faiss-cpu torch torchvision \
            transformers pillow numpy opencv-python-headless elasticsearch
```

---

## 3. Cấu trúc thư mục đề xuất

```
backend/
├── main.py                     # FastAPI app, CORS, routes
├── config.py                   # Cấu hình đường dẫn, model, ...
├── requirements.txt
│
├── routers/
│   ├── search_text.py
│   ├── search_image.py
│   ├── search_ocr.py
│   ├── search_asr.py
│   └── search_temporal.py
│
├── services/
│   ├── embedding_service.py    # Load & run CLIP/BEiT3
│   ├── faiss_service.py        # Tìm kiếm vector FAISS
│   ├── ocr_service.py          # Tìm kiếm OCR text
│   └── asr_service.py          # Tìm kiếm ASR transcript
│
├── models/
│   └── schemas.py              # Pydantic response models
│
└── data/
    ├── indexes/
    │   ├── beit3.index         # FAISS index
    │   ├── clip.index
    │   └── id_map.json         # mapping index → frame info
    ├── ocr/
    │   └── ocr_data.json       # {frame_id: "text content"}
    ├── asr/
    │   └── asr_data.json       # {video_name: [{start_ms, end_ms, text}]}
    └── metadata/
        └── frames_meta.json    # {frame_id: {video_name, timestamp_ms, fps, ...}}

media/                          # Static files served bởi backend
├── frames/
│   ├── video_L01_V001/
│   │   ├── 000001.webp
│   │   ├── 000002.webp
│   │   └── ...
│   └── ...
└── videos/
    ├── video_L01_V001.mp4
    └── ...
```

---

## 4. Data Models

### 4.1 SearchResult (response cho text / image / ocr)

```json
{
  "id":           "video_L01_V001_000125",
  "score":        0.8734,
  "frame_name":   "000125.webp",
  "video_name":   "video_L01_V001",
  "timestamp_ms": 5000,
  "fps":          25.0,
  "frame_url":    "http://localhost:8000/media/frames/video_L01_V001/000125.webp",
  "video_url":    "http://localhost:8000/media/videos/video_L01_V001.mp4"
}
```

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | string | ID duy nhất của frame |
| `score` | float | Điểm tương đồng (0–1, càng cao càng liên quan) |
| `frame_name` | string | Tên file frame, ví dụ `000125.webp` |
| `video_name` | string | Tên video gốc |
| `timestamp_ms` | integer | Thời điểm frame trong video (milliseconds) |
| `fps` | float | FPS của video (dùng để VideoPlayerModal tính frame index) |
| `frame_url` | string | URL tuyệt đối để tải frame image |
| `video_url` | string | URL tuyệt đối để stream video |

> **Lưu ý:** `fps` là bắt buộc để `VideoPlayerModal` hoạt động đúng (tính `currentFrameIndex`).

---

### 4.2 AsrFrame (frame bên trong segment ASR)

```json
{
  "id":           "video_L01_V001_000125",
  "frame_name":   "000125.webp",
  "frame_url":    "http://localhost:8000/media/frames/video_L01_V001/000125.webp",
  "video_url":    "http://localhost:8000/media/videos/video_L01_V001.mp4",
  "timestamp_ms": 5000,
  "fps":          25.0,
  "score":        0.95
}
```

### 4.3 AsrSegment

```json
{
  "asr_text": "Hôm nay thời tiết rất đẹp",
  "frames": [ /* AsrFrame[] */ ]
}
```

### 4.4 AsrVideoGroup (response cho /search_asr)

```json
{
  "video_name": "video_L01_V001",
  "segments": [ /* AsrSegment[] */ ]
}
```

### 4.5 TemporalEvent (frame trong kết quả temporal)

```json
{
  "id":           "video_L01_V001_000300",
  "event_index":  0,
  "frame_name":   "000300.webp",
  "frame_url":    "http://localhost:8000/media/frames/video_L01_V001/000300.webp",
  "video_url":    "http://localhost:8000/media/videos/video_L01_V001.mp4",
  "timestamp_ms": 12000,
  "fps":          25.0,
  "score":        0.81
}
```

| Field | Type | Mô tả |
|-------|------|-------|
| `event_index` | integer | 0, 1, hoặc 2 - chỉ số sự kiện trong chuỗi temporal |

### 4.6 TemporalBestSequence

```json
{
  "total_score": 2.4513,
  "events": [ /* TemporalEvent[] - mỗi element tương ứng 1 event */ ]
}
```

### 4.7 TemporalVideoGroup (response cho /search_temporal)

```json
{
  "video_name":    "video_L01_V001",
  "best_sequence": { /* TemporalBestSequence */ }
}
```

---

## 5. API Endpoints

### 5.1 `POST /search_text`

Tìm kiếm frame bằng mô tả văn bản tự nhiên (semantic search).

**Query Parameters:**

| Param | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `query` | string | Có | - | Chuỗi mô tả cần tìm |
| `top_k` | integer | Không | 25 | Số kết quả trả về |
| `model` | string | Không | `"siglip"` | Model embedding: `"siglip"`, `"clip"` hoặc `"ensemble"` (trộn điểm nhiều backbone theo `ENSEMBLE_MODELS`) |
| `ocr_keywords` | string | Không | `""` | Text OCR (per-frame). Cách dùng do `text_mode` quyết định |
| `asr_keywords` | string | Không | `""` | Transcript ASR (per-video). Cách dùng do `text_mode` quyết định |
| `caption_keywords` | string | Không | `""` | Caption sinh sẵn (Qwen2.5-VL, tiếng Anh). Gõ tiếng Việt có dấu thì được LLM dịch trước |
| `text_mode` | string | Không | `"filter"` | Ba ô trên chạy kiểu nào - xem **Lọc hay trộn** bên dưới. `"filter"` = cổng AND hậu xử lý; `"fuse"` = mỗi ô thành một kênh retrieval riêng rồi cộng điểm với visual |
| `rerank` | boolean | Không | `true` | Chấm lại top ứng viên bằng BLIP ITM (query–ảnh, cross-attention) |
| `expand` | boolean | Không | `true` | Dịch + mở rộng query thành 4 biến thể tiếng Anh bằng Gemini (cần `GEMINI_API_KEY`; không có key thì dùng query gốc) |
| `objects` | string | Không | `""` | Danh sách nhãn OpenImages cách nhau bằng dấu phẩy (vd `"person, motorcycle"`) - so với object của **cảnh** chứa ứng viên (graph layer, cần `data/graph/graph.json`). Xem `GET /graph/labels` để biết nhãn khả dụng |
| `object_mode` | string | Không | `"boost"` | `"boost"` = cộng điểm theo tỉ lệ nhãn khớp; `"filter"` = chỉ giữ ứng viên có cảnh chứa **đủ mọi** nhãn |
| `scene_keywords` | string | Không | `""` | Keyword cách nhau bằng dấu phẩy, so với **text của cảnh** = OCR các frame trong cảnh + ASR trùng khoảng thời gian cảnh (fuzzy nếu có rapidfuzz). Mịn hơn `ocr_keywords` (per-frame) và `asr_keywords` (per-video) |
| `scene_mode` | string | Không | `"boost"` | `"boost"` = cộng điểm theo tỉ lệ keyword khớp; `"filter"` = chỉ giữ ứng viên có cảnh chứa **đủ mọi** keyword |

**Request:**
```http
POST /search_text?query=người+đang+nấu+ăn&top_k=25&model=siglip
Content-Type: application/json
```
*(Body rỗng - tất cả tham số là query params)*

**Response `200 OK`:**
```json
{
  "results": [
    {
      "id":           "video_L01_V001_000125",
      "score":        0.8734,
      "frame_name":   "000125.webp",
      "video_name":   "video_L01_V001",
      "timestamp_ms": 5000,
      "fps":          25.0,
      "frame_url":    "http://localhost:8000/media/frames/video_L01_V001/000125.webp",
      "video_url":    "http://localhost:8000/media/videos/video_L01_V001.mp4"
    }
    // ... top_k items
  ]
}
```

**Luồng xử lý:**
1. Nếu `expand=true` và có `GEMINI_API_KEY`: Gemini dịch + sinh 4 biến thể tiếng Anh của `query` (biến thể 0 = bản dịch trực tiếp); search song song các biến thể và gộp điểm theo max từng frame
2. Encode query (hoặc từng biến thể) bằng text encoder của model được chọn
3. Tìm `top_k * 4` nearest neighbors trong FAISS index
4. Graph layer (tự bỏ qua nếu chưa build `data/graph/` - bước 08):
   - kNN expansion: hàng xóm similarity của top ứng viên vào pool với điểm `GRAPH_KNN_WEIGHT * cosine * điểm_nguồn`
   - Scene score aggregation: cộng bonus `GRAPH_SCENE_WEIGHT * mean(điểm các ứng viên cùng cảnh)` - như neighbor nhưng theo ranh giới cảnh SceneJSON
   - Nếu `objects` không rỗng: lọc (`filter`) hoặc cộng điểm (`boost`) theo nhãn object của cảnh
   - Nếu `scene_keywords` không rỗng: lọc/cộng điểm theo text của cảnh (OCR + ASR), bonus `GRAPH_SCENE_TEXT_BONUS`
5. Neighbor score aggregation: cộng điểm thưởng cho frame có ứng viên cùng video trong cửa sổ ±`NEIGHBOR_WINDOW_MS` (frame trúng theo cụm đáng tin hơn frame trúng lẻ)
6. Nếu `rerank=true`: chấm lại tối đa `RERANK_CANDIDATES` (mặc định 100) ứng viên đầu bằng BLIP ITM (`VISUAL_RERANK_MODEL`) với **bản dịch tiếng Anh** của query, trộn điểm `final = α*rerank + (1-α)*retrieve`
7. Nếu `ocr_keywords` không rỗng: lọc giữ lại frame có OCR text chứa keyword
8. Nếu `asr_keywords` không rỗng: lọc giữ lại frame thuộc video có ASR chứa keyword

#### Lọc hay trộn (`text_mode`)

Ba ô `ocr_keywords` / `asr_keywords` / `caption_keywords` dùng chung một tham số:

| | `filter` (mặc định) | `fuse` |
| --- | --- | --- |
| vai trò | cổng AND hậu xử lý trên pool visual | kênh retrieval riêng (`search_ocr`, `search_asr`, `search_captions`) |
| điểm cuối | 100% từ visual | Σ điểm max-norm mỗi kênh, đúng cơ chế fan-out của `/agent/chat` |
| recall | trần đúng bằng pool visual | kéo được frame visual trượt hẳn |
| chỗ chạy | `metadata_service.filter_candidates` | `routers/search_text._fuse_text_channels` |

Trọng số kênh visual khi trộn: `SEARCH_FUSE_VISUAL_WEIGHT` (mặc định 1.0).

**Đo thật** - `python backend/scripts/eval_search_text.py`, 10 câu trong
`eval/sotuyen12.json` có manh mối chữ, từ khoá lấy từ chính đề bài
(`eval/search_filters.json`), `model=ensemble`, `top_k=100`, rerank bật:

| nhánh | vid@1 | vid@100 | frm@100 | câu trả rỗng | giây/câu |
| --- | --- | --- | --- | --- | --- |
| không lọc gì | 4 | **10** | **7** | 0 | 10.1 |
| `filter` | **6** | 6 | 3 | **3** | **1.6** |
| `fuse` | 4 | 9 | **7** | 0 | 5.8 |

Đọc số này trước khi đổi mặc định:

- `filter` mạnh nhất ở hạng 1 nhưng **mất hẳn 4/10 câu** (3 câu trả rỗng). Cổng
  AND còn vứt cả frame ĐÚNG trong video đã giữ được: frm@100 chỉ 3/10 - p2-17
  giữ đúng video ở hạng 1 mà không còn frame nào trong tolerance.
- `fuse` giữ recall gần bằng không lọc gì, hơn `filter` 3 câu và kém 2 câu theo
  hạng video (hoà 5).
- **Không nhánh nào thắng "không lọc gì" ở @100.** Ô lọc chỉ đáng gõ khi cụm chữ
  thật sự đặc trưng; từ khoá chung chung hoặc suy diễn sai thì hại cả hai nhánh -
  "kéo co" (chữ không hề có trên slide) đẩy p2-26 từ hạng 49 ra khỏi top-100,
  "THPTQG" đẩy p2-23 từ 12 xuống 69.

Vì vậy mặc định giữ `filter` (nhanh gấp 3, mạnh ở hạng 1); `fuse` là lựa chọn
khi lọc trả rỗng hoặc quá ít kết quả.
9. Trả về `top_k` kết quả đầu

---

### 5.2 `POST /search_image`

Tìm kiếm frame bằng ảnh tải lên (image-to-image similarity).

**Query Parameters:**

| Param | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `top_k` | integer | Không | 25 | Số kết quả trả về |
| `model` | string | Không | `"siglip"` | Model embedding (`"siglip"` \| `"clip"` \| `"ensemble"`) |

**Request:**
```http
POST /search_image?top_k=25&model=siglip
Content-Type: multipart/form-data

image: <binary file>
```

**Form Data:**

| Field | Type | Required | Mô tả |
|-------|------|----------|-------|
| `image` | File | Có | File ảnh (JPEG, PNG, WebP, ...) |

**Response `200 OK`:** Cùng schema với `/search_text`.

```json
{
  "results": [ /* SearchResult[] */ ]
}
```

**Luồng xử lý:**
1. Đọc file ảnh từ form data
2. Encode ảnh thành vector bằng image encoder của model được chọn
3. Tìm kiếm nearest neighbors trong FAISS index
4. Trả về `top_k` kết quả

---

### 5.3 `POST /search_ocr`

Tìm kiếm frame có chứa text OCR khớp với query.

**Query Parameters:**

| Param | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `query` | string | Có | - | Text OCR cần tìm |
| `top_k` | integer | Không | 25 | Số kết quả trả về |
| `model` | string | Không | `"siglip"` | Model (dùng cho re-ranking nếu có) |
| `ocr_keywords` | string | Không | `""` | Từ khóa bổ sung |
| `asr_keywords` | string | Không | `""` | Lọc thêm theo ASR |
| `rerank` | boolean | Không | `true` | Chấm lại top ứng viên bằng cross-encoder (query–văn bản OCR) |

**Request:**
```http
POST /search_ocr?query=COVID-19&top_k=25
Content-Type: application/json
```

**Response `200 OK`:** Cùng schema với `/search_text`.

```json
{
  "results": [ /* SearchResult[] */ ]
}
```

**Luồng xử lý:**
1. Tìm kiếm full-text trong OCR index (Elasticsearch / SQLite FTS5) với `query`
2. Lấy frame IDs từ kết quả OCR, kèm `score` = BM25 score hoặc TF-IDF score
3. Map frame IDs về thông tin đầy đủ (video_name, timestamp_ms, URLs)
4. Trả về `top_k` kết quả sắp xếp theo score giảm dần

---

### 5.4 `POST /search_asr`

Tìm kiếm theo lời thoại / phụ đề trong video.

**Query Parameters:**

| Param | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `query` | string | Có | - | Chuỗi lời thoại cần tìm |
| `asr_filter` | string | Không | `""` | Từ khóa lọc thêm trong ASR |
| `rerank` | boolean | Không | `true` | Chấm lại top segment bằng cross-encoder (query–lời thoại) |

**Request:**
```http
POST /search_asr?query=giá+vàng+tăng+mạnh
Content-Type: application/json
```

**Response `200 OK`:**

```json
{
  "videos": [
    {
      "video_name": "video_L01_V001",
      "segments": [
        {
          "asr_text": "Giá vàng tăng mạnh trong những ngày qua",
          "frames": [
            {
              "id":           "video_L01_V001_000300",
              "frame_name":   "000300.webp",
              "frame_url":    "http://localhost:8000/media/frames/video_L01_V001/000300.webp",
              "video_url":    "http://localhost:8000/media/videos/video_L01_V001.mp4",
              "timestamp_ms": 12000,
              "fps":          25.0,
              "score":        0.95
            }
          ]
        }
      ]
    }
  ]
}
```

**Luồng xử lý:**
1. Tìm kiếm `query` trong ASR transcript index (full-text search)
2. Gom nhóm các segment khớp theo video
3. Với mỗi segment khớp: lấy các frame trong khoảng thời gian `[start_ms, end_ms]` của segment đó
4. Trả về danh sách video, mỗi video chứa các segment và frames tương ứng

---

### 5.5 `POST /search_temporal`

Tìm kiếm chuỗi sự kiện xảy ra theo thứ tự thời gian trong cùng một video (tối đa 3 sự kiện).

**Query Parameters:**

| Param | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `q1` | string | Không | `""` | Mô tả sự kiện 1 |
| `ocr1` | string | Không | `""` | OCR filter cho sự kiện 1 |
| `asr1` | string | Không | `""` | ASR filter cho sự kiện 1 |
| `q2` | string | Không | `""` | Mô tả sự kiện 2 |
| `ocr2` | string | Không | `""` | OCR filter cho sự kiện 2 |
| `asr2` | string | Không | `""` | ASR filter cho sự kiện 2 |
| `q3` | string | Không | `""` | Mô tả sự kiện 3 |
| `ocr3` | string | Không | `""` | OCR filter cho sự kiện 3 |
| `asr3` | string | Không | `""` | ASR filter cho sự kiện 3 |
| `model` | string | Không | `"siglip"` | Model embedding (`"siglip"` \| `"clip"` \| `"ensemble"`) |
| `topk_per_event` | integer | Không | 200 | Số frame candidate cho mỗi event |

> Ít nhất 1 trong `q1`, `q2`, `q3` phải có giá trị.

**Request:**
```http
POST /search_temporal?q1=người+đang+nấu+ăn&q2=mọi+người+ngồi+ăn+cơm&model=siglip&topk_per_event=200
Content-Type: application/json
```

**Response `200 OK`:**

```json
{
  "videos": [
    {
      "video_name": "video_L01_V001",
      "best_sequence": {
        "total_score": 2.4513,
        "events": [
          {
            "id":           "video_L01_V001_000125",
            "event_index":  0,
            "frame_name":   "000125.webp",
            "frame_url":    "http://localhost:8000/media/frames/video_L01_V001/000125.webp",
            "video_url":    "http://localhost:8000/media/videos/video_L01_V001.mp4",
            "timestamp_ms": 5000,
            "fps":          25.0,
            "score":        0.8734
          },
          {
            "id":           "video_L01_V001_000300",
            "event_index":  1,
            "frame_name":   "000300.webp",
            "frame_url":    "http://localhost:8000/media/frames/video_L01_V001/000300.webp",
            "video_url":    "http://localhost:8000/media/videos/video_L01_V001.mp4",
            "timestamp_ms": 12000,
            "fps":          25.0,
            "score":        0.81
          }
        ]
      }
    }
  ]
}
```

**Luồng xử lý:**
1. Với mỗi event có query không rỗng: encode query → tìm top `topk_per_event` frame candidates
2. Áp dụng OCR/ASR filter nếu có
3. **Temporal matching**: Với mỗi video xuất hiện trong candidates của cả 3 events:
   - Tìm tổ hợp frame `(f1, f2, f3)` sao cho `timestamp(f1) < timestamp(f2) < timestamp(f3)`
   - `total_score = score(f1) + score(f2) + score(f3)`
4. Chọn tổ hợp có `total_score` cao nhất cho mỗi video
5. Sắp xếp video theo `total_score` giảm dần, trả về top N video

---

### 5.5b `POST /search_caption`

Tìm theo **caption sinh bởi Qwen2.5-VL** (kaggle step 9 → `data/captions/` +
index step 07). Kênh này vớt được truy vấn mà embedding thị giác trượt (vật thể
lạ, khái niệm trừu tượng). Tham số như `/search_ocr` (`query`, `top_k`,
`ocr_keywords`, `asr_keywords`, `rerank`); scoring hybrid
`CAPTION_SEM_WEIGHT * cosine + CAPTION_EXACT_BONUS * exact` (bonus nhỏ hơn OCR
vì caption là văn bản sinh ra). Chưa build caption thì trả `503`. Đây cũng là
kênh `caption` trong `plan.steps` của `/agent/chat`.

---

### 5.6 `GET /graph/*` - graph introspection

Graph layer `Video → Scene → Frame → Object` build từ dữ liệu sẵn có (SceneJSON,
objects OpenImages, map-keyframes) bằng `data_processing/08_build_graph.py`.
Chưa build thì các endpoint trả `503` (còn search vẫn chạy bình thường, phần
graph tự no-op).

| Endpoint | Trả về |
|----------|--------|
| `GET /graph/labels` | `{"labels": [{"label": "person", "scene_count": 6040}, ...]}` - nhãn dùng được cho param `objects`, xếp theo tần suất |
| `GET /graph/frame/{frame_id}` | `{frame_id, scene_id, scene: {video_name, start_ms, end_ms, frames, objects, ocr, asr}, objects, neighbors: [[frame_id, cosine], ...]}` |
| `GET /graph/scene/{frame_id}` | `SearchResponse` - mọi keyframe của cảnh chứa `frame_id` (xem nguyên cảnh từ 1 kết quả) |

**Ví dụ:**
```http
GET /graph/frame/L21_V001_000000
GET /graph/scene/L22_V008_026534
GET /graph/labels
```

---

### 5.7 `POST /search_feedback` - relevance feedback

Tinh chỉnh kết quả từ các frame người dùng đánh dấu đúng (MemoriEase 3.0, §3.5):
`v = w * encode(query) + (1-w) * mean(vector các frame đã chọn)` với
`w = FEEDBACK_QUERY_WEIGHT` (mặc định 0.5). Vector frame đọc thẳng từ FAISS index
(không encode lại ảnh). Frame đã chọn bị loại khỏi kết quả trả về.

**Request body (JSON):**
```json
{ "frame_ids": ["L21_V003_007366", "L21_V003_007429"],
  "query": "sea turtle eggs on the beach",
  "top_k": 25, "model": "siglip" }
```
`query` rỗng = pooling thuần thị giác. **Response**: `SearchResponse` (như 5.1).

---

### 5.8 `POST /agent/chat` - conversational search

Gộp toàn bộ lịch sử chat thành MỘT structured plan bằng Gemini (auto filter
extraction, MemoriEase 2.0 §3.2) rồi tự thực thi: mô tả thị giác → semantic
search; vật thể → `objects`; chữ trên hình / lời nói → `scene_keywords`;
chuỗi sự kiện ("sau đó…") → `/search_temporal`. Không có `GEMINI_API_KEY`
thì fallback: tin nhắn cuối = query.

**Request body (JSON):**
```json
{ "messages": [
    {"role": "user", "content": "tìm cảnh người chạy xe máy trên phố"},
    {"role": "assistant", "content": "Đã tìm..."},
    {"role": "user", "content": "thêm điều kiện: trên màn hình có chữ 60 giây"}
  ],
  "top_k": 25, "model": "siglip", "rerank": false, "deep": false }
```

**Response `200 OK`:**
```json
{ "reply": "Đã tìm cảnh người chạy xe máy trên phố có chữ 60 giây.",
  "plan": { "mode": "search", "query": "person riding a motorcycle on a street",
            "events": [], "objects": "person, motorcycle",
            "scene_keywords": "60 giây", "react_steps": 0 },
  "results": [ /* SearchResult, mode=search */ ],
  "videos":  [ /* TemporalVideoGroup, mode=temporal */ ],
  "trace":   [ /* các bước ReAct {thought, action}, [] nếu one-shot */ ] }
```

`plan` được trả về để UI hiển thị agent đã tìm gì - người dùng luôn kiểm soát.

**Planning (Plan-and-Execute)**: khi yêu cầu trộn nhiều LOẠI manh mối (cảnh quay
+ chữ trên hình + lời nói), planner sinh `plan.steps` = 2-4 kênh retrieval chạy
**song song** (`visual` → search_text, `ocr` → search OCR semantic, `asr` →
search ASR semantic); điểm mỗi kênh chuẩn hoá theo max rồi cộng theo frame,
sau đó neighbor + scene aggregation gộp bằng chứng các kênh trúng frame khác
nhau của cùng cảnh. Query một manh mối thì `steps=[]` và đi đường one-shot cũ.

**ReAct escalation** (Thought→Action→Observation, Yao et al. 2022): sau one-shot,
nếu kết quả rỗng / top score < `REACT_SCORE_THRESHOLD` (0.3) **hoặc** request đặt
`deep=true`, agent vào vòng ReAct tối đa `REACT_MAX_STEPS` (3) bước với 4 tool:
`search` (sửa query/filter), `graph_labels` (tra nhãn object tồn tại),
`scene_info` (OCR/ASR quanh 1 frame), `view_frames` (nhìn tối đa 4 ảnh keyframe
bằng vision). Observation được nén (top-5 điểm + phân bố video + OCR/ASR cảnh
của top-3); action lặp lại y nguyên bị chặn. Kết quả tốt nhất giữa các vòng được
giữ lại; `trace` trả về để UI hiển thị. Model vòng ReAct: `GEMINI_REACT_MODEL`
(mặc định `gemini-2.5-flash`; one-shot vẫn dùng `GEMINI_MODEL` flash-lite).

---

### 5.9 `POST /agent/qa` - RAG question answering

Trả lời câu hỏi về nội dung video (MemoriEase 3.0 §3.4, thay caption offline
bằng Gemini **vision**): các keyframe ứng viên được gửi dưới dạng **ảnh** kèm
OCR/ASR của cảnh (từ graph) và timestamp; Gemini trả lời dựa trên bằng chứng đó.

**Request body (JSON):**
```json
{ "question": "Ổ trứng rùa được phát hiện ở đảo nào và vào năm nào?",
  "frame_ids": ["L21_V003_007366"],
  "top_k": 6, "model": "siglip" }
```
`frame_ids` bỏ trống → hệ thống tự retrieve từ câu hỏi (qua `search_text` +
query expansion). Tối đa `AGENT_MAX_QA_FRAMES` (mặc định 6) frame/câu hỏi.

**Response `200 OK`:**
```json
{ "answer": "Ổ trứng rùa được phát hiện ở đảo Hòn Câu vào năm 2024.",
  "frames": [ /* SearchResult - frame bằng chứng xếp đầu */ ] }
```

---

### 5.10 `POST /agent/ask` - một cửa cho cả ba dạng đề

Nhận dạng đề (KIS / TRAKE / QA) rồi gọi đúng đường ở trên. **Chỉ gộp lối vào,
không gộp pipeline**: ba dạng khác nhau ở bản chất retrieval (KIS fuse theo
frame + gom neighbor/scene; TRAKE fuse theo từng event rồi ghép chuỗi trong một
video; QA fuse theo VIDEO, luôn bật kênh ASR/OCR và KHÔNG gom neighbor). Đo trên
bộ SOTUYEN2: ép thêm kênh ASR/OCR cho KIS kéo top-5 từ 22/30 xuống 13/30, còn
gom neighbor cho QA đè mất video đúng - nên ép chung một pipeline là hỏng cả hai
đầu.

**Request body (JSON):**
```json
{ "messages": [{"role": "user", "content": "…nguyên văn đề…"}],
  "task_type": "", "frame_ids": null,
  "top_k": 25, "model": "ensemble", "rerank": true, "deep": false }
```

`task_type` (`""` | `"kis"` | `"qa"` | `"trake"`) là dạng **đã biết** từ gói đề
BTC phát - luôn thắng bộ nhận dạng. Để rỗng thì `services/task_classifier` đọc
chính câu đề mà quyết, thuần regex, không tốn thêm lượt LLM:

| dấu hiệu | dạng |
| --- | --- |
| ≥ 2 mục đánh số (`E1:`, `Cảnh 1:`…) hoặc cụm "chuỗi liên tiếp" | `trake` |
| câu cuối kết thúc bằng `?`, có từ để hỏi (gì/nào/bao nhiêu/ở đâu…), hoặc mở đầu bằng yêu cầu ("Đếm số…", "Hãy cho biết…") | `qa` |
| còn lại | `kis` |

Đo bằng `python backend/scripts/eval_task_classifier.py` trên 143 đề mẫu (đã bỏ
trùng) trong `query_example/`: **143/143 đúng**. Luật được chỉnh trên chính tập
này nên con số là cận trên - vì vậy dạng từ bộ đề luôn được ưu tiên, và UI có ô
ép tay.

**Response `200 OK`:**
```json
{ "task_type": "qa", "task_source": "auto", "task_reason": "câu cuối là câu hỏi",
  "num_events": 0,
  "reply": "Cá lóc.", "answer": "Cá lóc.",
  "plan": {}, "results": [ /* SearchResult */ ], "videos": [], "trace": [] }
```

`task_source` = `explicit` (nhãn từ bộ đề) | `auto` (tự nhận dạng); `task_reason`
nói vì sao - UI hiện cả hai để người thi phát hiện ngay khi máy đoán sai.
`answer` chỉ có ở dạng QA. Đề TRAKE mà planner chỉ tách được 1 cảnh sẽ trả về
`task_type: "kis"` kèm lý do trong `task_reason`, vì `/search_temporal` cần ≥ 2
event.

Kiểm định tuyến (không nạp model): `python backend/scripts/ask_smoke.py`.

---

## 6. File Serving (Static Assets)

Backend phải serve trực tiếp các file media để frontend có thể load ảnh và video.

### 6.1 Frames (ảnh thumbnail)

```
GET /media/frames/{video_name}/{frame_name}
```

**Ví dụ:**
```
GET /media/frames/video_L01_V001/000125.webp
```

**Response:** File ảnh `.webp` với `Content-Type: image/webp`

---

### 6.2 Videos

```
GET /media/videos/{video_file}
```

**Ví dụ:**
```
GET /media/videos/video_L01_V001.mp4
```

**Response:** File video `.mp4` với `Content-Type: video/mp4`

> **Yêu cầu:** Phải hỗ trợ **HTTP Range Requests** (`Accept-Ranges: bytes`) để trình duyệt có thể tua video. FastAPI `StaticFiles` tự động hỗ trợ điều này.

**Cấu hình trong FastAPI:**
```python
from fastapi.staticfiles import StaticFiles

app.mount("/media", StaticFiles(directory="media"), name="media")
```

---

## 7. CORS Configuration

Frontend chạy tại `http://localhost:5173` (Vite dev server), cần cấu hình CORS:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev
        "http://localhost:3000",   # CRA dev (nếu dùng)
        "http://localhost:4173",   # Vite preview
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 8. Error Handling

Tất cả lỗi trả về dạng:

```json
{
  "detail": "Mô tả lỗi rõ ràng"
}
```

| HTTP Code | Trường hợp |
|-----------|-----------|
| `400` | Query rỗng, file ảnh không hợp lệ, thiếu tham số bắt buộc |
| `404` | Model không tồn tại, index chưa được load |
| `422` | Validation error (Pydantic / FastAPI tự trả) |
| `500` | Lỗi nội bộ (FAISS, model inference, ...) |

**Ví dụ lỗi 400:**
```json
{
  "detail": "Query cannot be empty"
}
```

---

## 9. Luồng xử lý từng loại search

```
┌─────────────────────────────────────────────────────────────────┐
│                        TEXT SEARCH                              │
│  query (string)                                                 │
│      │                                                          │
│      ▼                                                          │
│  Text Encoder (BEiT3 / CLIP)                                    │
│      │  vector [768-dim or 512-dim]                             │
│      ▼                                                          │
│  FAISS ANN Search  ──── top_k * 3 candidates ──────────────────│
│      │                                                          │
│      ▼                                                          │
│  OCR/ASR post-filter (nếu có keywords)                         │
│      │                                                          │
│      ▼                                                          │
│  Map ID → metadata (video_name, timestamp, urls)               │
│      │                                                          │
│      ▼                                                          │
│  Return top_k SearchResult[]                                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       IMAGE SEARCH                              │
│  image file                                                     │
│      │                                                          │
│      ▼                                                          │
│  Image Encoder (BEiT3 / CLIP)                                   │
│      │  vector                                                  │
│      ▼                                                          │
│  FAISS ANN Search → top_k results → Return SearchResult[]      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        OCR SEARCH                               │
│  query string                                                   │
│      │                                                          │
│      ▼                                                          │
│  Full-text search trong OCR index (BM25/FTS5)                  │
│      │  matched frame IDs                                       │
│      ▼                                                          │
│  Map ID → metadata → Return SearchResult[]                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        ASR SEARCH                               │
│  query string                                                   │
│      │                                                          │
│      ▼                                                          │
│  Full-text search trong ASR transcript index                    │
│      │  matched segments (video_name, start_ms, end_ms, text)  │
│      ▼                                                          │
│  Lấy frames trong khoảng [start_ms, end_ms]                    │
│      │                                                          │
│      ▼                                                          │
│  Group by video → Return AsrVideoGroup[]                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     TEMPORAL SEARCH                             │
│  (q1, q2, q3) + filters                                         │
│      │                                                          │
│      ▼                                                          │
│  Text Encode mỗi query → FAISS search → candidates_i           │
│      │                                                          │
│      ▼                                                          │
│  Group candidates theo video_name                               │
│      │                                                          │
│      ▼                                                          │
│  Temporal matching: tìm (f1, f2, f3) với t1 < t2 < t3          │
│      │  maximize sum of scores                                  │
│      ▼                                                          │
│  Chọn best_sequence cho mỗi video                               │
│      │                                                          │
│      ▼                                                          │
│  Sort by total_score → Return TemporalVideoGroup[]             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10. Ví dụ triển khai với FastAPI

### `main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import search_text, search_image, search_ocr, search_asr, search_temporal

app = FastAPI(title="AIC Video Retrieval API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/media", StaticFiles(directory="media"), name="media")

# Include routers
app.include_router(search_text.router)
app.include_router(search_image.router)
app.include_router(search_ocr.router)
app.include_router(search_asr.router)
app.include_router(search_temporal.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}
```

### `models/schemas.py`

```python
from pydantic import BaseModel
from typing import List, Optional

class SearchResult(BaseModel):
    id: str
    score: float
    frame_name: str
    video_name: str
    timestamp_ms: int
    fps: float
    frame_url: str
    video_url: str

class SearchResponse(BaseModel):
    results: List[SearchResult]

# --- ASR ---
class AsrFrame(BaseModel):
    id: str
    frame_name: str
    frame_url: str
    video_url: str
    timestamp_ms: int
    fps: float
    score: float

class AsrSegment(BaseModel):
    asr_text: str
    frames: List[AsrFrame]

class AsrVideoGroup(BaseModel):
    video_name: str
    segments: List[AsrSegment]

class AsrSearchResponse(BaseModel):
    videos: List[AsrVideoGroup]

# --- Temporal ---
class TemporalEvent(BaseModel):
    id: str
    event_index: int
    frame_name: str
    frame_url: str
    video_url: str
    timestamp_ms: int
    fps: float
    score: float

class TemporalBestSequence(BaseModel):
    total_score: float
    events: List[TemporalEvent]

class TemporalVideoGroup(BaseModel):
    video_name: str
    best_sequence: TemporalBestSequence

class TemporalSearchResponse(BaseModel):
    videos: List[TemporalVideoGroup]
```

### `routers/search_text.py`

```python
from fastapi import APIRouter, HTTPException
from models.schemas import SearchResponse
from services.embedding_service import encode_text
from services.faiss_service import search_index
from services.metadata_service import build_search_results

router = APIRouter()

@router.post("/search_text", response_model=SearchResponse)
async def search_text(
    query: str,
    top_k: int = 25,
    model: str = "beit3",
    ocr_keywords: str = "",
    asr_keywords: str = "",
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    query_vector = encode_text(query, model=model)
    raw_results = search_index(query_vector, top_k=top_k * 3, model=model)
    results = build_search_results(
        raw_results,
        top_k=top_k,
        ocr_filter=ocr_keywords,
        asr_filter=asr_keywords,
    )
    return SearchResponse(results=results)
```

### `routers/search_image.py`

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from models.schemas import SearchResponse
from services.embedding_service import encode_image
from services.faiss_service import search_index
from services.metadata_service import build_search_results
from PIL import Image
import io

router = APIRouter()

@router.post("/search_image", response_model=SearchResponse)
async def search_image(
    image: UploadFile = File(...),
    top_k: int = 25,
    model: str = "beit3",
):
    contents = await image.read()
    pil_image = Image.open(io.BytesIO(contents)).convert("RGB")

    query_vector = encode_image(pil_image, model=model)
    raw_results = search_index(query_vector, top_k=top_k, model=model)
    results = build_search_results(raw_results, top_k=top_k)
    return SearchResponse(results=results)
```

### Khởi động server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI sẽ có tại: `http://localhost:8000/docs`

---

## Checklist triển khai

- [ ] Cài đặt Python 3.10+ và dependencies
- [ ] Chuẩn bị FAISS index cho BEiT3 và CLIP
- [ ] Chuẩn bị `id_map.json` mapping index position → frame info
- [ ] Chuẩn bị OCR data (dạng JSON hoặc Elasticsearch index)
- [ ] Chuẩn bị ASR transcript data (dạng JSON hoặc Elasticsearch index)
- [ ] Chuẩn bị `frames_meta.json` (fps, timestamp_ms cho mỗi frame)
- [ ] Đặt frame images vào `media/frames/{video_name}/`
- [ ] Đặt video files vào `media/videos/`
- [ ] Cấu hình CORS đúng origin của frontend
- [ ] Kiểm tra `GET /health` trả về 200
- [ ] Test từng endpoint bằng Swagger UI tại `/docs`
