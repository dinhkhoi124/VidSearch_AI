# HCM-AIC-2026 - Pipeline & Flow

Tài liệu mô tả luồng dữ liệu offline (data processing) và luồng xử lý online
(backend + frontend) của hệ thống. Chi tiết API: [BACKEND_API_SPEC.md](BACKEND_API_SPEC.md).

## 1. Kiến trúc tổng thể

```mermaid
flowchart LR
    subgraph OFFLINE["OFFLINE - data_processing (chạy 1 lần / khi có batch mới)"]
        RAW[("Video gốc<br/>Videos_L21, L22…")] --> DP["Pipeline 01→08<br/>(local hoặc Kaggle)"]
        DP --> DATA[("backend/data/<br/>indexes · metadata · ocr · asr · graph")]
        DP --> MEDIA[("backend/media/<br/>frames/Keyframes/…")]
    end

    subgraph ONLINE["ONLINE - truy vấn"]
        FE["Frontend React<br/>(SearchPage + 🤖 AgentChatPanel)"] <-->|REST| BE["Backend FastAPI"]
        BE --> DATA
        BE --> MEDIA
        BE <-->|"query expansion · plan · QA vision"| GEMINI["Gemini API"]
    end
```

## 2. Pipeline offline (data_processing 01→08)

| Bước | Script local | Notebook Kaggle | Output |
|------|--------------|-----------------|--------|
| 01 | `01_extract_keyframes.py` (TransNetV2) / `01b` (map CSV) | `01`, `02`, `03` | `media/frames/…`, `frames_meta.json`, SceneJSON |
| 02 | `02_extract_features.py` | `04_infer-embedding` | `features/<model>/<video>/<frame>.npy` |
| 03 | `03_build_faiss_index.py` (dedup 0.9) | `05_create-index/bin` | `<model>.index` + `id_map_<model>.json` |
| 04 | `04_extract_ocr.py` (EasyOCR vi+en) | `06_extract-ocr` | `ocr/ocr_data.json` |
| 05 | `05_extract_asr.py` (faster-whisper) | `07_extract-asr` | `asr/asr_data.json` |
| 07 | `07_build_text_indexes.py` (E5) | - | `ocr_text.index`, `asr_text.index`, `caption_text.index` + sidecar |
| 08 | `08_build_graph.py` (`--knn`) | `08_extract-objects` (input) | `graph/graph.json`, `graph/knn_<model>.json` |
| 09 | - (chỉ Kaggle) | `09_extract-ocr-caption-qwen` (Qwen2.5-VL-3B) | `ocr_data.json` (thay 04) + `captions/caption_data.json` |

```mermaid
flowchart TD
    RAW[("Video .mp4")] --> KF["01 · Keyframes<br/>TransNetV2 / map-keyframes"]
    KF --> FRAMES[("frames/Keyframes/&lt;batch&gt;/&lt;video&gt;/&lt;idx&gt;.webp")]
    KF --> META[("frames_meta.json<br/>frame_id → video, timestamp, fps")]
    KF --> SCENE[("SceneJSON<br/>ranh giới cảnh [start_idx, end_idx]")]

    FRAMES --> FEAT["02 · Embedding<br/>SigLIP / CLIP"] --> IDX["03 · FAISS IndexFlatIP<br/>+ dedup cosine ≥ 0.9"]
    IDX --> INDEXES[("&lt;model&gt;.index + id_map")]

    FRAMES --> OCR["04 · OCR (EasyOCR)"] --> OCRJ[("ocr_data.json")]
    RAW --> ASR["05 · ASR (faster-whisper)"] --> ASRJ[("asr_data.json")]
    OCRJ & ASRJ --> TXTIDX["07 · Text indexes (E5)"] --> TIDX[("ocr_text / asr_text .index")]

    OBJOFF[("objects-aic25-b1<br/>detections chính thức")] --> GRAPH
    OBJKAGGLE[("objects_data.json<br/>Kaggle 08 · OpenImages V4<br/>(tuỳ chọn, per-frame)")] --> GRAPH
    META & SCENE & OCRJ & ASRJ --> GRAPH["08 · Build graph"]
    INDEXES -->|"--knn: self-search"| GRAPH
    GRAPH --> GJSON[("graph.json<br/>Video → Scene → Frame → Object<br/>+ scene.ocr / scene.asr")]
    GRAPH --> KNN[("knn_&lt;model&gt;.json<br/>cạnh similarity k=10")]
```

