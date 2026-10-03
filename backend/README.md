# AIC 2026 - Backend (Video Retrieval API)

FastAPI backend cho hệ thống tìm kiếm video Ho Chi Minh AI Challenge 2026.
Chi tiết API xem tại [BACKEND_API_SPEC.md](../BACKEND_API_SPEC.md).

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Chạy dev server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Cấu trúc code

```
backend/
├── main.py              # Entry point, CORS, include routers
├── config.py            # Settings (env vars): model, device, paths
├── routers/             # 5 endpoints: text / image / ocr / asr / temporal
├── services/            # embedding, faiss, ocr, asr, metadata
├── models/schemas.py    # Pydantic response models
└── data/                # FAISS index + OCR/ASR/metadata JSON   (xem dưới)
```

> **Media** (keyframe `*.webp` + video `*.mp4`) giờ nằm ở **FE**
> (`frontend/public/media/...`) và được Vite serve thẳng tại `/media/*`. BE
> không mount StaticFiles nữa; URL trong response trỏ về `MEDIA_BASE_URL`
> trong `.env`. Khi rerank/agent cần pixel ảnh, `metadata_service.frame_bytes()`
> sẽ HTTP GET từ FE (có LRU cache 256 frame).

## Cấu trúc `data/`

```
data/
├── indexes/
│   ├── siglip.index            # FAISS IndexFlatIP - 54955 vector × 1152-d (cosine)
│   └── id_map_siglip.json      # ["L21_V001_000000", ...] thẳng hàng với row của index
│                               # (đọc id_map_<model>.json, fallback id_map.json)
├── metadata/
│   ├── frames_meta.json        # metadata mỗi keyframe (xem format dưới)
│   ├── keyframe_index.json     # {"<video_name>": ["000000.webp", ...]} - manifest
│   │                           # cho /frame_neighbors (BE không còn đọc disk)
│   └── media-info/
│       └── <video_name>.json   # 873 file: thông tin video (title, watch_url, length...)
├── ocr/
│   └── ocr_data.json           # { "<frame_id>": "text OCR" }       (hiện {} rỗng)
└── asr/
    └── asr_data.json           # { "<video_name>": [ {start_ms,end_ms,text} ] }  (hiện {} rỗng)
```

**`frames_meta.json`** - key là `frame_id`:

```json
{
  "L21_V001_000000": {
    "video_name": "L21_V001",
    "frame_name": "000000.webp",
    "timestamp_ms": 0,
    "fps": 30.0
  }
}
```

**`media-info/<video_name>.json`** - dùng cho `video_url` khi không có video local:

```json
{
  "title": "60 Giây Sáng - ...",
  "watch_url": "https://youtube.com/watch?v=Rzpw5WR7nAY",
  "length": 1262,
  "thumbnail_url": "https://i.ytimg.com/vi/.../sddefault.jpg",
  "author": "...", "channel_url": "...", "publish_date": "01/08/2024", "keywords": [...]
}
```

## Cấu trúc `frontend/public/media/`  (FE serve tại `/media/*`)

Media do **frontend** nắm giữ, BE build URL qua `MEDIA_BASE_URL`:

```
frontend/public/media/
├── frames/
│   └── Keyframes/
│       └── <batch>/                 # L21, L22, ...  (= token đầu của video_name)
│           └── <video_name>/        # L21_V001, L21_V012, ...
│               └── <idx>.webp       # 000000.webp, 012564.webp  (idx = 6 chữ số)
└── videos/                          # (TUỲ CHỌN) video local
    └── <video_name>.mp4             # nếu thiếu -> backend dùng watch_url ở media-info
```

## Quy ước khóa & URL

| Khái niệm   | Dạng                                   | Ví dụ |
|-------------|----------------------------------------|-------|
| `frame_id`  | `<video_name>_<idx:06d>`               | `L21_V001_000000` |
| `video_name`| `<batch>_V<nnn>`                       | `L21_V001` |
| `batch`     | token đầu của `video_name`             | `L21` |
| `frame_url` | `/media/frames/Keyframes/<batch>/<video_name>/<idx>.webp` | |
| `video_url` | mp4 local nếu có, **else** `watch_url` từ `media-info` | |

> `frame_id`, row của `siglip.index`, và `id_map_siglip.json` phải **thẳng hàng** với nhau.
> Toàn bộ artifact này sinh ra ở `data_processing` (Step 4: features → Step 5: index).
>
> `data/metadata/keyframe_index.json` được sinh bởi step 03b
> (`python data_processing/03b_build_keyframe_index.py`). Nếu keyframe nằm ở
> đường dẫn khác (vd FE thật sự deploy trên CDN, không phải `frontend/public/media`),
> truyền `--frames-root <path>` cho step 03b.

## Cấu hình quan trọng (`.env`)

