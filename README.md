# HCM-AIC-2026 - Hệ thống truy vấn video

Hệ thống tìm kiếm keyframe/video cho **Ho Chi Minh AI Challenge 2026**.

- **Backend**: FastAPI + FAISS + MetaCLIP 2 / SigLIP 2 (text · image · OCR · ASR · caption · temporal search) + tác tử hội thoại chạy trên LLM.
- **Frontend**: React 19 + Vite + TailwindCSS, có phòng thi chung 5 người qua WebSocket.

> Chi tiết API: [BACKEND_API_SPEC.md](BACKEND_API_SPEC.md) · Luồng xử lý: [pipeline.md](pipeline.md) · Backend: [backend/README.md](backend/README.md) · Vận hành lúc thi: [docs/VAN_HANH.md](docs/VAN_HANH.md)

---

## 0. Dữ liệu và mô hình đang dùng (bản chốt)

Đây là cấu hình thật đang chạy, không phải mặc định lịch sử của repo. Kiểm bằng `backend/.env` và `ls backend/data/indexes`.

| | |
|---|---|
| Kho keyframe | **244.928** ảnh `.webp`, **873** video, batch **L21 → L30** (~11GB, nằm ở `frontend/public/media`) |
| Backbone thị giác đang dùng | **`metaclip2`** = `facebook/metaclip-2-worldwide-huge-378` (1024-d) |
| Chỉ mục chính | `metaclip2.index` - FAISS `IndexFlatIP`, 244.928 × 1024 (~1,0GB) + `id_map_metaclip2.json` |
| Backbone đã build index nhưng KHÔNG bật | `siglip` (`google/siglip2-so400m-patch14-384`, 1152-d), `siglip512` (`google/siglip2-so400m-patch16-512`, 1152-d), `metaclip` (`facebook/metaclip-h14-fullcc2.5b`, 1024-d) |
| Embedding text (OCR/ASR/caption) | `intfloat/multilingual-e5-base` → `ocr_text.index`, `asr_text.index`, `caption_text.index` |
| Caption | **`microsoft/Florence-2-large`** - 244.928 caption tiếng Anh (`09b_caption-florence2.ipynb`) |
| OCR | **Qwen2.5-VL-Instruct** (thay EasyOCR ở bản đầu) - 231.687 frame có chữ |
| Object detection | **`yolo11x.pt`** (Ultralytics, `08_extract-objects.ipynb`) → `objects/objects_data.json`; kèm detection chính thức `objects-aic25-b1` của BTC |
| ASR | **faster-whisper `large-v3`** |
| Rerank | text: `BAAI/bge-reranker-v2-m3` · visual: `Salesforce/blip-itm-large-coco` |
| LLM | OpenRouter (`LLM_PROVIDER=openai_first`), Gemini làm lưới đỡ |

**Model cũ trong tài liệu đời đầu (`siglip` mặc định, ensemble `siglip:0.6,clip:0.4`, `jina`) đã bị thay.** `clip` và `jina` không còn được build index; `ENSEMBLE_MODELS` chốt ở `metaclip2:1.0` vì trộn thêm backbone kéo `@1` xuống trên bộ đo 55 câu (mục 10).

---

## 1. Yêu cầu môi trường

| Thành phần | Phiên bản đề nghị |
|------------|-------------------|
| Python     | 3.10 – 3.13 |
| Node.js    | ≥ 18 (kèm npm) |
| Git        | mới nhất |
| GPU (tuỳ chọn) | NVIDIA + CUDA. `metaclip2` là backbone cỡ huge - chạy `fp16`; máy VRAM nhỏ nên tắt reranker (`WARMUP_RERANKERS=false`, `VISUAL_RERANK_MODEL=none`) hoặc đổi `EMBED_DEVICE=cpu` (chậm nhưng luôn chạy) |

Backend nặng về ML (torch, faiss, transformers, sentence-transformers) nên khuyến nghị **conda** hoặc **venv** riêng.

