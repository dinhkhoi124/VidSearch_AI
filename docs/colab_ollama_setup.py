# Colab - 1 cell: dựng Ollama cạnh backend làm LLM chính (thay Gemini).
#
# Chạy TRƯỚC cell bật backend. Cùng máy với backend nên payload QA (12 keyframe
# ≈ 820 KB base64) đi qua localhost, không phải tunnel.
#
# Backend không cần sửa code - nó nói chuẩn /chat/completions. Sau khi cell này
# chạy xong, đặt trong backend/.env (hoặc os.environ ở cell sau):
#     LLM_PROVIDER=openai_first
#     OPENAI_BASE_URL=http://localhost:11434/v1
#     OPENAI_API_KEY=ollama
#     OPENAI_MODEL=aic-llm
#     OPENAI_QA_MODEL=aic-llm
# openai_first chứ KHÔNG phải openai: hụt GPU to hay Ollama chưa nạp xong thì
# vẫn còn Gemini đỡ. Đặt "openai" là mất lưới an toàn.

# @title Dựng Ollama trên GPU Colab
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Tag model trên ollama.com/library. PHẢI là model vision nếu muốn bước QA chạy
# - QA gửi 12 ảnh; model text-thuần sẽ trả lỗi và backend rơi về Gemini.
BASE_MODEL = "qwen3-vl:32b"        # đổi theo tag thật đang có
CUSTOM_TAG = "aic-llm"             # tên sau khi gắn num_ctx, dùng ở OPENAI_MODEL
NUM_CTX = 32768
USE_DRIVE = True                   # lưu weight lên Drive: session sau khỏi pull lại

# --- 0. Kiểm tra GPU trước khi tải hàng chục GB ------------------------------
try:
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
         "--format=csv,noheader"],
        capture_output=True, text=True, check=True).stdout.strip()
    print("GPU:", smi)
    free_mib = int(smi.split(",")[-1].strip().split()[0])
except Exception as e:
    print(f"Không đọc được nvidia-smi ({e!r}) - có thể đang ở runtime CPU.")
    free_mib = 0

# Stack retrieval của backend chiếm ~6,5 GB; con số dưới là phần CÒN LẠI cần có.
NEEDED_MIB = {"32b": 20_000, "27b": 18_000, "45b": 30_000, "8b": 6_000}
hint = next((v for k, v in NEEDED_MIB.items() if k in BASE_MODEL.lower()), 18_000)
if free_mib and free_mib < hint + 6_500:
    print(f"CẢNH BÁO: còn {free_mib} MiB trống, {BASE_MODEL} cần ~{hint} MiB và "
          f"backend cần thêm ~6.500 MiB. Ollama sẽ đẩy bớt sang CPU -> rất chậm. "
          f"Đổi sang model nhỏ hơn, hoặc dùng LLM_PROVIDER=auto để Gemini chạy chính.")

# --- 1. Cache weight lên Drive ------------------------------------------------
if USE_DRIVE:
    from google.colab import drive

    drive.mount("/content/drive")
    os.environ["OLLAMA_MODELS"] = "/content/drive/MyDrive/ollama_models"
    os.makedirs(os.environ["OLLAMA_MODELS"], exist_ok=True)
    print("OLLAMA_MODELS =", os.environ["OLLAMA_MODELS"],
          "(Drive đọc ~50-100 MB/s, nạp lần đầu mỗi session vẫn mất vài phút)")

# --- 2. Cài + chạy server -----------------------------------------------------
if subprocess.run(["which", "ollama"], capture_output=True).returncode != 0:
    subprocess.run("curl -fsSL https://ollama.com/install.sh | sh",
                   shell=True, check=True)

# Giữ model nằm lại trong VRAM giữa các request; mặc định Ollama nhả sau 5 phút
# và request kế tiếp phải nạp lại hàng chục GB.
os.environ["OLLAMA_KEEP_ALIVE"] = "-1"
os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"

server = subprocess.Popen(["ollama", "serve"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        print("Ollama đã sẵn sàng.")
        break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError("Ollama không lên sau 60s - xem lại bước cài.")

# --- 3. Kéo model + gắn num_ctx ----------------------------------------------
print(f"Kéo {BASE_MODEL} (lần đầu có thể vài chục GB)…")
subprocess.run(["ollama", "pull", BASE_MODEL], check=True)

# num_ctx là cái bẫy lớn nhất: mặc định của Ollama là 4096, mà QA gửi 12 keyframe
# 1280x720 ≈ 18-20k token phần vision. Vượt ngưỡng thì Ollama CẮT IM LẶNG -
# không lỗi, không cảnh báo - và model trả lời dựa trên vài frame đầu rồi bịa
# phần còn lại. Không thể đặt qua API /chat/completions nên phải nướng vào tag.
modelfile = f"FROM {BASE_MODEL}\nPARAMETER num_ctx {NUM_CTX}\n"
with open("/content/Modelfile.aic", "w") as f:
    f.write(modelfile)
subprocess.run(["ollama", "create", CUSTOM_TAG, "-f", "/content/Modelfile.aic"],
               check=True)
print(f"Đã tạo tag {CUSTOM_TAG} với num_ctx={NUM_CTX}")

# --- 4. Kiểm chứng đúng đường mà backend sẽ đi -------------------------------
# Gọi thẳng /v1/chat/completions với một ảnh data URL - cùng format
# services/agent_service.py::_openai_generate dựng.
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
body = {
    "model": CUSTOM_TAG,
    "temperature": 0.0,
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": 'Reply with ONLY this JSON: {"ok": true}'},
        {"type": "image_url", "image_url": {"url": PIXEL}},
    ]}],
}
req = urllib.request.Request(
    "http://127.0.0.1:11434/v1/chat/completions",
    data=__import__("json").dumps(body).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
    method="POST")
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        out = __import__("json").loads(r.read())
    print("Trả lời thử:", out["choices"][0]["message"]["content"][:200])
    print("=> Đường vision + JSON chạy được. Đặt LLM_PROVIDER=openai_first ở cell sau.")
except urllib.error.HTTPError as e:
    print(f"LỖI {e.code}: {e.read()[:300]}")
    print("=> Nhiều khả năng model không nhận ảnh. Giữ LLM_PROVIDER=auto để "
          "Gemini lo QA, hoặc đặt OPENAI_QA_MODEL sang một tag vision khác.")
except Exception as e:
    print(f"LỖI: {e!r}")

# --- 5. Nhắc kiểm tra num_ctx bằng dữ liệu thật ------------------------------
print("\nSau khi backend chạy: hỏi QA một câu mà đáp án CHỈ có ở frame thứ 10-12.")
print("Sai đều đặn = đang bị cắt context, tăng NUM_CTX rồi ollama create lại.")