| Biến            | Giá trị                      | Ý nghĩa |
|-----------------|------------------------------|---------|
| `MEDIA_BASE_URL`| `http://localhost:5173`      | URL FE serve static media. Dev: Vite. Prod: CDN/host tĩnh. |
| `DEFAULT_MODEL` | `siglip` \| `jina` \| `clip` | Model encode mặc định (phải khớp `<model>.index`) |
| `ENSEMBLE_MODELS` | `"siglip:0.6,clip:0.4"` | Trọng số fusion khi gọi `model=ensemble`; model thiếu index/encoder tự bị bỏ qua |
| `EMBED_DEVICE`  | `auto` \| `cuda` \| `cpu`    | Thiết bị encode query |
| `EMBED_DTYPE`   | `auto` \| `fp16` \| `fp32`   | `auto` = fp16 trên cuda, fp32 trên cpu |
| `TEXT_RERANK_MODEL` | HF id \| `none` | Cross-encoder chấm lại OCR/ASR (mặc định `BAAI/bge-reranker-v2-m3`, ~2.2GB tải lần đầu). Nhẹ hơn: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` |
| `VISUAL_RERANK_MODEL` | HF id \| `none` | ITM chấm lại ảnh cho `/search_text` (mặc định `Salesforce/blip2-itm-vit-g`; nhận cả checkpoint BLIP đời 1 như `Salesforce/blip-itm-large-coco`) |
| `RERANK_CANDIDATES` | int (100) | Số ứng viên đầu bảng được rerank |
| `TEXT_RERANK_ALPHA` / `VISUAL_RERANK_ALPHA` | 0..1 (0.7) | Trọng số trộn: `final = α*rerank + (1-α)*retrieve` |
| `GEMINI_API_KEY` | string | Key Gemini trực tiếp (free tại aistudio.google.com). Rỗng = tắt. Với `LLM_PROVIDER=openai_first` đây là **lưới đỡ** khi OpenRouter hỏng |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model Gemini cho expansion/planner |
| `LLM_PROVIDER` | `openai_first` | `auto` = Gemini trước · `openai_first` = OpenRouter trước, Gemini đỡ · `gemini`/`openai` = ép cứng một bên, không có đường lui |
| | | Đổi được ngay trong **Cài đặt ⚙ → Provider LLM** mà không restart backend (`POST /agent/llm_config`, chỉ nằm trong RAM) |
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | Bất kỳ endpoint nói chuẩn `/chat/completions` (OpenRouter, Groq, Ollama tự dựng) |
| `OPENAI_API_KEY` | string | Key OpenRouter (`sk-or-v1-...`), lấy ở [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) |
| `OPENAI_MODEL` | `google/gemini-3.5-flash-lite` | Model cho `expand` + `plan`. **Đừng dùng `openai/gpt-5.6-*`**: không hỗ trợ `temperature`, mà hai bước này gọi ở 0.0 |
| `OPENAI_REACT_MODEL` / `OPENAI_QA_MODEL` | `google/gemini-3.7-flash` | Model riêng cho ReAct và QA; rỗng = dùng `OPENAI_MODEL`. QA **bắt buộc** vision (tới 12 keyframe/lượt) |
| `ALLOW_RUNTIME_LLM_KEY` | `true` | Cho phép đổi key Gemini (`/agent/llm_key`) và provider/model/endpoint OpenAI (`/agent/llm_config`) từ giao diện. `false` = khoá cả hai, dùng khi backend nằm sau tunnel công khai |
| `OPENAI_REASONING_{EXPAND,PLAN,REACT,QA}` | `none`/`minimal`/`medium`/`medium` | Ngân sách thinking. `expand=none` là quan trọng: bước này chắn ngang mọi câu search, để thinking bật là mỗi lượt chờ thêm hàng chục giây |
| `OPENAI_JSON_MODE` | `auto` | `auto` = gửi `response_format: json_object`, endpoint từ chối thì tự gỡ và nhớ. Thiếu nó, model trả kèm câu dẫn → planner rơi fallback lặng lẽ |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` / `LLM_RETRY_BACKOFF_S` | 120 / 3 / 15 | Dùng chung cho cả hai provider; backoff tuyến tính (lần n chờ n×backoff giây) |
| `NEIGHBOR_WEIGHT` | float (0.5) | Neighbor score aggregation cho text/image search; 0 = tắt |
| `NEIGHBOR_WINDOW_MS` | int (10000) | Cửa sổ thời gian tính hàng xóm cùng video |
| `TEMPORAL_DECAY_ALPHA` | float (0.01) | Suy giảm mũ theo giây cho temporal search: `Σ sᵢ·e^(−α·Δtᵢ)` |
| `TEMPORAL_BEAM_WIDTH` | int (8) | Độ rộng beam search khi ghép chuỗi sự kiện |

> GPU nhỏ (vd GTX 1650 4GB) chỉ chạy được `siglip` ở **fp16**; fp32 cần GPU ≥ ~6GB.
> Nếu bật đủ SigLIP + E5 + 2 reranker trên 4GB VRAM sẽ khá sát trần - khi OOM,
> rerank tự bỏ qua (giữ thứ tự retrieve) hoặc đặt `TEXT_RERANK_MODEL=none` /
> `VISUAL_RERANK_MODEL=none` để tắt hẳn. Mọi endpoint cũng nhận `rerank=false` theo từng request.
