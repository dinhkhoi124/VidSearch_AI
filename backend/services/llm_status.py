"""Trạng thái hạn mức (quota) của LLM — để giao diện cảnh báo khi key hết lượt.

Free tier Gemini cạn lượt (429 RESOURCE_EXHAUSTED) là chuyện xảy ra GIỮA buổi
thi. Mọi service dùng LLM đều degrade êm theo thiết kế — query_expansion trả
None (giữ query tiếng Việt), plan_from_dialogue rơi về "câu cuối = query",
answer_question trả câu xin lỗi — nên ngoài giao diện KHÔNG có dấu hiệu nào:
người dùng chỉ thấy kết quả tự dưng kém đi và không hiểu tại sao.

Module này giữ sự kiện cạn quota gần nhất. main.py gắn nó vào header của MỌI
response (X-Llm-Quota / X-Llm-Quota-Info) nên frontend biết ngay ở request kế
tiếp mà không phải polling; GET /agent/llm_status trả bản đầy đủ cho lúc mở
trang.

Chỉ nhớ trong process — restart backend là quên, đúng ý: lúc đó key có thể đã
được đổi hoặc quota ngày đã reset.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

_lock = threading.Lock()
_state: Optional[dict] = None


def note_quota(
    provider: str,
    model: str = "",
    detail: str = "",
    scope: str = "unknown",
    retry_after_s: Optional[float] = None,
) -> None:
    """Ghi nhận provider vừa bị chặn vì hết lượt.

    scope: "day" (hết hạn mức ngày — hết cứu tới khi reset), "minute" (vượt
    RPM, chờ chút là chạy lại), "unknown" (không bóc được từ body lỗi).
    """
    global _state
    now = time.time()
    with _lock:
        prev = _state if _state and _state["provider"] == provider else None
        _state = {
            "provider": provider,
            "model": model or "",
            "detail": (detail or "").strip()[:400],
            "scope": scope,
            "retry_after_s": retry_after_s,
            # since = lần ĐẦU của chuỗi lỗi hiện tại; frontend dùng nó làm khoá
            # "cảnh báo mới" để banner đã tắt hiện lại khi sự cố khác xảy ra.
            "since": prev["since"] if prev else now,
            "last": now,
            "count": (prev["count"] + 1) if prev else 1,
        }
    print(f"[llm-quota] {provider} hết lượt (scope={scope}) — {detail[:160]}")


def note_ok(provider: str) -> None:
    """Provider vừa trả lời thành công -> xoá cảnh báo của chính nó."""
    global _state
    with _lock:
        if _state and _state["provider"] == provider:
            print(f"[llm-quota] {provider} trả lời lại được — gỡ cảnh báo")
            _state = None


def _fallback_available(provider: str) -> bool:
    """Còn provider nào khác để đỡ không (quyết định giọng của cảnh báo)."""
    try:
        from services import agent_service as agent

        if provider == "gemini":
            return agent._openai_configured()
        return bool((agent.settings.gemini_api_key or "").strip())
    except Exception:  # noqa: BLE001 — trạng thái phụ, không được làm vỡ request
        return False


def snapshot() -> dict:
    """Bản đầy đủ cho /agent/llm_status."""
    with _lock:
        state = dict(_state) if _state else None
    if not state:
        return {"exhausted": False}
    return {"exhausted": True, "fallback": _fallback_available(state["provider"]), **state}


def _ascii(text: str) -> str:
    # Header HTTP chỉ tải được latin-1; giá trị ở đây vốn là ASCII (tên
    # provider/model, số) nhưng lọc cho chắc — một ký tự lạ là uvicorn ném lỗi
    # khi ghi response.
    return "".join(c for c in text if 32 <= ord(c) < 127)


def headers() -> Dict[str, str]:
    """Header gắn vào mọi response. Luôn có X-Llm-Quota để frontend biết cả lúc
    ĐÃ HẾT sự cố (giá trị "ok") mà gỡ banner xuống."""
    state = snapshot()
    if not state["exhausted"]:
        return {"X-Llm-Quota": "ok"}
    info = (
        f"provider={state['provider']};model={state['model']};"
        f"scope={state['scope']};since={int(state['since'])};"
        f"count={state['count']};fallback={1 if state['fallback'] else 0}"
    )
    if state.get("retry_after_s"):
        info += f";retry={int(state['retry_after_s'])}"
    return {"X-Llm-Quota": "exhausted", "X-Llm-Quota-Info": _ascii(info)}
