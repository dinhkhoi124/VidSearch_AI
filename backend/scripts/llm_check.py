"""Kiểm tra cấu hình LLM trước giờ thi - key có sống, model có nhận ảnh không.

    python scripts/llm_check.py           # kiểm cả 4 nhiệm vụ, có gọi mạng thật
    python scripts/llm_check.py --dry     # chỉ in cấu hình, KHÔNG gọi mạng

LLM là chỗ hỏng ÂM THẦM: mọi lỗi đều trả None và caller tự rơi về fallback, nên
sai key / sai tên model / model text-thuần nhận ảnh đều cho ra cùng một triệu
chứng "agent trả lời nhạt" chứ không phải một thông báo lỗi. Script này gọi thật
từng nhiệm vụ rồi nói rõ cái nào chết vì sao.

Bốn nhiệm vụ, đúng thứ tự rủi ro tăng dần:
  expand  text ngắn  - chắn ngang MỌI câu search, nên đo cả độ trễ
  plan    text, JSON nhiều field
  react   text, JSON - model suy luận
  qa      VISION     - gửi 1 ảnh thật; đây là bước hay chết nhất

Tốn khoảng $0.001. Không nạp model, không cần GPU.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402

# PNG 2x2 đỏ thuần - đủ để biết endpoint có chịu nhận image_url hay không.
_RED_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFUlEQVR4nGP8z4AAT"
    "AwMDAwMDAwMDAAOPQEBaXvGCwAAAABJRU5ErkJggg=="
)

# (task, mô tả, parts, ngưỡng cảnh báo độ trễ giây)
_CASES = [
    ("expand", "dịch + mở rộng query (chạy trên MỌI câu search)",
     [{"text": 'Translate to English and reply JSON only: '
               '{"queries":["<dịch câu: người đàn ông mặc áo đỏ>"]}'}], 5.0),
    ("plan", "planner hội thoại",
     [{"text": 'Reply JSON only: {"mode":"search","query":"a red car on a street"}'}], 15.0),
    ("react", "vòng ReAct",
     [{"text": 'Reply JSON only: {"thought":"ok","final":{"reply":"xong"}}'}], 30.0),
    ("qa", "RAG QA - GỬI ẢNH (bước ăn điểm)",
     [{"text": 'What color is this image? Reply JSON only: {"answer":"<color>"}'},
      {"inline_data": {"mime_type": "image/png",
                       "data": base64.b64encode(_RED_PNG).decode()}}], 60.0),
]


def _gemini_model_for(settings, task: str) -> str:
    """Model phía GEMINI cho từng nhiệm vụ - phải khớp ĐÚNG cái call site thật
    truyền vào, nếu không script sẽ kiểm nhầm model và bỏ sót tên model đã chết.
    Xem agent_service.answer_question / react_refine."""
    per_task = {
        "react": settings.gemini_react_model,
        "qa": settings.gemini_qa_model,
    }.get(task, "")
    return (per_task or "").strip() or settings.gemini_model


def _print_config(settings, A) -> None:
    provider = (settings.llm_provider or "auto").strip().lower()
    order = {
        "auto": "gemini -> openai",
        "openai_first": "openai -> gemini",
        "gemini": "chỉ gemini (không có đường lui)",
        "openai": "chỉ openai (không có đường lui)",
    }.get(provider, provider + "?")
    print(f"provider   : {provider}  [{order}]")
    print(f"gemini     : {settings.gemini_model}  "
          f"{'có key' if settings.gemini_api_key.strip() else 'THIẾU key'}")
    print(f"openai     : {A._openai_host()}  "
          f"{'có key' if settings.openai_api_key.strip() else 'THIẾU key'}")
    print(f"json_mode  : {settings.openai_json_mode}   "
          f"timeout={settings.llm_timeout_s}s  retry={settings.llm_max_retries}")
    for task, desc, _, _ in _CASES:
        print(f"  {task:7s} openai={A._openai_model_for(task) or '-':32s} "
              f"gemini={_gemini_model_for(settings, task):24s} "
              f"reasoning={A._openai_reasoning_for(task) or '(không gửi)'}")


def main() -> int:
    settings = get_settings()
    from services import agent_service as A

    _print_config(settings, A)

    if "--dry" in sys.argv:
        return 0
    if not A.is_available():
        print("\nKHÔNG có provider nào khả dụng -> mọi tính năng LLM đang tắt.")
        print("Đặt OPENAI_API_KEY (và/hoặc GEMINI_API_KEY) trong backend/.env.")
        return 1

    print("\n--- gọi thật (mỗi dòng [llm] bên dưới là một lỗi có thật) ---")
    failed = []
    for task, desc, parts, budget in _CASES:
        t0 = time.time()
        text = A._gemini_generate(parts, temperature=0.0,
                                  model=_gemini_model_for(settings, task), task=task)
        dt = time.time() - t0

        if text is None:
            print(f"[FAIL] {task:7s} {dt:5.1f}s  {desc}")
            failed.append(task)
            continue
        # Không ép phải parse được: prompt ở đây cố tình sơ sài, mục tiêu là biết
        # endpoint có TRẢ VỀ gì không. Nhưng JSON hỏng vẫn đáng nói.
        try:
            json.loads(text)
            shape = "JSON hợp lệ"
        except ValueError:
            shape = f"KHÔNG parse được JSON: {text[:60]!r}"
        warn = "  <-- CHẬM" if dt > budget else ""
        print(f"[ OK ] {task:7s} {dt:5.1f}s  {shape}{warn}")

    print()
    if not failed:
        print("Tất cả nhiệm vụ đều sống.")
        return 0

    print(f"Hỏng: {', '.join(failed)}")
    if "qa" in failed:
        print("  qa hỏng thường là model KHÔNG nhận ảnh -> đổi OPENAI_QA_MODEL")
        print("  sang một model vision, hoặc để Gemini lo QA.")
    if failed == [t for t, _, _, _ in _CASES]:
        print("  Hỏng CẢ 4 -> nhiều khả năng sai key hoặc sai OPENAI_BASE_URL.")
        print("  Xem mã lỗi ở dòng [llm] phía trên: 401=key sai, 402=hết credit,")
        print("  404=sai tên model.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