---

## 2. Clone repo

```bash
git clone git@github.com:nlnamanh/HCM-AIC-2026.git
cd HCM-AIC-2026
```

---

## 3. Tải dữ liệu (BẮT BUỘC)

Toàn bộ FAISS index, metadata, keyframe **không** nằm trong git (xem [backend/.gitignore](backend/.gitignore)).

**Dataset**: <https://drive.google.com/drive/folders/1rlenfk0DVuxlm9dA1YDCucd2yrIqu8-Q?usp=sharing>

Giải nén ra 2 thư mục gốc: `data/` → `backend/data/`, `media/` → `frontend/public/media/`.

### Cách A - Kaggle CLI (khuyến nghị)

```bash
pip install kaggle
mkdir -p ~/.kaggle && mv ~/Downloads/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json

cd backend
kaggle datasets download -d nguynlngnamanh/data-media --unzip -p .

# Keyframe do FRONTEND phục vụ, không phải backend. Cùng ổ đĩa nên đây là đổi
# tên, không copy 11GB.
mv media ../frontend/public/media
cd ..
```

### Cách B - tải thủ công qua trình duyệt

Giải nén, đặt `data/` **trực tiếp** trong `backend/`, `media/` vào `frontend/public/`.

### Cấu trúc mong đợi

```text
backend/data/
├── indexes/
│   ├── metaclip2.index          # ĐANG DÙNG - 244.928 × 1024, IndexFlatIP
│   ├── id_map_metaclip2.json    # 244.928 frame_id, thẳng hàng với row của index
│   ├── siglip.index · siglip512.index · metaclip.index      # dự phòng, không bắt buộc
│   ├── ocr_text.index    + ocr_text_ids.json
│   ├── asr_text.index    + asr_text_meta.json
│   └── caption_text.index + caption_text_ids.json           # 243.089 caption
├── metadata/
│   ├── frames_meta.json         # 244.928 keyframe: video_name, timestamp_ms, fps
│   ├── keyframe_index.json      # manifest <video> -> [file ảnh] cho /frame_neighbors
│   └── media-info/<video>.json  # 873 file: title, watch_url, length…
├── ocr/ocr_data.json            # OCR theo frame_id (231.687 frame có chữ)
├── asr/asr_data.json            # faster-whisper large-v3 theo video
├── captions/caption_data.json   # caption Florence-2-large theo frame_id (244.928)
├── objects/objects_data.json    # detection yolo11x theo frame
├── objects-aic25-b1/            # detection chính thức của BTC
├── SceneJSON/                   # ranh giới cảnh
├── map-keyframes-aic25-b1/      # map-keyframes của BTC
└── graph/graph.json             # Video → Scene → Frame → Object (+ ocr/asr của cảnh)

frontend/public/media/
└── frames/Keyframes/<batch>/<video_name>/<idx>.webp     # vd L21/L21_V001/000000.webp
```

Kiểm nhanh:

```bash
ls backend/data/indexes/metaclip2.index          # phải có, đây là index đang chạy
ls frontend/public/media/frames/Keyframes        # phải thấy L21 … L30
```

> **Nếu bản dataset tải về chỉ có `siglip.index`** (bản phát hành cũ): hoặc đặt
> `DEFAULT_MODEL=siglip` trong `backend/.env` để chạy tạm, hoặc build lại index
> đúng backbone:
> ```bash
> cd data_processing
> MODEL_KEY=metaclip2 python 02_extract_features.py
> MODEL_KEY=metaclip2 python 03_build_faiss_index.py
> ```
> `DEFAULT_MODEL` **phải khớp** file `<model>.index` + `id_map_<model>.json` có
> trên đĩa; sai khớp thì backend báo thiếu file lúc warm-up.

