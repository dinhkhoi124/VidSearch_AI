# Vận hành hệ thống

Tài liệu cho người **đang thi**, không phải người đọc code. Cài đặt lần đầu xem
[README](../README.md) mục 1–6.

---

## 1. Hệ thống chạy ra sao

Ba khối, chạy độc lập được:

```
Trình duyệt ──► Frontend (Vite :5173) ──► Backend (FastAPI :8000) ──► data/ (index FAISS)
                     │
                     └── public/media/ ──► keyframe .webp  (ảnh hiện trên màn hình)
```

### Điều quan trọng nhất phải nhớ

**Backend không đọc ảnh từ đĩa.** Nó chỉ *dựng URL* trỏ về `MEDIA_BASE_URL`, còn
file thật do Vite phục vụ. Khi cần pixel (rerank visual, `/agent/qa`) thì backend
mới `GET` ảnh qua HTTP.

Hệ quả: đặt kho keyframe sai chỗ thì **ảnh vỡ, VÀ chất lượng tìm kiếm tụt mà không
báo lỗi gì** - rerank nhận ảnh rỗng, agent trả lời không nhìn ảnh nào. Từ 2026-08-19
backend đã in cảnh báo `[media] KHONG lay duoc keyframe` khi gặp trường hợp này;
thấy dòng đó là dừng lại sửa ngay, đừng thi tiếp.

Kho keyframe đúng chỗ: **`frontend/public/media/frames/Keyframes/<batch>/<video>/`**

### Năm chế độ tìm kiếm

| Chế độ | Endpoint | Dùng khi |
|---|---|---|
| Text | `/search_text` | mô tả cảnh bằng lời (query được LLM dịch + mở rộng sang tiếng Anh trước) |
| Image | `/search_image` | có sẵn ảnh mẫu |
| OCR | `/search_ocr` | nhớ chữ xuất hiện trên màn hình |
| ASR | `/search_asr` | nhớ lời thoại / lời thuyết minh |
| Temporal | `/search_temporal` | chuỗi sự kiện "A rồi tới B" (tối đa 4 event) |

Định tuyến ở [useSearch.js](../frontend/src/hooks/useSearch.js).

Hai đường agent: `/agent/chat` tự lập kế hoạch tìm hộ, `/agent/qa` trả lời câu hỏi
**có nhìn ảnh** (nên nó là thứ hỏng nặng nhất nếu đường ảnh đứt).

### Video bài giảng: frame không có keyframe

Bước cắt keyframe bỏ gần hết đoạn slide tĩnh (TransNetV2 thấy 1 shot dài, dedup
coi các frame là trùng). Đo trên `frames_meta.json`: **127 video có khoảng trống
> 30 giây, 88 trong số đó thuộc batch L25** (bài giảng), tệ nhất là 829 giây liên
tục không còn frame nào. Search hình ảnh không thể trúng những đoạn đó vì không
có gì trong index để trúng.

Vòng ReAct có ba công cụ cho tình huống này, **không cần cắt lại keyframe**:

| Tool | Làm gì |
|------|--------|
| `search_transcript` | video nào NÓI (asr) / HIỆN CHỮ (ocr) cụm từ đó |
| `locate_by_asr` | mốc ASR khớp nhất TRONG một video, trả frame id nộp được **kể cả khi không có keyframe** |
| `video_timeline` | keyframe + lời nói trong một cửa sổ thời gian, thấy rõ chỗ trống |

`locate_by_asr` đăng ký "frame ảo" qua `metadata_service.register_virtual_frame`:
`frame_name` mang chỉ số frame thật (để nộp bài đúng), còn ảnh hiển thị lấy
keyframe gần nhất. Chỉ nằm trong RAM, **không** ghi vào `frames_meta.json`.

Agent hay ghim đúng video bằng transcript rồi bỏ cuộc vì không có ảnh để chọn;
`react_refine` tự chạy nốt `locate_by_asr` trong trường hợp đó, nhưng **chỉ với
yêu cầu kiểu bài giảng** (`_lecture_like`) - với tin tức/thể thao thì video mà
ASR ghim được thường chỉ cùng chủ đề chứ không phải video đúng.

