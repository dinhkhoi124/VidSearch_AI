# Colab - 1 cell: đăng nhập HuggingFace + tăng tốc tải weight + cache lên Drive.
#
# Chạy cell này TRƯỚC cell khởi động backend, và trước bất kỳ cell nào import
# transformers / huggingface_hub: gói hub đọc HF_HOME và HF_HUB_ENABLE_HF_TRANSFER
# một lần duy nhất lúc nó được import, đặt muộn hơn là vô tác dụng (cell tự phát
# hiện và báo nếu rơi vào trường hợp đó - khi ấy Runtime > Restart session).
#
# Backend đọc HF_TOKEN / HF_HOME từ biến môi trường (backend/config.py), và
# tiến trình con kế thừa os.environ, nên không cần sửa backend/.env.

# @title Đăng nhập HuggingFace + tăng tốc tải weight
import os
import subprocess
import sys

USE_DRIVE = True          # cache weight lên Drive: session sau khỏi tải lại ~7GB
PREFETCH = True           # tải sẵn toàn bộ weight ngay trong cell này

# --- 0. Cảnh báo nếu hub đã bị import từ cell trước ---------------------------
if "huggingface_hub" in sys.modules:
    print("CẢNH BÁO: huggingface_hub đã được import ở cell trước - HF_HOME và "
          "hf_transfer sẽ KHÔNG có hiệu lực. Runtime > Restart session rồi chạy "
          "lại cell này ĐẦU TIÊN.")

# --- 1. Cache bền trên Drive --------------------------------------------------
# Đây là thứ tiết kiệm nhiều nhất: Colab xoá /root/.cache mỗi session, để cache
# trên Drive thì lần chạy thứ hai trở đi không tải lại byte nào.
if USE_DRIVE:
    from google.colab import drive

    drive.mount("/content/drive")
    HF_HOME = "/content/drive/MyDrive/hf_cache"
else:
    HF_HOME = "/root/.cache/huggingface"
os.makedirs(HF_HOME, exist_ok=True)
os.environ["HF_HOME"] = HF_HOME

# --- 2. Token -----------------------------------------------------------------
# Token KHÔNG làm băng thông nhanh hơn. Nó cho quyền tải repo gated và hạn mức
# request cao hơn - đáng kể trên Colab vì hàng nghìn notebook dùng chung dải IP,
# request ẩn danh bị siết trước và hay đứt giữa chừng.
# Cách an toàn: Colab > 🔑 Secrets > thêm khoá tên HF_TOKEN, bật Notebook access.
token = ""
try:
    from google.colab import userdata

    token = (userdata.get("HF_TOKEN") or "").strip()
except Exception:
    pass
if not token:
    from getpass import getpass

    token = getpass("HF token (https://huggingface.co/settings/tokens, quyền read): ").strip()

if token:
    os.environ["HF_TOKEN"] = token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = token   # tên cũ, vài lib vẫn đọc
else:
    print("Không có token - vẫn tải được repo công khai, nhưng dễ dính 429.")

# --- 3. Downloader nhanh ------------------------------------------------------
# hf_xet: đường mặc định của hub >= 0.32 (tải theo chunk + dedup).
# hf_transfer: downloader Rust đa luồng cho repo chưa chuyển sang Xet.
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-U",
     "huggingface_hub[hf_xet]", "hf_transfer"],
    check=True,
)
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60"

# --- 4. Kiểm chứng + tải sẵn weight ------------------------------------------
from huggingface_hub import snapshot_download, whoami

try:
    print("Đăng nhập:", whoami().get("name"))
except Exception as e:
    print(f"Không xác thực được ({type(e).__name__}) - chạy tiếp ở chế độ ẩn danh.")

# Đúng bộ model backend đang cấu hình trong backend/.env
# (DEFAULT_MODEL / ENSEMBLE_MODELS / TEXT_EMBED_MODEL / *_RERANK_MODEL).
# Sửa danh sách này nếu đổi cấu hình.
REPOS = [
    "google/siglip2-so400m-patch16-512",   # siglip512
    "facebook/metaclip-h14-fullcc2.5b",    # metaclip
    "facebook/metaclip-2-worldwide-huge-quickgelu",   # metaclip2 (~3.7GB)
    "intfloat/multilingual-e5-base",       # TEXT_EMBED_MODEL
    "BAAI/bge-reranker-v2-m3",             # TEXT_RERANK_MODEL
    "Salesforce/blip2-itm-vit-g",          # VISUAL_RERANK_MODEL (~4.7GB)
]

if PREFETCH:
    for repo in REPOS:
        print(f"→ {repo}")
        snapshot_download(
            repo,
            # Bỏ các bản trùng định dạng: safetensors là đủ cho transformers.
            ignore_patterns=["*.bin", "*.msgpack", "*.h5", "*.onnx", "*.ot"],
            max_workers=8,
        )
    print("Xong. Backend bật lên sẽ nạp thẳng từ cache, không tải lại.")

print(f"HF_HOME={os.environ['HF_HOME']}")
print("Bật backend ở cell SAU cell này để nó kế thừa các biến môi trường trên.")