> **Vì sao keyframe nằm bên frontend.** Backend không mount `StaticFiles`; nó chỉ
> *dựng URL* trỏ về `MEDIA_BASE_URL` (mặc định `http://localhost:5173`) và để Vite
> phục vụ file. Đặt nhầm vào `backend/media/` thì ảnh 404, **và** `frame_bytes()`
> im lặng trả `None` khiến rerank visual lẫn `/agent/qa` mất sạch bằng chứng ảnh
> mà không báo lỗi.
>
> `media/videos/` (mp4 gốc) là **tuỳ chọn** và hiện **không có** trong kho: backend
> tự dùng `watch_url` (YouTube) lấy từ `media-info`.
>
> Kho ~11GB nên **đừng chạy `npm run build`** khi đang thi: `vite build` copy toàn
> bộ `public/` sang `dist/`. Chỉ dùng `npm run dev`.

---

## 4. Cài đặt Backend

```bash
cd backend

python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
# hoặc:  conda create -n aic python=3.11 -y && conda activate aic

pip install -r requirements.txt
cp .env.example .env        # điền GEMINI_API_KEY / OPENAI_API_KEY của bạn
cd ..
```

### Các biến `.env` quan trọng

Bảng dưới là **giá trị đang chạy**; danh sách đầy đủ ở [backend/README.md](backend/README.md) và [backend/config.py](backend/config.py).

| Biến | Đang đặt | Ghi chú |
|------|----------|---------|
| `DEFAULT_MODEL` | `metaclip2` | Phải khớp `<model>.index` trên đĩa. Khả dụng: `metaclip2`, `metaclip`, `siglip`, `siglip512`, `clip`, `beit3` (chỉ khi đã build index tương ứng) |
| `ENSEMBLE_MODELS` | `metaclip2:1.0` | Trọng số khi gọi `model=ensemble`. Muốn nâng trần recall thì thử `siglip512:0.5,metaclip2:0.5` |
| `EMBED_DEVICE` / `EMBED_DTYPE` | `auto` / `fp16` | `cpu` khi không có GPU; `fp32` trên GPU nhỏ sẽ OOM |
| `TEXT_EMBED_MODEL` | `intfloat/multilingual-e5-base` | **Phải khớp** model lúc build index bước 07. Rỗng/`none` = tắt semantic, tự về fuzzy |
| `TEXT_FALLBACK_MODE` / `FUZZY_THRESHOLD` | `fuzzy` / `0.6` | Dùng khi semantic không khả dụng; chịu được lỗi OCR/ASR |
| `GRAPH_KNN_WEIGHT` | `0` (tắt) | Đo được **−1 câu @1**, không thêm gì ở mức nào: footage phát lại nhiều lần nên "hàng xóm cosine" thường là bản sao cảnh đúng nằm trong **video sai** |
| `TEXT_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` (~2,2GB) | Cross-encoder chấm lại OCR/ASR. Nhẹ hơn: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`; `none` = tắt |
| `VISUAL_RERANK_MODEL` | `Salesforce/blip-itm-large-coco` | ITM chấm lại ảnh cho `/search_text`. `none` = tắt |
| `RERANK_CANDIDATES` | `100` | Số ứng viên đầu bảng được rerank |
| `TEXT_RERANK_ALPHA` / `VISUAL_RERANK_ALPHA` | `0.7` / `0.3` | `final = α·rerank + (1−α)·retrieve` |
| `NEIGHBOR_WEIGHT` / `NEIGHBOR_WINDOW_MS` | `0.5` / `10000` | Cộng điểm cho frame có ứng viên cùng video trong ±10s |
| `TEMPORAL_DECAY_ALPHA` / `TEMPORAL_BEAM_WIDTH` | `0.01` / `8` | Beam search chuỗi sự kiện, điểm `Σ sᵢ·e^(−α·Δtᵢ)` |
| `LLM_PROVIDER` | `openai_first` | OpenRouter chạy chính, Gemini đỡ. `auto` = ngược lại; `gemini`/`openai` = ép cứng, **không có đường lui** |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_QA_MODEL` | `https://openrouter.ai/api/v1` · `openai/gpt-5.6-luna` | Base URL **phải** có `/api/v1`. `OPENAI_QA_MODEL` **bắt buộc là model vision** (bước QA gửi ảnh) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | *(điền tay)* · `gemini-3.5-flash-lite` | Key miễn phí tại aistudio.google.com. Rỗng = tắt nhánh Gemini |
| `AGENT_MAX_QA_FRAMES` | `15` | Mỗi lượt QA gửi tới ngần này ảnh **nguyên kích thước** - bước tốn tiền nhất; hạ xuống 4–6 khi dùng model trả phí |
| `ALLOW_RUNTIME_LLM_KEY` | `true` | Cho đổi key/provider/model từ giao diện. `false` khi backend nằm sau tunnel công khai |
| `WARMUP_*` | `true` | Nạp sẵn model + index lúc khởi động (~85s khi `WARMUP_PARALLEL=true`); xem tiến độ `GET /warmup` |