### Warm-up

Bật server xong, model + index nạp mất **~2 phút**. Mặc định warm-up chạy nền nên
server nhận request ngay, nhưng câu search đầu sẽ chậm.

```bash
curl http://localhost:8000/health     # {"ready": true} = nạp xong
curl http://localhost:8000/warmup     # chi tiết từng bước, index nào thiếu
```

### Từ giỏ đáp án tới file nộp

Giỏ chia **theo từng câu**, mỗi câu có `taskType` (KIS / Q&A / TRAKE), `queryId`
và thứ tự hạng. Bấm **Xuất gói nộp** thì app kiểm tra trước
([submissionValidate.js](../frontend/src/utils/submissionValidate.js)) - thiếu câu
trả lời Q&A, chưa khai số event TRAKE, trùng tên file... đều **chặn không cho xuất**.
Qua được mới đóng gói `.zip` chứa thư mục `submission/` theo spec BTC.

---

## 2. Bốn chế độ vận hành

| | Một mình | LAN 5 người | Colab + ngrok | Mỗi người một BE |
|---|---|---|---|---|
| Backend chạy ở | máy bạn | máy chủ | Colab (GPU) | **máy của từng người** |
| `MEDIA_BASE_URL` | mặc định | mặc định | **URL tunnel FE** | mặc định |
| FE trỏ backend bằng | tự suy ra | tự suy ra | Settings ⚙ | tự suy ra |
| `CORS_ORIGINS` | mặc định | mặc định | + origin FE *nếu* mở FE qua tunnel | mặc định |
| Giỏ đáp án nằm ở | localStorage | máy chủ | Colab → **phải để trên Drive** | **1 room server chung** |
| Room URL (⚙) | trống | trống | trống | **URL chung, cả 5 dán giống nhau** |

### 2a. Một mình

```bash
./run.sh          # Linux/macOS
./run.ps1         # Windows
```
Mở http://localhost:5173. Xong.

### 2b. LAN 5 người

Xem [README mục 8](../README.md). Tóm tắt: **một máy** chạy `./run.ps1 -BackendHost 0.0.0.0`,
bốn máy còn lại mở `http://<IP-máy-chủ>:5173`. Không phải cài gì, không phải copy
keyframe, không phải sửa file cấu hình nào - FE tự suy địa chỉ backend từ host đang mở.

### 2c. Colab + ngrok

Dùng khi máy bạn không đủ GPU. Xem mục 3.

### 2d. Mỗi người một BE, chung một giỏ

Dùng khi 5 người **ở 5 mạng khác nhau**, không LAN được, và ai cũng đủ máy chạy
backend riêng. Mỗi người search bằng GPU của mình, chỉ giỏ đáp án là chung.

```text
   máy A          máy B          máy C          máy D          máy E
   BE+FE          BE+FE          BE+FE          BE+FE          BE+FE
     └──────────────┴──── Room URL ─┴──────────────┴──────────────┘
                            │
                   room server (1 chỗ) + tunnel
```

**Người giữ phòng** chạy thêm một tiến trình nhẹ, KHÔNG có search:

```bash
cd backend && python scripts/room_server.py --port 8100
cloudflared tunnel --url http://localhost:8100     # -> https://<room>.trycloudflare.com
```

`room_server.py` chỉ gắn `routers/room.py`, không import torch/faiss/transformers,
không cần `backend/data/` lẫn GPU - nó lên trong một hai giây và đặt được trên máy
bất kỳ. State ghi vào `ROOM_DIR` y như bản đầy đủ.

**Cả 5 người** (kể cả người giữ phòng) làm giống nhau:

1. `./run.sh` - BE + FE của chính mình
2. ⚙ → **Backend URL**: để trống (tự suy ra `localhost:8000`)
3. ⚙ → **Room URL**: dán `https://<room>.trycloudflare.com` - **cùng một chuỗi ở cả 5 máy**