## 3. Luồng search chính (`POST /search_text`)

Thứ tự đúng như code ([routers/search_text.py](backend/routers/search_text.py)):

```mermaid
flowchart TD
    Q["Query (vi/en)"] --> EXP{"expand=true?"}
    EXP -->|"Gemini"| VAR["4 biến thể tiếng Anh<br/>(biến thể 0 = bản dịch)"]
    EXP -->|không| ONE["query gốc"]
    VAR & ONE --> RET["FAISS retrieve top_k×4<br/>(siglip / clip / ensemble)<br/>+ gộp điểm max-norm giữa biến thể"]

    RET --> G1["Graph · expand_knn<br/>thêm hàng xóm similarity của top ứng viên"]
    G1 --> NB["neighbor_service<br/>bonus cụm cùng video ±10s (mean)"]
    NB --> G2["Graph · aggregate_scene_scores<br/>bonus theo ranh giới cảnh"]
    G2 --> G3{"objects?"}
    G3 -->|"filter/boost"| G4{"scene_keywords?"}
    G3 -->|không| G4
    G4 -->|"filter/boost<br/>(OCR+ASR của cảnh, fuzzy)"| RR
    G4 -->|không| RR{"rerank=true?"}
    RR -->|"BLIP ITM top-100"| BUILD
    RR -->|không| BUILD["build_search_results<br/>+ lọc ocr_keywords / asr_keywords"]
    BUILD --> OUT["top_k SearchResult<br/>(frame_url, video_url, timestamp…)"]
```

Các luồng khác dùng chung khối trên: `/search_image` (encode ảnh thay text,
không expand/rerank), `/search_ocr` `/search_asr` (E5 semantic + exact/fuzzy),
`/search_temporal` (retrieve từng event → beam search chuỗi theo thời gian).

## 4. Luồng agent (MemoriEase-style)

### 4.0 `POST /agent/ask` - một cửa, ba đường

Người thi dán nguyên đề vào một ô; backend nhận dạng dạng đề rồi rẽ. Ba pipeline
bên dưới KHÔNG gộp - chúng khác nhau ở bản chất retrieval (xem 4.1, 4.2 và
`qa_select_evidence`): KIS fuse theo frame + gom neighbor/scene, TRAKE fuse theo
từng event rồi ghép chuỗi trong một video, QA fuse theo VIDEO và luôn bật kênh
ASR/OCR. Đo trên SOTUYEN2: ép kênh ASR/OCR cho KIS kéo top-5 từ 22/30 xuống
13/30; gom neighbor cho QA đè mất video đúng.

```mermaid
flowchart TD
    Q["Nguyên văn đề<br/>(dán vào 1 ô)"] --> SRC{"bộ đề BTC<br/>đã nạp?"}
    SRC -->|"có: task_type"| T{"dạng?"}
    SRC -->|"không"| CLS["task_classifier (regex)<br/>E1/Cảnh 1 · dấu ? · từ để hỏi<br/>143/143 trên đề mẫu"]
    CLS --> T
    T -->|kis| C1["/agent/chat<br/>hint mode=search"]
    T -->|trake| C2["/agent/chat<br/>hint mode=temporal"]
    T -->|qa| C3["/agent/qa<br/>retrieve đa kênh + vision"]
    C1 --> UI0["reply + chip dạng đề<br/>→ lưới chính"]
    C2 --> UI0
    C3 --> UI0
```

### 4.1 `POST /agent/chat` - tìm kiếm hội thoại