---

## 5. Cài đặt Frontend

```bash
cd frontend
npm install
cd ..
```

> Frontend tự suy ra địa chỉ backend từ host đang mở (mặc định cổng 8000); chỉ sửa `frontend/src/api/apiClient.js` khi backend chạy cổng khác.

---

## 6. Chạy hệ thống

### Cách A - script (khuyến nghị)

```bash
./run.sh                                   # Linux/macOS
CONDA_ENV=aic BACKEND_PORT=8000 ./run.sh   # tuỳ biến
```

Script khởi động backend (uvicorn) + frontend (Vite). Ctrl+C một lần để dừng cả hai. `run.sh` ưu tiên conda env `aic`; dùng venv thì activate rồi chạy tay theo Cách B.

### Cách B - thủ công (2 terminal)

```bash
# Terminal 1
cd backend && source .venv/bin/activate     # hoặc: conda activate aic
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2
cd frontend && npm run dev
```

> **Vite bắt buộc phải chạy** kể cả khi bạn chỉ gọi API: backend kéo pixel keyframe
> qua HTTP từ frontend cho rerank visual, `view_frames` và `/agent/qa`.
> Đừng bật `--reload` khi đã có dữ liệu: mỗi lần file đổi là nạp lại toàn bộ model (~2 phút + một lượt VRAM nữa).

---

## 7. Truy cập

| Dịch vụ | URL |
|---------|-----|
| Frontend (Vite) | http://localhost:5173 |
| Backend Swagger UI | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| Tiến độ warm-up | http://localhost:8000/warmup |

```bash
curl http://localhost:8000/health      # -> {"status":"ok"}
```

### Các endpoint tìm kiếm

| Endpoint | Dùng khi |
|---|---|
| `POST /search_text` | Mô tả cảnh bằng chữ (có `expand` dịch/mở rộng bằng LLM, `rerank`, lọc `objects` / `scene_keywords` / `ocr_keywords` / `asr_keywords`) |
| `POST /search_image` | Ảnh tải lên hoặc một keyframe làm truy vấn |
| `POST /search_ocr` · `/search_asr` · `/search_caption` | Chữ trên màn hình · lời thoại · caption tiếng Anh (semantic E5 + exact/fuzzy) |
| `POST /search_temporal` | Chuỗi sự kiện (TRAKE) - beam search theo thời gian |
| `POST /search_feedback` | "Tìm tương tự" từ các frame đã tick |
| `POST /agent/chat` · `/agent/qa` | Tác tử hội thoại (plan → fan-out đa kênh → ReAct) · hỏi–đáp có ảnh làm bằng chứng |
| `POST /agent/ask` | Một cửa cho cả ba dạng đề: nhận dạng KIS / TRAKE / QA rồi gọi đúng đường ở trên |
| `text_mode=fuse` | Ba ô lọc OCR/ASR/caption chạy như kênh retrieval riêng rồi cộng điểm với visual, thay vì cổng AND (`scripts/eval_search_text.py` đo A/B) |
| `POST /verify_answers` | Đối chiếu đáp án trong giỏ với ASR/OCR/caption trước khi nộp |

