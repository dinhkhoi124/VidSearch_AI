# HCM-AIC-2026 Frontend

React 19 + Vite + TailwindCSS. Giao diện tra cứu keyframe cho cuộc thi AIC:
tìm kiếm đa chế độ, agent chat, chọn frame và **nộp bài** (export/live submit).

```bash
npm install
npm run dev        # http://localhost:5173
```

## Cấu hình backend

Backend FastAPI mặc định ở `http://localhost:8000`. Thứ tự ưu tiên base URL
(xem [src/api/apiClient.js](src/api/apiClient.js)):

1. **Cài đặt (⚙) trong app** - đổi runtime, lưu `localStorage`, không cần rebuild.
2. **`VITE_API_BASE_URL`** trong [.env](.env) - cấu hình lúc build, cần restart `npm run dev`.
3. `http://localhost:8000` - mặc định dev.

## Tính năng

- **5 chế độ tìm kiếm** (sidebar trái): Text / Image / OCR / ASR / Temporal,
  kèm filter OCR/ASR, chọn model (siglip / clip / ensemble), rerank, dịch &
  mở rộng query (Gemini). Lịch sử truy vấn được lưu lại
  ([useQueryHistory.js](src/hooks/useQueryHistory.js)) để chạy lại nhanh khi thi.
- **🤖 Agent chat** (nút tròn góc phải dưới - [AgentChatPanel.jsx](src/components/AgentChatPanel.jsx)):
  - **Tìm**: mô tả bằng tiếng Việt tự nhiên qua nhiều lượt chat; backend gộp cả
    hội thoại thành một plan (query + objects + scene_keywords, tự nhận diện
    chuỗi sự kiện → temporal) rồi đổ kết quả vào lưới chính. Plan hiển thị
    dưới câu trả lời dạng chips để kiểm soát agent đã tìm gì.
  - **Hỏi**: hỏi đáp nội dung video (RAG - Gemini vision đọc keyframe + OCR/ASR
    của cảnh). Nếu đang chọn frame nào thì trả lời dựa trên đúng các frame đó.
- **Vùng nháp + relevance feedback** ([SelectedFramesPanel.jsx](src/components/SelectedFramesPanel.jsx)):
  hover lên kết quả → tick ✓ để chọn (viền xanh). Vùng nháp (docked góc dưới-trái)
  gom các frame đã chọn → **🔁 Tìm tương tự** trộn embedding các frame đó với query
  hiện tại (`POST /search_feedback`) và loại chính chúng khỏi kết quả mới. Các frame
  đang chọn cũng là bằng chứng cho chế độ **Hỏi** của agent, và có thể đẩy sang Giỏ đáp án.
- **📥 Giỏ đáp án + nộp bài** ([SubmissionPanel.jsx](src/components/SubmissionPanel.jsx)):
  danh sách **có thứ tự** (rank = vị trí) tách biệt với vùng nháp. Kéo hạng lên/xuống,
  chọn loại task **KIS / Q&A / TRAKE**, đặt Query ID và số dòng tối đa, xem trước CSV,
  rồi **Export CSV/JSON** hoặc **Nộp trực tiếp** (nếu đã cấu hình endpoint DRES).
  Định dạng nộp gói gọn trong [utils/submissionFormat.js](src/utils/submissionFormat.js) -
  chỗ duy nhất cần sửa khi BTC AIC 2026 chốt format chính thức.
- **Frame đã xem**: frame từng mở video / phóng to được đánh dấu và làm mờ khi duyệt
  ([useSeenFrames.js](src/hooks/useSeenFrames.js)), tránh xem lặp khi tính giờ.
- **⌨ Phím tắt** (bảng tra ở nút bàn phím trên header -
  [HotkeysHelp.jsx](src/components/HotkeysHelp.jsx)): `1` tab Thủ công · `2` tab Agent ·
  `s` mở giỏ đáp án · `Esc` đóng modal. Mọi thao tác khác dùng chuột.

## frame_idx (chỉ số nộp bài)

[utils/frameIndex.js](src/utils/frameIndex.js) tính `frame_idx` trong video gốc:
ưu tiên parse số từ tên keyframe (vd `000123.webp`), fallback
`round(timestamp_ms/1000 * fps)` - cùng công thức VideoPlayerModal hiển thị.

## Cấu trúc

```text
src/
├── api/            apiClient (axios, base URL runtime), searchService,
│                   submissionService (nộp live DRES-style)
├── hooks/          useSearch, useAnswerBasket (giỏ nộp), useSeenFrames,
│                   useQueryHistory, useHotkeys, usePersistedState
├── utils/          frameIndex, submissionFormat (KIS/QA/TRAKE ↔ CSV/JSON)
├── components/     ResultItem, AgentChatPanel, SelectedFramesPanel,
│                   SubmissionPanel, SettingsModal, HotkeysHelp, Icons,
│                   VideoPlayerModal, FrameSequenceModal,
│                   AsrResultGroup, TemporalResultGroup
└── pages/          SearchPage (toàn bộ layout + state)
```
