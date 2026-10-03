# Colab - 1 cell: chạy BACKEND trên Colab (GPU) và mở ra ngoài bằng ngrok.
#
# Mô hình: BE ở Colab, FE + kho keyframe ở máy bạn. Hai bên nối nhau bằng HAI
# tunnel, mỗi cái một chiều - xem docs/VAN_HANH.md nếu chưa rõ vì sao cần cả hai:
#
#   Browser --API--> tunnel BE  --> Colab (cell này)
#   Colab   --ảnh--> tunnel FE  --> Vite trên máy bạn
#
# THỨ TỰ: chạy colab_hf_setup.py TRƯỚC cell này (nó đặt HF_HOME/hf_transfer, mà
# huggingface_hub chỉ đọc hai biến đó đúng một lần lúc được import).
#
# TRƯỚC KHI CHẠY, ở máy local:
#   1. npm run dev            (Vite lên cổng 5173)
#   2. ngrok http 5173        hoặc: cloudflared tunnel --url http://localhost:5173
#   3. dán URL vừa nhận vào FE_TUNNEL_URL bên dưới

# @title Chạy backend AIC trên Colab sau ngrok
import os
import subprocess
import sys
import time
import urllib.request

# --- Cấu hình -----------------------------------------------------------------
FE_TUNNEL_URL = ""          # BẮT BUỘC: URL tunnel của FE, vd https://abc.ngrok-free.dev
REPO_URL = "https://github.com/nlnamanh/HCM-AIC-2026.git"
BRANCH = "feature/room"
WORKDIR = "/content/HCM-AIC-2026"

# backend/data (~6.5GB index FAISS + metadata) để sẵn trên Drive: phiên sau chỉ
# mount là có ngay, khỏi tải lại từ Kaggle.
DRIVE_DATA = "/content/drive/MyDrive/aic_data"
# Giỏ đáp án của CẢ NHÓM. Xem cảnh báo ở bước 5 - đừng đổi ra ngoài Drive.
DRIVE_ROOM = "/content/drive/MyDrive/aic_room_state"

BACKEND_PORT = 8000

if not FE_TUNNEL_URL.strip():
    raise SystemExit(
        "Thiếu FE_TUNNEL_URL. Backend cần URL này để fetch bytes keyframe từ máy bạn "
        "cho rerank visual và /agent/qa. Bỏ trống thì search vẫn chạy nhưng hai thứ "
        "đó chạy MÙ mà không báo lỗi - đúng kiểu hỏng khó phát hiện nhất."
    )
FE_TUNNEL_URL = FE_TUNNEL_URL.rstrip("/")

# --- 1. Drive -----------------------------------------------------------------
from google.colab import drive

drive.mount("/content/drive")

if not os.path.isdir(os.path.join(DRIVE_DATA, "indexes")):
    raise SystemExit(
        f"Không thấy {DRIVE_DATA}/indexes.\n"
        "Lần đầu phải đưa backend/data lên Drive (~6.5GB, làm MỘT lần):\n"
        "  - từ máy local: copy thư mục backend/data lên Drive, đổi tên thành aic_data\n"
        "  - hoặc tải thẳng trên Colab:\n"
        "      !pip install -q kaggle && mkdir -p ~/.kaggle\n"
        "      # đưa kaggle.json vào ~/.kaggle rồi:\n"
        f"      !kaggle datasets download -d nguynlngnamanh/data-media --unzip -p {DRIVE_DATA}/..\n"
        "    (chỉ cần thư mục data/ - media/ KHÔNG cần lên Colab, nó ở máy bạn)"
    )

os.makedirs(DRIVE_ROOM, exist_ok=True)

# --- 2. Repo ------------------------------------------------------------------
# Colab kéo code từ GitHub, nên nhánh PHẢI đã được push. Commit chỉ nằm ở máy
# local thì Colab không thấy - và lỗi git thô rất khó đoán ra nguyên nhân này.
probe = subprocess.run(
    ["git", "ls-remote", "--heads", REPO_URL, BRANCH],
    capture_output=True, text=True,
)
if probe.returncode != 0 or not probe.stdout.strip():
    raise SystemExit(
        f"Nhánh '{BRANCH}' không có trên {REPO_URL}.\n"
        f"Ở máy local, đẩy nó lên trước:\n"
        f"    git push -u origin {BRANCH}\n"
        "Rồi chạy lại cell này. (Hoặc sửa BRANCH ở đầu cell cho đúng nhánh đã push.)"
    )

if os.path.isdir(os.path.join(WORKDIR, ".git")):
    subprocess.run(["git", "-C", WORKDIR, "fetch", "--all", "-q"], check=True)
    subprocess.run(["git", "-C", WORKDIR, "checkout", "-q", BRANCH], check=True)
    subprocess.run(["git", "-C", WORKDIR, "pull", "-q"], check=True)
else:
    subprocess.run(
        ["git", "clone", "-q", "--branch", BRANCH, REPO_URL, WORKDIR], check=True
    )
BACKEND = os.path.join(WORKDIR, "backend")