---

## 8. Thi theo nhóm 5 người - phòng chung trên LAN

Cả nhóm dùng **chung một giỏ đáp án** (theo từng câu) và **chung lịch sử truy vấn**, đồng bộ tức thì qua WebSocket.

### Cách chạy

**Chỉ MỘT máy chạy server** - cả backend lẫn frontend. 4 máy còn lại chỉ mở trình duyệt.

```bash
# Trên máy chủ (máy có GPU + kho keyframe):
./run.ps1 -BackendHost 0.0.0.0     # Windows
./run.sh                            # Linux/macOS

ipconfig            # Windows -> IPv4 Address
ip addr             # Linux
```

Trên 4 máy còn lại: mở `http://<IP-máy-chủ>:5173`. Không cài gì, không copy kho keyframe. Lần đầu vào, mỗi người nhập tên mình (không có mật khẩu).

### Trong lúc thi

| Thấy ở đâu | Ý nghĩa |
|---|---|
| Avatar trên header | Ai đang online, số nhỏ = **đang làm câu mấy** |
| Chip tên trong giỏ | Frame này do ai chốt |
| Tab "Nhóm" ở Lịch sử | Truy vấn đồng đội đã chạy - bấm để chạy lại |
| Badge `Offline (n)` | Mất kết nối; **vẫn làm việc bình thường**, n thao tác chờ và tự đồng bộ khi kết nối lại |

Câu đang làm là **riêng của từng người**; không ai kéo câu của ai.

### Kiểm chứng trước khi nộp

Trong giỏ đáp án, nút **Kiểm chứng câu N** gọi `/verify_answers`, chạy hoàn toàn offline, hai tầng:

1. **Anchor** (không model): trích tên riêng + số ≥ 3 chữ số trong đề, grep (bỏ dấu) vào toàn bộ ASR + OCR + caption của video đang nộp. Anchor vắng ở video nộp nhưng có ở video khác → cảnh báo **ĐỎ** kèm video gợi ý.
2. **E5**: cosine giữa đề và caption từng frame; dòng tụt hẳn so với trung vị → **VÀNG** "lệch chủ đề".

ĐỎ nghĩa là "dừng lại nhìn 10 giây", không phải "chắc sai" - đo được 2/30 câu báo oan trên bộ SOTUYEN2.

### Lịch sử tra cứu Agent - xem lại mà KHÔNG tốn thêm lượt LLM

Tab **Agent → ⏱ Lịch sử**. Mỗi lượt hỏi Agent tự lưu lên server **kèm danh sách frame đã tìm ra**, tách riêng theo thành viên. Mở lại cuộc cũ rồi bấm **Xem lại kết quả** là đổ nguyên lưới frame của lượt đó - **không gọi `/agent/*` lần nào**.

| | |
|---|---|
| Lưu ở đâu | `ROOM_DIR/agent-history/<member>.json` trên máy chủ phòng |
| Riêng tư | Theo `member_id`; không broadcast qua WebSocket |
| Trần dung lượng | `AGENT_HISTORY_MAX_CHATS` (30), `AGENT_HISTORY_RESULT_CAP` (200 frame/lượt), `AGENT_HISTORY_PAYLOAD_TURNS` (60 lượt gần nhất còn giữ frame) |
| Tắt phòng | Không lưu lên server, nhưng cuộc **đang dở** vẫn sống qua F5 nhờ bản nháp localStorage |

### Sao lưu và đường thoát

```bash
curl http://<IP-máy-chủ>:8000/room/export -o room-backup.json
```

Giỏ được ghi ra đĩa liên tục (`backend/room_state/`) nên restart backend không mất bài.

### Không LAN được - mỗi người một backend, chung một giỏ

```bash
cd backend && python scripts/room_server.py --port 8100
cloudflared tunnel --url http://localhost:8100
```