```mermaid
flowchart TD
    CHAT["Lịch sử chat<br/>(nhiều lượt refine)"] --> PLAN["Gemini · plan_from_dialogue<br/>gộp thành 1 plan JSON"]
    PLAN --> P[("mode · query(EN) · events · steps<br/>objects · scene_keywords · reply")]
    P --> M{"mode?"}
    M -->|"search, steps ≥ 2<br/>(nhiều loại manh mối)"| FAN["🧭 Plan-and-Execute<br/>2-4 kênh SONG SONG:<br/>visual / ocr / asr / caption<br/>(caption tự thêm khi có dữ liệu)"]
    FAN --> FUSE["Fuse max-norm theo frame<br/>+ neighbor + scene aggregation<br/>(gộp bằng chứng cùng cảnh)"]
    FUSE --> W
    M -->|"search, steps < 2"| ST["/search_text pipeline<br/>(expand=false, boost objects + scene_keywords)"]
    M -->|"temporal<br/>('sau đó…')"| TP["/search_temporal<br/>q1→q2→q3 = events"]
    ST --> W{"yếu (top &lt; 0.3 / rỗng)<br/>hoặc deep=true?"}
    W -->|không| UI
    W -->|có| REACT["🧠 Vòng ReAct (≤ 3 bước)<br/>Thought → Action → Observation nén"]
    REACT -->|"tool: search / graph_labels /<br/>scene_info / view_frames (vision)"| REACT
    REACT -->|"giữ kết quả tốt nhất + trace"| UI
    TP --> UI["reply + plan chips + trace + kết quả<br/>→ lưới chính frontend"]
    PLAN -.->|"Gemini lỗi/thiếu key"| FB["fallback: tin nhắn cuối = query"]
```

### 4.2 `POST /agent/qa` - hỏi đáp RAG

```mermaid
flowchart TD
    QS["Câu hỏi"] --> HAS{"frame_ids<br/>người dùng chọn?"}
    HAS -->|có| EV["Dùng đúng các frame đó"]
    HAS -->|không| RETQ["/search_text (expand=true)<br/>tự retrieve top 6"]
    EV & RETQ --> CTX["Mỗi frame: ảnh keyframe (base64)<br/>+ OCR/ASR của CẢNH (graph) + timestamp"]
    CTX --> LLM["Gemini vision"] --> ANS["answer + evidence frame<br/>(xếp đầu danh sách)"]
```

### 4.3 `POST /search_feedback` - relevance feedback

```mermaid
flowchart LR
    PICK["Frame user tick ✓"] --> REC["reconstruct vector<br/>từ FAISS index (không encode lại)"]
    REC --> POOL["mean → chuẩn hoá"]
    QORIG["Query gốc"] --> QV["encode_text"]
    POOL & QV --> BLEND["v = 0.5·q + 0.5·pooled"]
    BLEND --> S["FAISS search<br/>(loại frame đã chọn)"] --> PIPE["knn → neighbor → scene"] --> OUT2["Kết quả mới"]
```

## 5. Frontend flow

```mermaid
flowchart LR
    subgraph SearchPage
        SIDE["Sidebar: 5 mode<br/>text/image/ocr/asr/temporal<br/>+ filter + model + rerank/expand"] --> GRID["Lưới kết quả<br/>(ResultItem)"]
        GRID -->|"tick ✓ chọn frame"| BAR["Thanh nổi:<br/>🔁 Tìm tương tự (feedback)"]
        BAR --> GRID
        CHATP["🤖 AgentChatPanel<br/>Tìm (chat) / Hỏi (QA, dùng frame đã chọn)"] -->|injectResults| GRID
        GRID --> MODALS["Zoom / Video player /<br/>Chuỗi frame liên tiếp / Xem cả cảnh"]
    end
```

## 6. Các tín hiệu xếp hạng (tổng hợp)

| Tín hiệu | Service | Khi nào |
|----------|---------|---------|
| Cosine SigLIP/CLIP (+ ensemble, + query expansion) | `faiss/embedding/ensemble/query_expansion` | luôn |
| kNN expansion (cạnh similarity) | `graph_service.expand_knn` | có `knn_<model>.json` |
| Neighbor bonus (cửa sổ ±10s) | `neighbor_service` | luôn |
| Scene bonus (ranh giới cảnh) | `graph_service.aggregate_scene_scores` | có `graph.json` |
| Object filter/boost (nhãn OpenImages của cảnh) | `graph_service.apply_object_filter` | param `objects` |
| Scene text filter/boost (OCR+ASR cảnh, fuzzy) | `graph_service.apply_scene_text_filter` | param `scene_keywords` |
| BLIP ITM rerank (query–ảnh) | `rerank_service` | `rerank=true` |
| Lọc OCR/ASR hậu kỳ | `metadata_service` | param `ocr/asr_keywords` |