Ô Room URL để trống thì giỏ nằm trên chính Backend URL, tức đúng hành vi của ba
chế độ trên - không ai phải cấu hình lại gì.

**Vì sao chung giỏ được dù 5 backend khác nhau:** id của một mục giỏ là
`<video_name>_<frame_idx>`, sinh từ dữ liệu chứ không phải từ backend, nên 5 máy
cho ra id trùng khớp và op `add` vẫn idempotent. Còn `frame_url` lưu trong giỏ là
URL tuyệt đối của người đã thêm, được localize lại về origin người đang xem lúc
render - mỗi người thấy ảnh từ `public/media/` của chính mình.

**Điều kiện:** cả 5 người dùng cùng bộ `backend/data/`. Lệch version index thì id
vẫn khớp (id theo frame, không theo index), chỉ là kết quả search khác nhau - giỏ
không hỏng.

**Rủi ro:** máy giữ phòng tắt hoặc rớt tunnel là cả nhóm mất giỏ chung. Vẫn làm
việc bình thường (badge `Offline (n)`, thao tác xếp hàng chờ đồng bộ), nhưng phải
dựng lại tunnel và 4 người dán URL mới. Sao lưu:
`curl https://<room>.trycloudflare.com/room/export -o room-backup.json`

---

## 3. Dựng ngrok (BE trên Colab)

### Vì sao cần HAI tunnel

Hai chiều khác nhau, không lược bớt được cái nào:

```
Browser ──API──► tunnel BE ──► Colab
Colab   ──ảnh──► tunnel FE ──► Vite trên máy bạn
```

Tunnel FE tồn tại **chỉ để Colab với tay xuống lấy bytes keyframe**. Ảnh hiện trên
màn hình thì không đi qua đó: [mediaUrl.js](../frontend/src/utils/mediaUrl.js) viết
lại host về origin đang mở, nên thumbnail đọc thẳng từ đĩa. Chỉ ~100 ảnh mỗi lượt
rerank là thật sự chui qua tunnel.

### Vì sao data chia được

| | Dung lượng | Ở đâu |
|---|---|---|
| `backend/data/` - index FAISS, metadata, OCR/ASR, graph | ~6.5 GB | Colab (từ Drive) |
| `frontend/public/media/` - keyframe | ~11 GB | máy bạn |

11GB không cần lên Colab. Đó là điều làm mô hình này khả thi.

### Các bước

**Bước 0 - đẩy nhánh lên GitHub.** Colab kéo code từ remote, commit nằm ở local thì
nó không thấy:

```bash
git push -u origin feature/room
```

**Bước 1 - cài ngrok ở máy local** (chưa có sẵn):

```bash
winget install ngrok.ngrok           # Windows
brew install ngrok                   # macOS
# authtoken lấy ở https://dashboard.ngrok.com/get-started/your-authtoken
ngrok config add-authtoken <TOKEN>
```

**Bước 2 - bật FE và tunnel của nó:**

```bash
cd frontend && npm run dev           # terminal 1
ngrok http 5173                      # terminal 2  -> https://<fe>.ngrok-free.dev
```

> Đã thêm keyframe vào `public/media` mà Vite đang chạy sẵn? **Restart Vite.** Nó
> chốt danh sách `public/` lúc khởi động; không restart thì ảnh vẫn 404.

**Bước 3 - trên Colab**, chạy hai cell theo đúng thứ tự:

1. [`colab_hf_setup.py`](colab_hf_setup.py) - cache weight HuggingFace lên Drive
2. [`colab_backend_ngrok.py`](colab_backend_ngrok.py) - dán URL ở bước 2 vào
   `FE_TUNNEL_URL`, chạy. Cell tự lo repo, thư viện, symlink data, tunnel BE, và in
   ra URL backend.

**Bước 4 - nối FE vào BE:** mở http://localhost:5173 → **Cài đặt (⚙)** → dán URL
backend cell vừa in → **Lưu**. Không cần F5, phòng nhóm tự nối lại.

**Bước 5 - kiểm tra trước khi tin:**