Cả 5 dán URL tunnel vào **Cài đặt (⚙) → Room URL**. Chi tiết: [docs/VAN_HANH.md](docs/VAN_HANH.md) mục 2d.

### Muốn làm một mình

**Cài đặt (⚙) → Phòng nhóm → Rời phòng**, hoặc `ROOM_ENABLED=false`. Rời phòng **không xoá** giỏ đang có.

```bash
cd backend && python scripts/room_smoke.py     # kiểm tra phần phòng, không cần nạp model
```

### Đổi provider / model LLM giữa buổi thi - không restart backend

**Cài đặt ⚙ → Provider LLM**: chọn `auto` · `openai_first` · `gemini` · `openai`, dán tên model (hai ô riêng cho ReAct và QA), đổi base URL + API key rồi **Áp dụng cấu hình LLM** - có hiệu lực từ request kế tiếp.

Vì sao cần: restart backend tốn ~10 phút nạp lại model thị giác, trong khi thứ hỏng giữa buổi thi thường nằm ở phía LLM (hết credit, tunnel đứt, model text-thuần chết đúng bước QA). Backend chặn trước các lựa chọn làm agent câm (chọn `gemini` khi không có key; `openai` khi thiếu base URL/key/model) kèm lý do. Cấu hình **chỉ nằm trong RAM**; đặt `ALLOW_RUNTIME_LLM_KEY=false` để khoá khi backend nằm sau tunnel công khai.

---

## 9. Vận hành lúc thi + chạy backend trên Colab

**[docs/VAN_HANH.md](docs/VAN_HANH.md)** - ba chế độ vận hành (một mình / LAN 5 người / Colab qua ngrok), bảng sự cố, checklist 10 phút trước giờ thi.

Máy không đủ GPU thì đẩy backend lên Colab: dán [docs/colab_backend_ngrok.py](docs/colab_backend_ngrok.py) vào một cell - kho keyframe 11GB vẫn ở máy bạn, chỉ index lên Colab. Khi backend ở Colab, đặt `MEDIA_DIR` trỏ vào kho ảnh trên đĩa Colab thay vì để từng pixel chui qua tunnel (đo trên ngrok free: 100 ảnh/lượt rerank làm cạn hạn mức, lượt sau rụng 30–70%).

---

## 10. Kỹ thuật tìm kiếm và số đo (chốt 09/2026)

### Các tín hiệu xếp hạng

Áp lên danh sách ứng viên sau khi FAISS trả kết quả, **không cần huấn luyện**:

| Tín hiệu | Service | Khi nào |
|----------|---------|---------|
| Cosine MetaCLIP 2 (+ ensemble, + query expansion bằng LLM) | `faiss` / `embedding` / `ensemble` / `query_expansion` | luôn |
| Neighbor bonus (cửa sổ ±10s cùng video) | `neighbor_service` | luôn |
| Scene bonus (theo ranh giới cảnh) | `graph_service.aggregate_scene_scores` | có `graph.json` |
| Object filter/boost (nhãn của cảnh) | `graph_service.apply_object_filter` | param `objects` |
| Scene text filter/boost (OCR+ASR của cảnh, fuzzy) | `graph_service.apply_scene_text_filter` | param `scene_keywords` |
| Rerank: BLIP ITM (ảnh) / `bge-reranker-v2-m3` (văn bản) | `rerank_service` | `rerank=true` |
| Gộp trùng thị giác xuyên video ở tầng kết quả | `dedup_service` (ngưỡng 0.975) | luôn |
| Lọc OCR/ASR hậu kỳ | `metadata_service` | param `ocr_keywords` / `asr_keywords` |
| kNN expansion | `graph_service.expand_knn` | **đã tắt** (`GRAPH_KNN_WEIGHT=0`) |

### Tác tử `/agent/chat`