# --- 3. Thư viện --------------------------------------------------------------
# faiss-cpu là đủ: index đọc từ RAM, GPU để dành cho encoder/reranker.
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-r",
     os.path.join(BACKEND, "requirements.txt"), "pyngrok"],
    check=True,
)

# --- 4. Nối data từ Drive -----------------------------------------------------
# Symlink chứ không copy: 6.5GB mỗi phiên là phí, và Colab đọc thẳng từ Drive được.
data_link = os.path.join(BACKEND, "data")
if os.path.islink(data_link):
    os.unlink(data_link)
elif os.path.isdir(data_link):
    raise SystemExit(f"{data_link} là thư mục thật - xoá hoặc đổi tên rồi chạy lại.")
os.symlink(DRIVE_DATA, data_link)

# --- 5. Biến môi trường -------------------------------------------------------
# backend/config.py đọc qua pydantic-settings nên os.environ là đủ, không cần .env.
# LƯU Ý: Settings đặt extra="ignore" - gõ SAI TÊN biến thì bị nuốt im lặng, không
# báo gì. Mọi tên dưới đây đối chiếu trực tiếp với các trường trong config.py.
os.environ["MEDIA_BASE_URL"] = FE_TUNNEL_URL

# ⚠ GIỎ ĐÁP ÁN CỦA CẢ NHÓM. Mặc định ROOM_DIR=./room_state nằm trong filesystem
# TẠM của Colab - hết phiên là mất sạch bài của cả buổi thi. Phải để trên Drive.
os.environ["ROOM_ENABLED"] = "true"
os.environ["ROOM_DIR"] = DRIVE_ROOM

# Cho tunnel lên sớm: warm-up (~2 phút, hàng GB weight) chạy ở thread nền, server
# nhận request ngay. Nếu chặn thì ngrok dễ bị coi là backend chết.
os.environ["WARMUP_ON_STARTUP"] = "true"
os.environ["WARMUP_BACKGROUND"] = "true"

# CORS: browser mở FE ở localhost:5173 nên Origin gửi lên là localhost - vốn đã
# nằm trong mặc định. Chỉ khi có người mở FE BẰNG URL tunnel mới cần thêm nó vào.
# (Việc Colab fetch ảnh từ FE là request server-side, KHÔNG dính CORS.)
# Đừng đặt "*": kèm allow_credentials=True là cặp trình duyệt từ chối.
os.environ["CORS_ORIGINS"] = f"http://localhost:5173,http://localhost:4173,{FE_TUNNEL_URL}"

# --- 6. Bật server ------------------------------------------------------------
log = open("/content/backend.log", "w")
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app",
     "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
    cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy(),
)

# --- 7. Tunnel ----------------------------------------------------------------
# Authtoken: Colab > 🔑 Secrets > khoá tên NGROK_TOKEN (bật Notebook access),
# lấy ở https://dashboard.ngrok.com/get-started/your-authtoken
from pyngrok import conf, ngrok

tok = ""
try:
    from google.colab import userdata

    tok = (userdata.get("NGROK_TOKEN") or "").strip()
except Exception:
    pass
if not tok:
    from getpass import getpass

    tok = getpass("ngrok authtoken: ").strip()
conf.get_default().auth_token = tok

be_url = ngrok.connect(BACKEND_PORT, "http").public_url.replace("http://", "https://")

# --- 8. Chờ sống rồi báo cáo --------------------------------------------------
def _health():
    req = urllib.request.Request(
        f"http://127.0.0.1:{BACKEND_PORT}/health",
        headers={"ngrok-skip-browser-warning": "true"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        import json

        return json.load(r)


print("\nĐang chờ backend nhận request...")
for _ in range(60):
    if server.poll() is not None:
        print(open("/content/backend.log").read()[-3000:])
        raise SystemExit("Backend CHẾT lúc khởi động - log ở trên.")
    try:
        h = _health()
        break
    except Exception:
        time.sleep(2)
else:
    print(open("/content/backend.log").read()[-3000:])
    raise SystemExit("Backend không phản hồi /health sau 2 phút - log ở trên.")

print("=" * 68)
print(f"  Backend:  {be_url}")
print(f"  Warm-up:  {h['warmup']}  (ready={h['ready']})")
print(f"  Giỏ nhóm: {DRIVE_ROOM}  (trên Drive - sống qua phiên Colab)")
print("=" * 68)
print("\nTRÊN MÁY LOCAL, mở FE rồi vào Cài đặt (⚙) > Backend URL, dán:")
print(f"    {be_url}")
print("\nWarm-up chạy nền ~2 phút. Theo dõi:")
print("    !tail -f /content/backend.log")
print(f"    hoặc mở {be_url}/warmup")
print("\nKIỂM TRA ĐƯỜNG ẢNH (quan trọng - hỏng ở đây là rerank/QA chạy mù):")
print(f"    !curl -sI {FE_TUNNEL_URL}/media/frames/Keyframes/L21/L21_V001/000000.webp | head -3")
print("    phải thấy 'content-type: image/webp'. Ra text/html = sai FE_TUNNEL_URL,")
print("    hoặc Vite chưa restart sau khi thêm public/media.")