```bash
# đường ảnh (hỏng ở đây là rerank/QA chạy mù mà không báo)
curl -sI https://<fe>.ngrok-free.dev/media/frames/Keyframes/L21/L21_V001/000000.webp | head -3
#   -> phải thấy: content-type: image/webp

# backend sống
curl -H "ngrok-skip-browser-warning: 1" https://<be>.ngrok-free.dev/health
#   -> {"status":"ok", ...}
```

### Hai điều dễ hiểu sai

**CORS chỉ đụng tới khi mở FE QUA tunnel.** Mở FE ở `localhost:5173` thì Origin gửi
lên backend là `http://localhost:5173`, vốn đã nằm trong `CORS_ORIGINS` mặc định.
Việc Colab fetch ảnh là request **server-side**, không dính CORS. Đừng đặt
`CORS_ORIGINS=*` - kèm `allow_credentials=True` là cặp trình duyệt từ chối, và nó
vô hiệu hoá luôn phần tự cho qua dải LAN.

**ngrok free giới hạn tunnel đồng thời trên một tài khoản.** Hai tunnel ở hai máy
dùng chung authtoken có thể bị từ chối cái thứ hai. Đường lui, không phải sửa code:

```bash
cloudflared tunnel --url http://localhost:5173     # cho FE
```

Domain `.trycloudflare.com` đã có sẵn trong `allowedHosts` của
[vite.config.js](../frontend/vite.config.js).

---

## 4. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Sửa |
|---|---|---|
| Ảnh vỡ hết | keyframe sai chỗ, hoặc Vite chưa restart sau khi thêm `public/media` | restart Vite; kiểm bằng lệnh ở Bước 5 |
| Log `[media] KHONG lay duoc keyframe` | backend không với tới ảnh → **rerank + `/agent/qa` đang chạy mù** | kiểm `MEDIA_BASE_URL`, tunnel FE còn sống không |
| Gọi API nhận HTML, lỗi parse lạ | trang cảnh báo ngrok | app đã tự gửi header; nếu `curl` thủ công thì thêm `-H "ngrok-skip-browser-warning: 1"` |
| Search chạy nhưng kết quả kém bất thường | warm-up chưa xong, hoặc thiếu index | `curl /warmup` xem bước nào lỗi |
| Đổi Backend URL mà phòng không nối lại | (đã sửa ở `23c46ad`) | nếu tái diễn: F5, rồi báo lại |
| `Offline (n)` trên MemberBar | mất kết nối tới backend | **vẫn làm việc bình thường**, n thao tác tự đồng bộ khi mạng về |
| Tunnel thứ hai bị từ chối | giới hạn ngrok free | dùng `cloudflared` cho FE |
| Colab chết giữa chừng | hết phiên / mất GPU | chạy lại cell; **giỏ còn nguyên nếu `ROOM_DIR` trên Drive** |
| `ModuleNotFoundError` lúc bật backend | thiếu gói | `pip install -r backend/requirements.txt` |

---

## 5. Checklist 10 phút trước giờ thi

- [ ] `curl localhost:8000/health` → `"ready": true`
- [ ] Chạy thử một câu Text, **thấy ảnh hiện ra** (không phải ô xám)
- [ ] Log backend **không có** dòng `[media] KHONG lay duoc keyframe`
- [ ] Thử `/agent/qa` một câu - trả lời có dẫn được frame bằng chứng
- [ ] Thêm 1 frame vào giỏ, máy khác thấy ngay (nếu thi nhóm)
- [ ] Xuất thử gói nộp với 1 câu → mở `.zip`, có thư mục `submission/`
- [ ] Colab: `ROOM_DIR` đang trỏ Drive, không phải `./room_state`
- [ ] Backup: `curl http://<be>/room/export -o room-backup.json`

> **Đừng chạy `npm run build` lúc thi.** `vite build` copy toàn bộ `public/` sang
> `dist/` - 11GB keyframe, mất vài phút và đầy đĩa. Chỉ dùng `npm run dev`.