`plan_from_dialogue` (LLM gộp cả hội thoại thành 1 plan JSON) → fan-out 2–4 kênh **song song** (visual / ocr / asr / caption) → fuse max-norm theo frame + neighbor + scene → nếu yếu (top < `REACT_SCORE_THRESHOLD` = 0.3) hoặc `deep=true` thì chạy **vòng ReAct ≤ 6 bước** với các công cụ `search`, `search_transcript`, `graph_labels`, `scene_info`, `view_frames` (nhìn ảnh thật), `video_timeline`, `locate_by_asr`.

`locate_by_asr` trả frame id hợp lệ tại thời điểm nói **ngay cả khi không tồn tại keyframe** ở đó - đây là đường duy nhất giải được nhóm video bài giảng (slide đứng yên nhiều phút, không có keyframe).

### Số đo trên bộ 55 câu (`backend/eval/sotuyen12.json`)

`recall@k` = số câu trung bình của MỘT lần chạy có video đúng trong k dòng đầu.

| Cấu hình | lần chạy | vid@1 | vid@5 | vid@20 | vid@100 | frm@1 | frm@100 |
|---|---|---|---|---|---|---|---|
| metaclip2, một lượt | 3 | 19,3 | 32,7 | 42,7 | 48,0 | 12,7 | 35,0 |
| metaclip2 + ReAct (ghép danh sách) | 2 | **23,0** | **35,5** | **44,5** | 50,0 | 12,0 | 36,5 |
| metaclip2 + siglip512, một lượt | 2 | 21,0 | 31,5 | 41,5 | **51,5** | **14,0** | **37,0** |
| siglip512 đơn | 2 | 17,5 | 29,0 | 39,5 | 48,5 | 12,0 | 36,0 |
| metaclip (h14) đơn | 1 | 14,0 | 24,0 | 35,0 | 49,0 | 11,0 | 34,0 |
| 3 backbone | 2 | 19,5 | 30,5 | 39,0 | 48,5 | 13,5 | 35,0 |

**Nhiễu lớn**: cùng cấu hình, `vid@1` đổi ở 5–13 / 55 câu giữa các lần chạy (router LLM không tất định). Chênh 1–2 câu là vô nghĩa; chạy ≥ 3 lượt rồi mới so. Đọc đầy đủ: [docs/IMPROVEMENT_ANALYSIS.md](docs/IMPROVEMENT_ANALYSIS.md) mục 4b · [backend/eval/README.md](backend/eval/README.md).

Kết luận đã dùng để chốt cấu hình:

- ReAct nâng đầu bảng ~+3 câu `vid@1`, **không** nâng frame, và chậm hơn 3–4 lần (9s → 25–40s mỗi câu) → chỉ bật khi một lượt cho kết quả yếu.
- Trộn `metaclip2 + siglip512` nâng trần recall (`vid@100` 48,0 → 51,5) nhưng hạ `@1`; **3 backbone không tốt hơn 2**.
- BLIP rerank ở chế độ một lượt: mọi cột chênh dưới 2 câu, chậm hơn 32% → tắt vì **tốc độ**. Nhưng với `--deep` thì **bắt buộc bật** (`vid@1` 14,5 → 22,5) - chênh lệch duy nhất vượt hẳn nhiễu.

### Chạy eval

```bash
cd backend
python scripts/eval_agent.py                     # /agent/chat một lượt, top_k=100
python scripts/eval_agent.py --deep              # ép vòng ReAct mọi câu
python scripts/eval_agent.py --qa                # thêm /agent/qa cho các câu QA
python scripts/eval_aggregate.py eval/runs/full_baseline*.json
python scripts/eval_search_text.py               # A/B ô lọc: không lọc vs filter vs fuse
python scripts/eval_task_classifier.py           # nhận dạng kis/qa/trake (offline, không cần backend)
```

Backend (và Vite) phải đang chạy; script chỉ gọi HTTP, không nạp model.

---

## 11. Xây lại dữ liệu từ đầu (data_processing)

| Bước | Script | Model | Output |
|------|--------|-------|--------|
| 01 | `01_extract_keyframes.py` / `01b_keyframes_from_map.py` | TransNetV2 | `frames/…`, `frames_meta.json`, SceneJSON |
| 02 | `02_extract_features.py` | `MODEL_KEY=metaclip2` | `features/<model>/…` |
| 03 | `03_build_faiss_index.py` | - | `<model>.index` + `id_map_<model>.json` |
| 03b | `03b_build_keyframe_index.py` | - | `metadata/keyframe_index.json` |
| 04 | `04_extract_ocr.py` | EasyOCR (bản đầu) | `ocr/ocr_data.json` |
| 05 | `05_extract_asr.py` | faster-whisper `large-v3` | `asr/asr_data.json` |
| 07 | `07_build_text_indexes.py` | E5 multilingual base | `ocr_text` · `asr_text` · `caption_text` `.index` |
| 08a | Kaggle `08_extract-objects.ipynb` | **`yolo11x.pt`** (Ultralytics) | `objects/objects_data.json` |
| 08b | `08_build_graph.py` | - | `graph/graph.json` (`--knn` để thêm `knn_<model>.json`) |
| 09b | Kaggle `09b_caption-florence2.ipynb` | **`microsoft/Florence-2-large`** | `captions/caption_data.json` ← **caption đang dùng** |
| 09c | `09c_caption_qwen_vllm.py` / Kaggle `09`, `10` | Qwen2.5-VL-Instruct | `ocr_data.json` (**thay bước 04**); nhánh caption của script này không dùng |

Ghép nhiều batch: `09_merge_batches.py`. Chi tiết: [data_processing/README.md](data_processing/README.md).

> Thư mục `data_processing/kaggle/` còn các nhánh OCR đã thử: `11_extract-ocr-ppocrv5.ipynb` (PP-OCRv5) và `12_extract-ocr-surya.ipynb` (Surya). Chỉ **một** trong các nhánh OCR sinh ra `ocr_data.json` đang dùng - đổi nhánh thì phải build lại `ocr_text.index` (bước 07) cho khớp.
>
> Bước 03 bỏ qua frame có cosine > `DEDUP_THRESHOLD` (0.9) so với frame giữ gần nhất **trong cùng video**. Index đang chạy giữ đủ 244.928 vector; việc gộp bản trùng **xuyên video** làm ở tầng kết quả (`dedup_service`) chứ không làm lúc build.

---

## Xử lý sự cố

| Triệu chứng | Nguyên nhân & cách xử lý |
|-------------|--------------------------|
| Backend báo thiếu `metaclip2.index` / `id_map_metaclip2.json` | Dataset chưa đúng chỗ hoặc `DEFAULT_MODEL` không khớp file có trên đĩa - xem **mục 3** |
| Ảnh keyframe 404 (`/media/...`) | Kho ảnh phải ở `frontend/public/media/frames/Keyframes/...`; kiểm `ls frontend/public/media/frames/Keyframes` |
| Rerank / QA không thấy ảnh dù UI hiển thị bình thường | Vite không chạy, hoặc `MEDIA_BASE_URL` sai → `frame_bytes()` trả `None` **im lặng** |
| CUDA out of memory | `EMBED_DTYPE=fp16`, `WARMUP_RERANKERS=false`, `VISUAL_RERANK_MODEL=none` / `TEXT_RERANK_MODEL=none`, hoặc `EMBED_DEVICE=cpu` |
| Agent trả rỗng / reply cụt | Kiểm `GET /agent/llm_status`: hết credit OpenRouter, sai tên model (400), hoặc `OPENAI_QA_MODEL` là model text-thuần (chỉ hỏng đúng bước QA) |
| `/search_caption` trả 503 | Thiếu `data/captions/caption_data.json` hoặc `caption_text.index` |
| Frontend không gọi được backend (CORS) | Backend đang chạy cổng 8000? Xem `CORS_ORIGINS` trong `.env` |
| `kaggle: command not found` | `pip install kaggle`, đặt `kaggle.json` vào `~/.kaggle/` (chmod 600) |
