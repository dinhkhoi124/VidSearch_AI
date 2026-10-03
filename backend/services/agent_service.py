"""Conversational agent - dialogue processing + RAG question answering (Gemini).

Two capabilities modelled on MemoriEase 2.0/3.0 (Tran et al., LSC'24/'25):

  plan_from_dialogue  The whole chat history is aggregated into ONE structured
                      query (§3.2 "automatic filter extraction"): the LLM
                      splits the request into a visual query (English - every
                      visual backbone is English-biased), OpenImages object
                      labels, on-screen/spoken keywords, and detects event
                      sequences ("... sau đó ..." -> temporal mode).
  answer_question     RAG for the QA task (§3.4): the candidate keyframes are
                      sent AS IMAGES to Gemini vision together with each
                      scene's OCR/ASR text and timestamp - no offline caption
                      generation needed (MemoriEase had to caption 725k images
                      with InstructBLIP because its LLM was text-only).

Both degrade gracefully: without GEMINI_API_KEY plan_from_dialogue falls back
to "last user message = visual query" and answer_question returns an apology
string - the API never breaks because of this service.
"""
from __future__ import annotations

import base64
import json
from typing import Dict, List, Optional

from config import get_settings
from services import llm_status

settings = get_settings()

_TIMEOUT_S = 120  # mặc định lịch sử; đường chạy thật đọc settings.llm_timeout_s

# Model mà endpoint đã TỪ CHỐI một field tuỳ chọn -> lần sau khỏi gửi lại. Nhớ ở
# cấp tiến trình để chỉ tốn ĐÚNG MỘT round-trip thừa cho mỗi model, thay vì mỗi call.
_NO_JSON_MODE: set = set()
_NO_REASONING: set = set()


def _http_err_detail(e) -> str:
    """Body của HTTPError. OpenRouter đặt lý do THẬT ở đây - hết credit, sai
    model id, model không nhận ảnh - trong khi repr(e) chỉ cho thấy mã số, khiến
    ba sự cố hoàn toàn khác nhau trông giống hệt nhau trong log."""
    try:
        return e.read().decode("utf-8", "replace").strip()[:300]
    except Exception:  # noqa: BLE001 - body đã bị đọc mất thì thôi
        return ""


def _log_llm(provider: str, task: str, model: str, msg: str) -> None:
    print(f"[llm] {provider} task={task or '?'} model={model or '?'} {msg}")


def _openai_host() -> str:
    """Host của endpoint, để log phân biệt được openrouter/ollama/orcarouter."""
    import urllib.parse

    try:
        return urllib.parse.urlsplit(settings.openai_base_url).hostname or "openai"
    except Exception:  # noqa: BLE001
        return "openai"


def _quota_info(err, body: str = "") -> dict:
    """Bóc thông tin quota từ body của một HTTPError 429.

    Gemini trả {"error": {"message": ..., "details": [QuotaFailure, RetryInfo]}}.
    Cần phân biệt hết-hạn-mức-NGÀY với vượt-RPM: cái đầu thì retry chỉ tốn thêm
    một phút chờ vô ích, cái sau đợi vài chục giây là chạy lại được.

    `body` đọc sẵn: body của HTTPError chỉ đọc được MỘT lần, mà caller đã đọc nó
    qua _http_err_detail() để ghi log. Không truyền vào thì err.read() ở đây trả
    chuỗi rỗng và mọi phát hiện quota im lặng hỏng.
    """
    if not body:
        try:
            body = err.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - body đã bị đọc hoặc stream hỏng
            body = ""

    detail, retry, scope = body[:400], None, "unknown"
    try:
        error = json.loads(body).get("error", {})
        detail = error.get("message") or detail
        for d in error.get("details") or []:
            kind = str(d.get("@type", ""))
            if kind.endswith("RetryInfo"):
                raw = str(d.get("retryDelay", "")).rstrip("s")
                if raw.replace(".", "", 1).isdigit():
                    retry = float(raw)
            elif kind.endswith("QuotaFailure"):
                for v in d.get("violations") or []:
                    tag = f"{v.get('quotaId', '')} {v.get('quotaMetric', '')}".lower()
                    tag = tag.replace("_", "").replace(" ", "")
                    if "perday" in tag:
                        scope = "day"
                    elif "perminute" in tag and scope == "unknown":
                        scope = "minute"
    except Exception:  # noqa: BLE001 — body không phải JSON -> đoán từ chữ
        pass

    if scope == "unknown":
        low = detail.lower()
        if "per day" in low or "perday" in low or "daily" in low:
            scope = "day"
        elif "per minute" in low or "perminute" in low:
            scope = "minute"
    return {"scope": scope, "detail": detail, "retry_after_s": retry}


def _openai_configured() -> bool:
    return bool((settings.openai_api_key or "").strip()
                and (settings.openai_base_url or "").strip()
                and (settings.openai_model or "").strip())


def is_available() -> bool:
    # Đủ MỘT trong hai provider là agent sống (planner/QA/ReAct).
    return bool((settings.gemini_api_key or "").strip()) or _openai_configured()


def key_hint(api_key: str) -> str:
    """4 ký tự cuối để đối chiếu key nào đang chạy. KHÔNG bao giờ trả/ghi log
    key đầy đủ — backend hay chạy sau tunnel công khai."""
    api_key = (api_key or "").strip()
    return f"…{api_key[-4:]}" if len(api_key) >= 4 else ("(rỗng)" if not api_key else "…")


def verify_gemini_key(api_key: str) -> Optional[str]:
    """Thử key bằng models.list (không tốn quota generateContent).

    None = dùng được. Khác None = câu lỗi tiếng Việt để trả thẳng cho người dùng.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    url = ("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1&key="
           + urllib.parse.quote(api_key))
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            json.loads(resp.read().decode("utf-8"))
        return None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            # Key thật, chỉ là đang bị siết — vẫn cho đổi: có thể là hạn mức của
            # riêng models.list, và quota generateContent mới là thứ cần.
            return None
        if e.code in (400, 401, 403):
            return "Key không hợp lệ hoặc chưa bật Generative Language API cho project."
        return f"Google trả lỗi {e.code} khi kiểm tra key."
    except Exception as e:  # noqa: BLE001 — mạng hỏng, tunnel chết...
        return f"Không gọi được Google để kiểm tra key ({e.__class__.__name__})."


def set_gemini_key(api_key: str, model: str = "") -> dict:
    """Thay key Gemini cho tiến trình đang chạy. Ném ValueError nếu key hỏng.

    Chỉ sống trong RAM: restart backend là quay về GEMINI_API_KEY trong .env.
    Cố ý — ghi secret xuống đĩa từ một endpoint HTTP là chuyện khác hẳn, và
    trong lúc thi thì thứ cần là đổi key trong 5 giây chứ không phải bền vững.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("Chưa nhập key.")

    error = verify_gemini_key(api_key)
    if error:
        raise ValueError(error)

    settings.gemini_api_key = api_key
    if (model or "").strip():
        settings.gemini_model = model.strip()

    # Key mới -> cảnh báo hết lượt của key cũ không còn đúng nữa.
    llm_status.note_ok("gemini")
    # Cache mở rộng query nhớ cả những lần THẤT BẠI (None = "dùng query gốc").
    # Không dọn thì mọi query đã hỏng lúc cạn quota vẫn hỏng với key mới.
    from services import query_expansion_service

    dropped = query_expansion_service.clear_failed_cache()

    print(f"[llm-key] đổi key gemini -> {key_hint(api_key)}, "
          f"model={settings.gemini_model}, dọn {dropped} cache expansion hỏng")
    return {"key_hint": key_hint(api_key), "model": settings.gemini_model}


# --- Đổi provider / model LLM lúc đang chạy --------------------------------
# Cùng lý do với set_gemini_key ở trên: restart backend mất ~10 phút nạp lại
# model visual, mà thứ hỏng giữa buổi thi thường là phía LLM - OpenRouter hết
# credit, Ollama trên Colab bị ngắt, model text-thuần chết ở bước QA vì phải
# nhận ảnh. Đổi được provider/model ngay trên giao diện thì sự cố đó tốn 5 giây
# thay vì 10 phút. Mọi thay đổi CHỈ nằm trong RAM - restart là quay về .env.

LLM_PROVIDERS = ("auto", "openai_first", "gemini", "openai")


def llm_config_snapshot() -> dict:
    """Cấu hình LLM đang chạy, ĐÃ che key (chỉ 4 ký tự cuối).

    effective_react/effective_qa là thứ THỰC SỰ được gửi đi: hai field riêng
    theo nhiệm vụ rỗng thì rơi về openai_model, mà nhìn ô rỗng trên giao diện
    không ai đoán ra điều đó.
    """
    return {
        "provider": (settings.llm_provider or "auto").strip().lower(),
        "providers": list(LLM_PROVIDERS),
        "can_edit": settings.allow_runtime_llm_key,
        "gemini": {
            "configured": bool((settings.gemini_api_key or "").strip()),
            "key_hint": key_hint(settings.gemini_api_key),
            "model": settings.gemini_model,
        },
        "openai": {
            "configured": _openai_configured(),
            "base_url": settings.openai_base_url,
            "host": _openai_host(),
            "key_hint": key_hint(settings.openai_api_key),
            "model": settings.openai_model,
            "react_model": settings.openai_react_model,
            "qa_model": settings.openai_qa_model,
            "effective_react": _openai_model_for("react"),
            "effective_qa": _openai_model_for("qa"),
            "max_tokens": settings.openai_max_tokens,
        },
    }


def set_llm_config(
    provider: Optional[str] = None,
    openai_model: Optional[str] = None,
    openai_react_model: Optional[str] = None,
    openai_qa_model: Optional[str] = None,
    openai_base_url: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> dict:
    """Đổi provider và/hoặc cấu hình OpenAI-compat cho tiến trình đang chạy.

    None = GIỮ NGUYÊN field đó. Chuỗi rỗng = XOÁ field đó (react/qa rỗng nghĩa
    là dùng lại openai_model) - phân biệt hai thứ này là lý do tham số phải là
    Optional chứ không phải str mặc định rỗng.

    Ném ValueError với câu tiếng Việt nếu cấu hình MỚI sẽ làm agent câm: mọi
    caller LLM đều degrade êm, nên đổi sang một provider không có key thì ngoài
    giao diện chỉ thấy kết quả tự dưng kém đi, không có lỗi nào hiện ra.
    """
    def pick(new: Optional[str], cur: str) -> str:
        return cur if new is None else (new or "").strip()

    new_provider = pick(provider, settings.llm_provider or "auto").lower() or "auto"
    new_base = pick(openai_base_url, settings.openai_base_url)
    new_key = pick(openai_api_key, settings.openai_api_key)
    new_model = pick(openai_model, settings.openai_model)
    new_react = pick(openai_react_model, settings.openai_react_model)
    new_qa = pick(openai_qa_model, settings.openai_qa_model)

    if new_provider not in LLM_PROVIDERS:
        raise ValueError(
            f"Provider '{new_provider}' không hợp lệ. Chọn một trong: "
            + ", ".join(LLM_PROVIDERS) + "."
        )

    has_gemini = bool((settings.gemini_api_key or "").strip())
    has_openai = bool(new_base and new_key and new_model)

    if new_provider == "gemini" and not has_gemini:
        raise ValueError("Chọn 'gemini' nhưng backend không có key Gemini nào. "
                         "Dán key ở ô Gemini API key phía trên trước.")
    if new_provider == "openai" and not has_openai:
        missing = [n for n, v in (("base URL", new_base), ("API key", new_key),
                                  ("model", new_model)) if not v]
        raise ValueError("Chọn 'openai' (không có đường lui) nhưng endpoint "
                         "OpenAI-compat còn thiếu: " + ", ".join(missing) + ".")
    if not has_gemini and not has_openai:
        raise ValueError("Không provider nào đủ cấu hình - agent sẽ không gọi "
                         "được LLM. Nhập key trước rồi hãy đổi provider.")

    base_changed = new_base != (settings.openai_base_url or "")
    model_changed = (new_model, new_react, new_qa) != (
        settings.openai_model, settings.openai_react_model, settings.openai_qa_model)
    provider_changed = new_provider != (settings.llm_provider or "auto").strip().lower()

    settings.llm_provider = new_provider
    settings.openai_base_url = new_base
    settings.openai_api_key = new_key
    settings.openai_model = new_model
    settings.openai_react_model = new_react
    settings.openai_qa_model = new_qa

    # Đổi endpoint = CÙNG tên model có thể là model khác hẳn, nên hai bộ nhớ
    # "model này không nhận field X" học được từ endpoint cũ hết đúng. Chỉ đổi
    # tên model thì giữ - chúng vẫn khoá theo đúng model đó.
    if base_changed:
        _NO_JSON_MODE.clear()
        _NO_REASONING.clear()

    # Cùng lý do với set_gemini_key: cache mở rộng query nhớ cả những lần THẤT
    # BẠI, không dọn thì query đã hỏng với cấu hình cũ vẫn hỏng với cấu hình mới.
    dropped = 0
    if provider_changed or model_changed or base_changed:
        llm_status.note_ok("openai")
        llm_status.note_ok("gemini")
        from services import query_expansion_service

        dropped = query_expansion_service.clear_failed_cache()

    print(f"[llm-config] provider={new_provider} host={_openai_host()} "
          f"model={new_model or '(rỗng)'} react={_openai_model_for('react') or '(rỗng)'} "
          f"qa={_openai_model_for('qa') or '(rỗng)'} key={key_hint(new_key)}, "
          f"dọn {dropped} cache expansion hỏng")

    config = llm_config_snapshot()
    label = {
        "auto": "Gemini chạy chính, OpenAI-compat đỡ khi hỏng",
        "openai_first": "OpenAI-compat chạy chính, Gemini đỡ khi hỏng",
        "gemini": "CHỈ Gemini, không có đường lui",
        "openai": "CHỈ OpenAI-compat, không có đường lui",
    }[new_provider]
    # Chỉ nhắc model của BÊN sẽ thật sự chạy: nói "Model: qwen..." khi vừa ép
    # cứng sang gemini thì câu xác nhận mô tả sai thứ vừa được đặt.
    if new_provider == "gemini":
        used = f"Model: {settings.gemini_model}. "
    else:
        used = f"Model: {new_model or '(chưa đặt)'}. "
    return {
        "config": config,
        "message": f"Đã đổi sang {new_provider} - {label}. " + used
                   + "Chỉ nằm trong RAM - restart backend là quay về .env.",
    }


def _openai_generate(
    parts: List[dict],
    temperature: float = 0.3,
    model: Optional[str] = None,
    task: str = "",
) -> Optional[str]:
    """Một call /chat/completions OpenAI-compatible; parts CÙNG format với
    _gemini_call ({"text"} | {"inline_data"}) để hai provider hoán đổi được.

    Ảnh gửi dạng data URL - model text-thuần sẽ trả lỗi (caller nhận None).
    `model` là tên model PHÍA OPENAI, do router tra sẵn theo nhiệm vụ
    (_openai_model_for); rỗng thì dùng settings.openai_model. `task` chỉ dùng để
    tra ngân sách thinking và để log nói rõ bước nào hỏng.

    Hai field tuỳ chọn (response_format, reasoning) được gửi kèm nếu cấu hình bật.
    Endpoint nào không hiểu chúng trả 400; khi đó ta GỠ field rồi gửi lại ngay -
    lần retry đó KHÔNG tính vào ngân sách retry, vì đây là lỗi cấu hình đã tự sửa
    được chứ không phải sự cố mạng.
    """
    import time
    import urllib.error
    import urllib.request

    content: List[dict] = []
    for p in parts:
        if "text" in p:
            content.append({"type": "text", "text": p["text"]})
        elif "inline_data" in p:
            d = p["inline_data"]
            content.append({"type": "image_url", "image_url": {
                "url": f"data:{d['mime_type']};base64,{d['data']}"}})

    mdl = (model or "").strip() or settings.openai_model
    host = _openai_host()
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"

    json_mode = (settings.openai_json_mode or "auto").strip().lower()
    want_json = json_mode != "off" and mdl not in _NO_JSON_MODE
    effort = _openai_reasoning_for(task)
    want_reasoning = bool(effort) and mdl not in _NO_REASONING

    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {settings.openai_api_key}"}
    # OpenRouter dùng hai header này để gắn request vào một app; endpoint khác bỏ qua.
    if (settings.openai_referer or "").strip():
        headers["HTTP-Referer"] = settings.openai_referer.strip()
    if (settings.openai_title or "").strip():
        headers["X-Title"] = settings.openai_title.strip()

    def _body() -> bytes:
        b: Dict = {
            "model": mdl,
            "temperature": temperature,
            "messages": [{"role": "user", "content": content}],
        }
        if int(settings.openai_max_tokens or 0) > 0:
            b["max_tokens"] = int(settings.openai_max_tokens)
        if want_json:
            b["response_format"] = {"type": "json_object"}
        if want_reasoning:
            b["reasoning"] = {"effort": effort}
        return json.dumps(b).encode("utf-8")

    max_retries = max(1, settings.llm_max_retries)
    attempt = 0
    while attempt < max_retries:
        try:
            req = urllib.request.Request(
                url, data=_body(), method="POST", headers=headers,
            )
            with urllib.request.urlopen(req, timeout=settings.llm_timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            choice = payload["choices"][0]
            text = choice["message"]["content"] or ""
            if choice.get("finish_reason") == "length":
                _log_llm(host, task, mdl, f"reply bị CẮT (finish_reason=length, "
                                          f"{len(text)} ký tự) - tăng OPENAI_MAX_TOKENS")
            # Qwen/Llama hay bọc ```json ...``` - caller json.loads thẳng nên bóc ở
            # đây. Vẫn giữ dù đã có response_format: json_mode=off, hoặc model bị
            # gỡ khỏi JSON mode ở trên, thì đây là lớp phòng thủ duy nhất còn lại.
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            llm_status.note_ok("openai")
            return text
        except urllib.error.HTTPError as e:
            detail = _http_err_detail(e)
            low = detail.lower()
            # Endpoint không hiểu field tuỳ chọn -> gỡ, nhớ, gửi lại NGAY. Đặt
            # TRƯỚC nhánh quota: đây là lỗi cấu hình tự sửa được, không phải sự cố.
            if e.code == 400 and want_json and "response_format" in low:
                _NO_JSON_MODE.add(mdl)
                want_json = False
                _log_llm(host, task, mdl, "không nhận response_format -> tắt JSON mode")
                continue
            if e.code == 400 and want_reasoning and "reasoning" in low:
                _NO_REASONING.add(mdl)
                want_reasoning = False
                _log_llm(host, task, mdl, "không nhận reasoning -> bỏ ngân sách thinking")
                continue
            if e.code == 429:
                # Hết lượt: ghi lại để FE bật cảnh báo (mọi caller đều degrade ÊM).
                info = _quota_info(e, detail)
                llm_status.note_quota("openai", mdl, **info)
                # Hết hạn mức NGÀY thì retry chỉ ngồi ngủ vô ích.
                if info["scope"] == "day":
                    _log_llm(host, task, mdl, "hết quota NGÀY -> bỏ retry, đi đường lui")
                    return None
            if e.code in (408, 429, 500, 502, 503, 504) and attempt < max_retries - 1:
                wait = settings.llm_retry_backoff_s * (attempt + 1)
                _log_llm(host, task, mdl, f"HTTP {e.code}, retry sau {wait}s: {detail}")
                time.sleep(wait)
                attempt += 1
                continue
            _log_llm(host, task, mdl, f"HTTP {e.code}: {detail or repr(e)}")
            return None
        except Exception as e:  # noqa: BLE001 - caller falls back
            _log_llm(host, task, mdl, f"lỗi: {e!r}")
            return None
    return None


def _openai_model_for(task: str) -> str:
    """Model OpenAI-compat cho từng nhiệm vụ; rỗng thì rơi về openai_model."""
    per_task = {
        "react": settings.openai_react_model,
        "qa": settings.openai_qa_model,
    }.get(task, "")
    return (per_task or "").strip() or settings.openai_model


def _openai_reasoning_for(task: str) -> str:
    """Ngân sách thinking cho từng nhiệm vụ; rỗng = không gửi field `reasoning`.

    Nhiệm vụ lạ (không nằm trong 4 cái dưới) trả rỗng để không áp đặt gì.
    """
    effort = {
        "expand": settings.openai_reasoning_expand,
        "plan": settings.openai_reasoning_plan,
        "react": settings.openai_reasoning_react,
        "qa": settings.openai_reasoning_qa,
    }.get(task, "")
    return (effort or "").strip().lower()


def _gemini_generate(
    parts: List[dict],
    temperature: float = 0.3,
    model: Optional[str] = None,
    task: str = "plan",
) -> Optional[str]:
    """Router LLM (tên giữ nguyên để không đổi call site): theo llm_provider -
    gemini/openai ép cứng một bên, auto và openai_first có đường lui sang bên kia.

    `model` là tên model phía GEMINI (per-call). Phía OpenAI-compat không dùng
    tên đó - endpoint khác thì không gian tên model cũng khác - mà tra theo
    `task` ("expand" | "plan" | "react" | "qa") qua _openai_model_for().
    """
    provider = (settings.llm_provider or "auto").strip().lower()
    has_gemini = bool((settings.gemini_api_key or "").strip())
    has_openai = _openai_configured()

    def _try_openai() -> Optional[str]:
        return _openai_generate(parts, temperature, _openai_model_for(task), task)

    def _try_gemini() -> Optional[str]:
        return _gemini_call(parts, temperature, model, task)

    if provider == "openai":
        return _try_openai()
    if provider == "gemini":
        return _try_gemini() if has_gemini else None

    if provider == "openai_first":
        if has_openai:
            text = _try_openai()
            if text is not None:
                return text
            _log_llm(_openai_host(), task, _openai_model_for(task),
                     "thất bại -> fallback sang gemini")
        return _try_gemini() if has_gemini else None

    # auto: Gemini chính, OpenAI-compat dự phòng
    if not has_openai:
        return _try_gemini() if has_gemini else None
    if has_gemini:
        text = _try_gemini()
        if text is not None:
            return text
        _log_llm("gemini", task, model or settings.gemini_model,
                 f"thất bại -> fallback sang {_openai_host()}")
    return _try_openai()


def _gemini_call(
    parts: List[dict],
    temperature: float = 0.3,
    model: Optional[str] = None,
    task: str = "",
) -> Optional[str]:
    """One generateContent call; parts = [{"text": ...} | {"inline_data": ...}].

    Returns the raw response text (JSON mime requested), or None on any error.
    """
    import urllib.parse
    import urllib.request

    mdl = model or settings.gemini_model
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{mdl}:generateContent?key="
        + urllib.parse.quote(settings.gemini_api_key)
    )
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": temperature,
        },
    }
    import time
    import urllib.error

    data = json.dumps(body).encode("utf-8")
    max_retries = max(1, settings.llm_max_retries)
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=settings.llm_timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            llm_status.note_ok("gemini")
            return text
        except urllib.error.HTTPError as e:
            detail = _http_err_detail(e)
            wait = settings.llm_retry_backoff_s * (attempt + 1)
            if e.code == 429:
                # Hết lượt: ghi lại để FE bật cảnh báo (mọi caller đều degrade
                # ÊM, không có dòng này thì ngoài giao diện không ai biết).
                info = _quota_info(e, detail)
                llm_status.note_quota("gemini", mdl, **info)
                # Hết hạn mức NGÀY thì retry chỉ ngồi ngủ vô ích.
                if info["scope"] == "day":
                    _log_llm("gemini", task, mdl,
                             "hết quota NGÀY -> bỏ retry, đi đường lui")
                    return None
                # Nghe RetryInfo của Google thay vì đoán, và CHẶN TRẦN 30s: cả
                # chuỗi retry nằm trong một request HTTP của người dùng, ngủ lâu
                # là client timeout trước khi backend kịp trả lời.
                if info["retry_after_s"]:
                    wait = max(5, min(int(info["retry_after_s"]) + 1, 30))
            # 429/5xx thoáng qua (free tier RPM thấp) -> đợi rồi thử lại
            if e.code in (408, 429, 500, 502, 503, 504) and attempt < max_retries - 1:
                _log_llm("gemini", task, mdl,
                         f"HTTP {e.code}, retry sau {wait}s: {detail}")
                time.sleep(wait)
                continue
            _log_llm("gemini", task, mdl, f"HTTP {e.code}: {detail or repr(e)}")
            return None
        except Exception as e:  # noqa: BLE001 - caller falls back
            _log_llm("gemini", task, mdl, f"lỗi: {e!r}")
            return None
    return None


# --- Dialogue processing ---------------------------------------------------------

_PLAN_PROMPT = """You are the query planner of a keyframe search engine over Vietnamese
news broadcasts (HTV). Aggregate the WHOLE conversation below into ONE search plan.
The latest user message may refine or override earlier ones.

Return ONLY a JSON object:
{
  "mode": "search" | "temporal",
  "query": "<one English sentence describing the VISUAL scene>",
  "events": ["<English visual query>", ...],
  "objects": "<comma-separated OpenImages labels, e.g. person, motorcycle>",
  "scene_keywords": "<comma-separated keywords expected in on-screen text OR speech, original language>",
  "steps": [{"channel": "visual" | "ocr" | "asr" | "caption", "query": "..."}, ...],
  "reply": "<one short Vietnamese sentence telling the user what you searched for>"
}

Rules:
- mode="temporal" ONLY when the user clearly describes a SEQUENCE of 2-4 distinct
  events over time ("sau đó", "tiếp theo", "then", "after that", or an explicit
  E1/E2/E3/E4 list); put each event as one English visual query in "events"
  (chronological order). Otherwise mode="search" and "events" is [].
- "query": faithful English description of what should be VISIBLE in the frame.
  Never generalize the main subject (a "tiger" stays "tiger"). For temporal mode
  set it to the first event.
- "objects": only concrete physical object labels likely detectable (person, car,
  motorcycle, boat, tree, building, animal names...). "" if none.
- "scene_keywords": text the user says appears ON SCREEN or is SPOKEN (names,
  numbers, quoted phrases). Keep Vietnamese as-is, do NOT translate. When the
  request implies a concrete subject a Vietnamese narrator would surely SAY
  (an animal, dish, place... - e.g. a story about the 1975 Spielberg movie ->
  "cá mập"), ADD that Vietnamese term as one extra keyword. "" if none.
{task_rule}{slide_rule}- "steps" (PLANNING, mode="search" only): parallel retrieval channels to run and
  fuse. A simple one-clue request = [] (the main query is enough). Use 2-4 steps
  ONLY when the request mixes DISTINCT clue types, e.g. a described camera shot
  (visual, English query), specific text on screen (ocr, original language), a
  quoted/spoken phrase (asr, original language). When the MAIN SUBJECT is an
  unusual/rare object, a fine-grained detail, or an abstract concept (things
  visual embeddings often miss), ALSO add {"channel": "caption", "query": "<same
  English visual description>"} alongside the visual step. One step per distinct
  clue; visual steps may repeat the main query or describe a DIFFERENT shot.
  Be SPARING: fusion adds channel scores, so every extra channel dilutes a good
  visual hit with 300 more frames of its own noise. Measured on the 30-query
  SOTUYEN2 set, forcing an asr/ocr step whenever the request named a proper noun
  helped 3 queries and hurt 10 (top-5 fell 22/30 -> 13/30). Add a text channel
  only when its phrase is DISTINCTIVE enough to pin one video by itself
  ("Lý Thường Kiệt", "Tam Kỳ"), never for words every broadcast of that genre
  contains ("NGUYÊN LIỆU", "múa lân", "đua xe đạp").
- No markdown, JSON only.

Conversation:
{dialogue}"""


# Dạng đề do BTC phát -> chốt cứng "mode", planner khỏi đoán. Gắn vào
# _PLAN_PROMPT qua {task_rule}; key rỗng (không biết dạng) = không thêm gì.
_TASK_RULE = {
    "trake": """- THE TASK TYPE IS KNOWN: TRAKE. The request describes an ORDERED chain of
  moments in ONE video. You MUST return mode="temporal" and put every listed
  moment ("E1/E2/...", "Cảnh 1/2/...", or each sentence of the chain) into
  "events" as one English visual query, in the given order. Never merge two
  moments into one event and never return mode="search".
""",
    "kis": """- THE TASK TYPE IS KNOWN: KIS (find ONE keyframe). Return mode="search" and
  leave "events" empty, even if the request narrates several actions - they are
  context for the same shot, not separate targets.
""",
}

# Luật riêng cho video bài giảng, gắn vào _PLAN_PROMPT qua {slide_rule}. Tách ra
# để tắt được bằng settings.plan_slide_rule mà vẫn A/B đo được trên eval.
_SLIDE_RULE = """- LECTURE SLIDES: when the request describes a slide/board in a lesson, the little
  drawings on it are METAPHORS for the concept being taught, not the subject of the
  video: two figures in a tug-of-war = "cạnh tranh, ganh đua, đấu tranh"; one red
  figure among white figures = "chủ thể kinh tế / cá nhân và tập thể"; a balance
  scale = "cung cầu". Never use the literal object drawn ("kéo co") - that word is
  nowhere on the slide and nowhere in the lesson. Add an {"channel": "asr"} step
  whose query is the SENTENCE the teacher would say about that concept ("cạnh
  tranh là sự ganh đua, đấu tranh giữa các chủ thể kinh tế"): the teacher speaks
  the concept aloud, so ASR is reliable, while guessing the exact words PRINTED
  on the slide is not - measured on p2-26, guessing "cá nhân và tập thể" (a
  correct gloss, but absent from the slide) pushed the right frame out of the OCR
  top-3, while the spoken sentence pinned the video first. Keep "scene_keywords"
  to short heading-style terms that plausibly appear as printed labels.
"""


def _fallback_plan(messages: List[dict]) -> dict:
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
    )
    return {
        "mode": "search",
        "query": last_user,
        "events": [],
        "objects": "",
        "scene_keywords": "",
        "steps": [],
        "reply": "Đã tìm theo mô tả của bạn (LLM planner không khả dụng).",
    }


def plan_from_dialogue(messages: List[dict], task_hint: str = "") -> dict:
    """Aggregate chat history -> structured plan dict (never fails).

    task_hint = "kis" | "trake" khi dạng đề đã biết (BTC phát kèm gói truy vấn,
    xem routers/agent.py::agent_ask). Planner hết phải đoán mode - đề TRAKE
    không đánh số cảnh ("Cảnh 1: ... Cảnh 2: ...") trước đây có thể rơi về
    mode="search" và mất hẳn nhánh temporal. task_hint="" = giữ nguyên hành vi
    cũ, nên các endpoint khác không đổi kết quả.
    """
    fallback = _fallback_plan(messages)
    if not is_available() or not fallback["query"]:
        return fallback

    dialogue = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
    # temperature=0: planner phải tất định - cùng dialogue cho cùng plan, tránh
    # kết quả search đổi hạng giữa các lần chạy chỉ vì keyword sinh khác nhau.
    text = _gemini_generate(
        [{"text": _PLAN_PROMPT
          .replace("{slide_rule}", _SLIDE_RULE if settings.plan_slide_rule else "")
          .replace("{task_rule}", _TASK_RULE.get(task_hint, ""))
          .replace("{dialogue}", dialogue)}], temperature=0.0,
        task="plan",
    )
    if text is None:
        return fallback
    try:
        plan = json.loads(text)
    except ValueError:
        return fallback

    out = dict(fallback)
    for key in ("mode", "query", "events", "objects", "scene_keywords", "steps", "reply"):
        v = plan.get(key)
        if v:
            out[key] = v
    if out["mode"] not in ("search", "temporal"):
        out["mode"] = "search"
    if task_hint == "kis":
        # Đề KIS mô tả nhiều hành động liên tiếp vẫn chỉ cần MỘT frame.
        out["mode"], out["events"] = "search", []
    elif task_hint == "trake" and len(out["events"]) >= 2:
        out["mode"] = "temporal"
    if out["mode"] == "temporal" and len(out["events"]) < 2:
        # Kể cả khi biết là TRAKE: một event không chạy được search_temporal.
        out["mode"] = "search"
    out["events"] = [str(e) for e in out["events"]][:4]
    # steps hợp lệ: dict có channel được hỗ trợ + query không rỗng, tối đa 4
    out["steps"] = [
        {"channel": s["channel"], "query": str(s.get("query", "")).strip(),
         "objects": str(s.get("objects", "")), "scene_keywords": str(s.get("scene_keywords", ""))}
        for s in (out["steps"] if isinstance(out["steps"], list) else [])
        if isinstance(s, dict)
        and s.get("channel") in ("visual", "ocr", "asr", "caption", "scene_text")
        and str(s.get("query", "")).strip()
    ][:4]
    print(f"[agent] plan: {out}")
    return out


# --- Plan execution: fan-out đa kênh song song + fusion ----------------------------
# Plan-and-Execute: mỗi step là một kênh retrieval độc lập (visual / ocr / asr)
# chạy đồng thời bằng asyncio; điểm mỗi kênh chuẩn hoá theo max của chính nó rồi
# CỘNG theo frame (Tran et al., arXiv:2504.08384, Alg. 3) - frame trúng nhiều
# kênh nổi lên trên. Kênh lỗi/rỗng tự bị bỏ qua, không vỡ request.

async def _run_step(step: dict, top_k: int, model: str) -> List[dict]:
    """Một kênh -> [{id, score}, ...]; lỗi -> [] (đã log)."""
    import asyncio

    channel, q = step["channel"], step["query"]
    try:
        if channel == "visual":
            from routers.search_text import search_text  # local: tránh vòng import
            # top_k*3: kênh visual cần pool ứng viên tương đương các kênh text
            # để fusion không thiên vị kênh trả nhiều frame hơn.
            #
            # KHÔNG fuse biến thể diễn đạt ở đây (đã thử 26/8, planner sinh
            # variants cùng lượt plan + cộng-fusion như search_text): đo trên
            # 23 query cho KÉM đi ở mọi mức (@1 14->13, @100 22->21, +1.6s/q).
            # Các kênh text của fan-out đã đóng vai đa dạng hoá; biến thể tương
            # quan chỉ pha loãng. Trái với search thuần, nơi cộng-fusion biến
            # thể lãi +3 @1 — xem routers/search_text.py.
            res = await search_text(
                query=q, top_k=top_k * 3, model=model, rerank=False, expand=False,
                objects=step.get("objects", ""), object_mode="boost",
                scene_keywords=step.get("scene_keywords", ""), scene_mode="boost",
            )
            return [{"id": r["id"], "score": float(r["score"])} for r in res["results"]]
        if channel == "ocr":
            from services.ocr_service import search_ocr
            # rerank=False: cross-encoder chậm, fan-out cần tốc độ - độ chính
            # xác cuối do fusion + scene aggregation đảm nhiệm
            raw = await asyncio.to_thread(search_ocr, q, top_k * 3, False)
            return [{"id": r["id"], "score": float(r["score"])} for r in raw]
        if channel == "caption":
            from services.caption_service import search_captions
            raw = await asyncio.to_thread(search_captions, q, top_k * 3, False)
            return [{"id": r["id"], "score": float(r["score"])} for r in raw]
        if channel == "scene_text":
            # Chi tiết đặc trưng của câu hỏi ("200g thịt nạc xay") khớp token
            # với OCR+ASR của scene - bất biến thứ tự từ, chịu lỗi OCR.
            from services.graph_service import search_scene_text
            return await asyncio.to_thread(search_scene_text, q, 30)
        if channel == "asr":
            from services.asr_service import search_asr
            from services.metadata_service import frames_in_range
            # Lấy rộng hơn top segment: một phân đoạn đúng có thể nằm dưới top-3
            # (vd câu thơ nằm ở segment thứ 4-5 của cùng video) - frame của nó
            # vẫn phải vào pool để scene aggregation gộp bằng chứng.
            videos = await asyncio.to_thread(search_asr, q, "", False)
            out: List[dict] = []
            for v in videos[:15]:
                for seg in v["segments"][:10]:
                    for fr in frames_in_range(v["video_name"], seg["start_ms"], seg["end_ms"]):
                        out.append({"id": fr["id"], "score": float(seg["score"])})
            return out
    except Exception as e:  # noqa: BLE001 - một kênh hỏng không được vỡ cả plan
        print(f"[plan] step {channel} {q!r} failed: {e!r}")
    return []


async def run_step_lists(steps: List[dict], top_k: int, model: str) -> List[List[dict]]:
    """Chạy các step song song -> kết quả THÔ từng kênh, giữ đúng thứ tự steps."""
    import asyncio

    return list(await asyncio.gather(*(_run_step(s, top_k, model) for s in steps)))


def fuse_step_lists(steps: List[dict], lists: List[List[dict]],
                    channel_weights: Optional[Dict[str, float]] = None) -> List[dict]:
    """Fuse kết quả các kênh theo điểm max-norm -> [{id, score}] đã sort.

    channel_weights (vd {"visual": 0.6, "asr": 1.5}): nhân điểm mỗi kênh sau
    chuẩn hoá - dùng để ưu tiên kênh bằng chứng quan trọng với bối cảnh gọi.
    """
    weights = channel_weights or {}
    peak_bonus = float(getattr(settings, "fusion_peak_bonus", 0.0) or 0.0)
    fused: dict = {}
    for step, lst in zip(steps, lists):
        if not lst:
            continue
        smax = max(x["score"] for x in lst) or 1.0
        w = weights.get(step["channel"], 1.0)
        seen: set = set()
        for x in lst:
            if x["id"] in seen:  # ASR có thể sinh trùng frame giữa các segment
                continue
            seen.add(x["id"])
            fused[x["id"]] = fused.get(x["id"], 0.0) + w * x["score"] / smax
        print(f"[plan] {step['channel']} {step['query']!r}: {len(seen)} frames")
        # Kênh CHỮ có ĐỈNH NHỌN = khớp nguyên văn một cụm hiếm (điểm đỉnh gấp
        # >= 2 lần điểm kế tiếp): bằng chứng mạnh hơn hẳn cosine hình ảnh, nhưng
        # max-norm coi nó ngang một frame visual bất kỳ và 600 frame nhiễu của
        # visual + caption nhấn chìm nó (p2-26: OCR một mình rank 1 điểm 1.0,
        # sau fusion ngoài top-20). Thưởng thêm cho đỉnh để nó ở lại đầu bảng.
        # Phân bố phẳng (mọi frame cùng "NGUYÊN LIỆU") không có đỉnh -> không
        # thưởng, nên không lặp lại lỗi "ép kênh text hại 10 câu".
        if peak_bonus > 0 and step["channel"] in ("ocr", "asr", "scene_text") and len(lst) >= 2:
            ranked = sorted({x["id"]: float(x["score"]) for x in lst}.items(),
                            key=lambda kv: -kv[1])
            top_s = ranked[0][1]
            second = ranked[1][1] if len(ranked) > 1 else 0.0
            if top_s > 0 and top_s >= 2.0 * second:
                peaks = [fid for fid, sc in ranked if sc >= 0.95 * top_s][:3]
                for fid in peaks:
                    fused[fid] = fused.get(fid, 0.0) + w * peak_bonus
                print(f"[plan] {step['channel']} peak x{top_s / max(second, 1e-9):.1f} "
                      f"-> +{peak_bonus} for {peaks}")
    out = [{"id": fid, "score": s} for fid, s in fused.items()]
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


async def execute_plan_steps(steps: List[dict], top_k: int, model: str,
                             channel_weights: Optional[Dict[str, float]] = None) -> List[dict]:
    """Chạy các step song song rồi fuse (xem fuse_step_lists)."""
    lists = await run_step_lists(steps, top_k, model)
    return fuse_step_lists(steps, lists, channel_weights)


def _cpu_text_model():
    """SentenceTransformer riêng chạy trên CPU để chấm scene text.

    E5 đã nằm trên GPU cùng SigLIP - 4GB VRAM không đủ để encode batch passage
    thêm (OOM như đã gặp). Scene text của QA chỉ vài trăm frame ngắn, encode trên
    CPU chậm hơn nhưng an toàn tuyệt đối; model được load lazy, dùng chung process.
    """
    global _CPU_MODEL
    if _CPU_MODEL is None:
        from sentence_transformers import SentenceTransformer
        name = (settings.text_embed_model or "intfloat/multilingual-e5-base").strip()
        _CPU_MODEL = SentenceTransformer(name, device="cpu")
    return _CPU_MODEL


_CPU_MODEL = None


def rerank_qa_by_scene_text(raw: List[dict], question: str) -> List[dict]:
    """Rerank QA candidates by semantic similarity between the question and the
    scene's OCR+ASR text.

    QA answers often live in SPOKEN text (ASR) or ON-SCREEN text (OCR) - e.g.
    "hai câu thơ ca ngợi Nguyễn Trung Trực" is read aloud in the clip. The
    visual embedding (SigLIP/CLIP) can't see words, so a purely visual retrieve
    misses those frames. The asr/ocr channels DO surface the right video, but a
    frame that happens to hit 2-3 channels (visual+ocr+asr) can out-rank the
    one frame whose scene text IS the answer. Here we add an explicit text
    signal - cosine(question, scene OCR+ASR) - blended into the fused score:

        final = fused + qa_scene_text_weight * cosine

    Encodings run on CPU so SigLIP + E5 share the small GPU safely; no-op
    (returns raw unchanged) when the text model or the graph is missing.
    """
    w = float(settings.qa_scene_text_weight)
    if w <= 0 or not raw:
        return raw

    from services.graph_service import frame_node  # local: tránh vòng
    from services.text_embedding_service import encode_query

    qv = encode_query(question)  # GPU, 1 vector - an toàn
    if qv is None:
        return raw

    entries = []  # (idx, frame_id, scene_text)
    for idx, item in enumerate(raw):
        scene = (frame_node(item["id"]) or {}).get("scene") or {}
        text = f"{scene.get('ocr', '')} {scene.get('asr', '')}".strip()
        if text:
            entries.append((idx, item["id"], text))
    if not entries:
        return raw

    try:
        import numpy as np

        model = _cpu_text_model()
        emb = model.encode(
            [f"passage: {t}" for _, _, t in entries],
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=8,
        )
        sims = (np.asarray(emb, dtype=np.float32) @ qv).tolist()
    except Exception as e:  # noqa: BLE001 - thiếu model -> giữ fusion cũ
        print(f"[qa-rerank] scene-text unavailable ({e!r}); giữ fusion")
        return raw

    out = [dict(item) for item in raw]  # copy: không mutate caller list
    for (idx, _, _), sim in zip(entries, sims):
        out[idx]["score"] = float(out[idx]["score"]) + w * float(sim)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def qa_select_evidence(steps: List[dict], lists: List[List[dict]], question: str) -> List[dict]:
    """Chọn frame bằng chứng cho QA: fusion theo VIDEO + đa dạng hoá video/kênh.

    Fusion per-frame (execute_plan_steps) thua thiệt cho QA: các kênh thường
    trúng frame KHÁC NHAU của cùng video đúng (visual trúng cảnh quay, OCR
    trúng khung chữ, ASR trúng đoạn nói) nên video đúng chỉ được tính 1 kênh
    mỗi frame, còn video "gần chủ đề" trúng 1 frame ở nhiều kênh thì cộng dồn
    và chiếm trọn top-N. Neighbor/scene aggregation còn khuếch đại video đông
    frame trong pool (đo được: ground truth rơi #5 -> #29). Thay bằng:

      1. điểm video  = Σ theo kênh ( max điểm chuẩn hoá của frame thuộc video )
      2. giữ qa_max_videos video mạnh nhất
      3. điểm frame  = fusion per-frame + qa_scene_text_weight * cosine
         (rerank_qa_by_scene_text) trong phạm vi các video đã giữ
      4. mỗi video lấy tối đa qa_frames_per_video frame - frame tốt nhất của
         TỪNG kênh trước (bằng chứng nằm ở frame khác nhau), rồi bù theo điểm
    """
    channels: List[Dict[str, float]] = []  # mỗi kênh: {frame_id: điểm đã max-norm}
    for step, lst in zip(steps, lists):
        if not lst:
            continue
        smax = max(x["score"] for x in lst) or 1.0
        scores: Dict[str, float] = {}
        for x in lst:
            s = float(x["score"]) / smax
            if s > scores.get(x["id"], 0.0):
                scores[x["id"]] = s
        channels.append(scores)
        print(f"[qa] {step['channel']} {step['query']!r}: {len(scores)} frames")
    if not channels:
        return []

    def vid(fid: str) -> str:
        return fid.rsplit("_", 1)[0]

    video_score: Dict[str, float] = {}
    frame_fused: Dict[str, float] = {}
    for scores in channels:
        best: Dict[str, float] = {}
        for fid, s in scores.items():
            frame_fused[fid] = frame_fused.get(fid, 0.0) + s
            if s > best.get(vid(fid), 0.0):
                best[vid(fid)] = s
        for v, s in best.items():
            video_score[v] = video_score.get(v, 0.0) + s

    top_videos = sorted(video_score, key=video_score.get, reverse=True)[
        : max(int(settings.qa_max_videos), 1)]
    print(f"[qa] videos: {[(v, round(video_score[v], 3)) for v in top_videos]}")
    kept = set(top_videos)

    pool = [{"id": fid, "score": s} for fid, s in frame_fused.items() if vid(fid) in kept]
    pool = rerank_qa_by_scene_text(pool, question)
    pool_score = {x["id"]: float(x["score"]) for x in pool}

    per_video = max(int(settings.qa_frames_per_video), 1)
    picked: List[str] = []
    for v in top_videos:
        # Slot 1: frame mà kênh TIN video này nhất (bằng chứng theo kênh mạnh).
        # Slot còn lại: theo điểm pool (fused + scene-text cosine) - frame có
        # scene OCR/ASR khớp chữ nghĩa câu hỏi nhất, thường là nơi chứa lời đáp.
        cands: List[tuple] = []
        for scores in channels:
            best_fid = max(
                (fid for fid in scores if vid(fid) == v),
                key=lambda f: scores[f], default=None)
            if best_fid:
                cands.append((scores[best_fid], best_fid))
        chosen: List[str] = [max(cands)[1]] if cands else []
        rest = sorted(
            (fid for fid in pool_score if vid(fid) == v and fid not in chosen),
            key=pool_score.get, reverse=True)
        chosen.extend(rest[: per_video - len(chosen)])
        picked.extend(chosen)

    picked.sort(key=lambda f: pool_score.get(f, 0.0), reverse=True)

    # Rải thêm frame theo DÒNG THỜI GIAN của video mạnh nhất. Các slot ở trên đều
    # chọn theo điểm, nên với một video dài chúng dồn vào đúng một cảnh: câu hỏi
    # về chi tiết ở cảnh KHÁC (p2-7 hỏi số trên hông xe trắng, hai frame điểm cao
    # nhất đều là cảnh trong ca-bin) không có frame nào chứa lời đáp để mà nhìn.
    if top_videos and int(settings.qa_timeline_frames) > 0:
        from services.metadata_service import frames_in_video, get_meta

        v = top_videos[0]
        names = frames_in_video(v)
        have = {f for f in picked if vid(f) == v}
        if names:
            n_extra = int(settings.qa_timeline_frames)
            step = max(1, len(names) // (n_extra + 1))
            for nm in names[step::step][:n_extra]:
                fid = f"{v}_{nm.rsplit('.', 1)[0]}"
                if fid in have or get_meta(fid) is None:
                    continue
                have.add(fid)
                picked.append(fid)

    return [{"id": fid, "score": pool_score.get(fid, frame_fused.get(fid, 0.0))}
            for fid in picked]


# --- RAG question answering -------------------------------------------------------

_QA_PROMPT = """You answer a question about Vietnamese news broadcast footage.
Below are candidate keyframes; each comes with its video id, timestamp, text
visible on screen (OCR) and the speech transcript around that shot (ASR).
Ground your answer ONLY in this evidence. OCR/ASR may contain recognition errors.

The candidates come from DIFFERENT videos and only one video truly matches the
question. Before answering, check every constraint the question states (who is
visible, what they are holding/doing, where, what kind of footage) against each
candidate, and answer from the video satisfying ALL of them - not from a
candidate that merely shares a detail (e.g. the same ingredient or place name).

WHEN THE PICTURE IS AMBIGUOUS, THE TEXT DECIDES. Many things are impossible to
tell apart from pixels alone - salmon floss vs pork floss, one white fish vs
another, which street a shop is on - but the narrator SAYS it and the OCR shows
it. If the ASR or OCR of the matching video states the answer, use that, even
when the image merely looks like something else. Quote the exact words you used
in "evidence_quote"; leave it "" only when the answer really comes from the image.
The quote MUST come from the OCR/ASR block of the frame you name in
"evidence_index". The frames below are from DIFFERENT videos about different
events; a phrase from another video's block is not evidence about this one, and
mixing them is the single most common way to answer confidently and wrongly.

Return ONLY a JSON object:
{"answer": "<concise answer in the question's language>",
 "evidence_quote": "<the exact OCR/ASR words that gave the answer, or \"\">",
 "evidence_index": <0-based index of the single most relevant frame, or -1>}

Question: {question}"""


def _image_part(data: Optional[bytes], suffix: str = "webp") -> Optional[dict]:
    """Build Gemini inline_data part from raw image bytes.

    `data` đến từ `metadata_service.frame_bytes()` (HTTP fetch từ FE + cache).
    """
    if not data:
        return None
    suffix = (suffix or "webp").lstrip(".").lower()
    mime = f"image/{'jpeg' if suffix in ('jpg', 'jpeg') else suffix or 'webp'}"
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}


def answer_question(question: str, frames: List[dict]) -> dict:
    """{"answer": str, "evidence_index": int} from Gemini vision over the frames.

    `frames` = SearchResult dicts (id, video_name, frame_name, timestamp_ms...).
    """
    if not is_available():
        return {"answer": "Gemini chưa cấu hình (GEMINI_API_KEY) - không trả lời được.",
                "evidence_index": -1}

    from services.asr_service import asr_context
    from services.graph_service import frame_node  # local import: tránh vòng
    from services.metadata_service import frame_bytes_many

    parts: List[dict] = [{"text": _QA_PROMPT.replace("{question}", question)}]
    picked = frames[: settings.agent_max_qa_frames]
    # Kéo cả 12 ảnh song song trước vòng lặp: tuần tự thì tổng = 12 × RTT, đau
    # khi media nằm sau ngrok (backend Colab, media máy nhà).
    blobs = frame_bytes_many([(f["video_name"], f["frame_name"]) for f in picked])
    for i, fr in enumerate(picked):
        node = frame_node(fr["id"]) or {}
        scene = node.get("scene") or {}
        img = _image_part(blobs[i], suffix=fr.get("frame_name", "").rsplit(".", 1)[-1])
        if img is None:
            continue
        # ASR lấy theo cửa sổ thời gian quanh frame, không bó theo scene: lời
        # đáp thường được NÓI cạnh shot (scene chỉ vài giây, trượt mất câu thơ
        # đọc ngay sau đó).
        asr = asr_context(fr["video_name"], int(fr["timestamp_ms"])) or scene.get("asr", "")
        parts.append({"text": (
            f"--- Frame {i} | video {fr['video_name']} "
            f"@ {fr['timestamp_ms'] / 1000:.0f}s ---\n"
            f"OCR: {scene.get('ocr', '')[:400]}\n"
            f"ASR: {asr[:900]}"
        )})
        parts.append(img)

    qa_model = settings.gemini_qa_model or None
    if qa_model and "gemma" in qa_model.lower():
        # Gemma trên AI Studio không có JSON mode và hay suy luận dông dài -
        # quan sát thực tế: có chỉ thị chốt thì nó LUÔN kết bằng JSON ở dòng
        # cuối, parser regex phía dưới vớt được.
        parts.append({"text": (
            'IMPORTANT: your LAST line MUST be exactly one JSON object '
            '{"answer": "<Vietnamese answer>", "evidence_index": <int>}. '
            "Keep any reasoning short; never omit the final JSON line.")})
    text = _gemini_generate(parts, temperature=0.1, model=qa_model, task="qa")
    if text is None:
        return {"answer": "LLM không phản hồi - thử lại hoặc giảm số frame.",
                "evidence_index": -1}
    out = _parse_qa_json(text)
    if out is None:
        # Model không tôn trọng JSON mode (Gemma AI Studio, Qwen OpenAI-compat)
        # và suy luận dông dài đến quên JSON - pha 2: đưa lại chính câu trả lời
        # của nó, bắt chưng cất thành JSON (call text ngắn, rẻ, gần như luôn ăn).
        fix = _gemini_generate([{"text": (
            'From the NOTES below, output ONLY one JSON object '
            '{"answer": "<Vietnamese answer>", "evidence_index": <int frame index, '
            "-1 if unclear>}. No other text.\nNOTES:\n" + text[:2000])}],
            temperature=0.0, model=qa_model, task="qa")
        out = _parse_qa_json(fix) if fix else None
    if out is None:
        return {"answer": text.strip()[:500], "evidence_index": -1}
    try:
        ev = int(out.get("evidence_index", -1))
    except (ValueError, TypeError):
        ev = -1
    quote = str(out.get("evidence_quote", "")).strip()
    if quote:
        print(f"[qa] evidence_quote: {quote[:120]!r}")
        if 0 <= ev < len(picked) and not _quote_in_video(quote, picked[ev]["video_name"]):
            # Trích dẫn không nằm trong OCR/ASR của chính video bằng chứng =
            # model gom nhầm khối văn bản của video khác (đo được: p2-28 dẫn
            # "Lương thì mềm và thơm lắm" của video khác rồi trả lời "con lươn",
            # trong khi video đúng nói "cá hồi" 11 lần).
            print(f"[qa] CANH BAO: trich dan KHONG co trong "
                  f"{picked[ev]['video_name']} - cau tra loi dang dua vao video khac")
    return {"answer": str(out.get("answer", "")).strip() or "(không có trả lời)",
            "evidence_index": ev, "evidence_quote": quote}


_ZOOM_PROMPT = """You already looked at this question once and answered:

  "{prev}"

Small printed text - a number on a scale, a plate number, a line in an ingredient
table - is easy to misread at a glance. Below is the SAME evidence again,
enlarged: each frame is shown at 2x,
followed by its four overlapping quadrants at 2x, plus the frames just before and
after it.

Read the actual characters. Do not infer a plausible value: if the digits are
legible, report exactly what is printed, including the decimal point and units.
If they are genuinely illegible, keep the previous answer.

Return ONLY a JSON object:
{"answer": "<concise answer in the question's language>",
 "evidence_index": 0}

Question: {question}"""


def _zoom_image_parts(blob: Optional[bytes], suffix: str) -> List[dict]:
    """Ảnh phóng to + 4 góc chồng mép, tất cả 2x.

    TẮT MẶC ĐỊNH (settings.qa_zoom_pass=False) - giữ lại vì có thể có ích với
    batch ảnh nhỏ, nhưng ĐỪNG bật lại mà không đo. Lý do: giả thiết ban đầu
    ("keyframe lưu ở nửa kích thước 640x360 nên chữ nhỏ không đọc nổi") SAI -
    kiểm lại thì cả 10 batch L21-L30 đều là 1280x720, model vốn đã nhận đủ độ
    phân giải. Đo trên 13 câu QA: 10 lượt zoom, KHÔNG lượt nào đổi nội dung câu
    trả lời (chỉ đổi cách viết "Số 6" -> "6"), trong khi tốn thêm một call
    vision mỗi câu. Hai câu tưởng là "đọc sai chữ nhỏ" hoá ra là chọn nhầm
    frame trong đúng video (p2-7) và bỏ qua lời thoại đã có sẵn (p2-28).
    Thiếu Pillow -> trả ảnh gốc, không bao giờ vỡ.
    """
    if not blob:
        return []
    try:
        import io

        from PIL import Image
    except Exception:  # noqa: BLE001 - không có Pillow thì dùng ảnh gốc
        part = _image_part(blob, suffix)
        return [part] if part else []
    try:
        im = Image.open(io.BytesIO(blob)).convert("RGB")
    except Exception:  # noqa: BLE001 - webp hỏng
        part = _image_part(blob, suffix)
        return [part] if part else []

    def enc(img) -> Optional[dict]:
        # JPEG q90, KHÔNG PNG: cùng ảnh 2x thì PNG ~1.5 MB còn JPEG ~120 KB, mà
        # một lượt zoom gửi 5 ảnh nên PNG đội lên ~5 MB base64 cho MỘT câu hỏi.
        # Nhiễu nén ở q90 không ảnh hưởng việc đọc chữ đã phóng to.
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        return _image_part(buf.getvalue(), "jpg")

    w, h = im.size
    out: List[dict] = []
    full = enc(im.resize((w * 2, h * 2), Image.LANCZOS))
    if full:
        out.append(full)
    ox, oy = int(w * 0.15), int(h * 0.15)  # chồng mép: chữ nằm giữa không bị cắt đôi
    boxes = [(0, 0, w // 2 + ox, h // 2 + oy),
             (w // 2 - ox, 0, w, h // 2 + oy),
             (0, h // 2 - oy, w // 2 + ox, h),
             (w // 2 - ox, h // 2 - oy, w, h)]
    for box in boxes:
        crop = im.crop(box)
        part = enc(crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS))
        if part:
            out.append(part)
    return out


def zoom_reread(question: str, frames: List[dict], evidence_index: int,
                prev_answer: str) -> Optional[dict]:
    """Pha 2 của QA: đọc lại frame bằng chứng ở 2x + 4 góc, sửa nếu pha 1 đọc sai.

    Trả None khi không chạy được (thiếu key, thiếu ảnh, model không trả JSON) -
    caller giữ nguyên câu trả lời pha 1.
    """
    if not (0 <= evidence_index < len(frames)) or not is_available():
        return None
    from services.metadata_service import frame_bytes_many, frames_in_range

    ev = frames[evidence_index]
    ts = int(ev["timestamp_ms"])
    # Hai frame kề: số cuối cùng trên màn hình / bảng hiện đủ chữ thường nằm ở
    # frame sát bên chứ không đúng frame được chấm điểm cao nhất.
    neigh = [f for f in frames_in_range(ev["video_name"], ts - 6000, ts + 6000)
             if f["id"] != ev["id"] and not f.get("virtual")][:2]
    rows = [ev] + [{"video_name": n["video_name"], "frame_name": n["frame_name"],
                    "id": n["id"], "timestamp_ms": n["timestamp_ms"]} for n in neigh]
    blobs = frame_bytes_many([(r["video_name"], r["frame_name"]) for r in rows])

    parts: List[dict] = [{"text": _ZOOM_PROMPT.replace("{prev}", prev_answer[:300])
                          .replace("{question}", question)}]
    n_img = 0
    for i, r in enumerate(rows):
        suffix = str(r.get("frame_name", "")).rsplit(".", 1)[-1]
        imgs = _zoom_image_parts(blobs[i], suffix) if i == 0 else (
            [_image_part(blobs[i], suffix)] if blobs[i] else [])
        imgs = [x for x in imgs if x]
        if not imgs:
            continue
        label = "EVIDENCE frame (2x, then its 4 quadrants at 2x)" if i == 0 else \
                f"neighbour frame @ {r['timestamp_ms'] / 1000:.0f}s"
        parts.append({"text": f"--- {label} | {r['id']} ---"})
        parts.extend(imgs)
        n_img += len(imgs)
    if not n_img:
        return None

    text = _gemini_generate(parts, temperature=0.0,
                            model=settings.gemini_qa_model or None, task="qa")
    if text is None:
        return None
    out = _parse_qa_json(text)
    if not out:
        return None
    ans = str(out.get("answer", "")).strip()
    if not ans:
        return None
    print(f"[qa] zoom: {prev_answer[:40]!r} -> {ans[:40]!r} ({n_img} ảnh)")
    return {"answer": ans, "evidence_index": evidence_index,
            "evidence_quote": str(out.get("evidence_quote", "")).strip()}


def _quote_in_video(quote: str, video_name: str) -> bool:
    """Cụm trích dẫn có thật sự nằm trong OCR/ASR của video đó không (bỏ dấu,
    khớp theo cửa sổ token để chịu được model diễn đạt lại đôi chút)."""
    from services.asr_service import _load_asr
    from services.ocr_service import _load_ocr
    from services.text_norm import tokens

    qt = tokens(quote)
    if len(qt) < 2:
        return True  # quá ngắn để kiểm, đừng báo động giả
    hay = " ".join(s.get("text", "") for s in _load_asr().get(video_name, []))
    ocr = _load_ocr()
    hay += " " + " ".join(v for k, v in ocr.items() if k.startswith(video_name + "_"))
    ht = set(tokens(hay))
    return sum(1 for t in qt if t in ht) >= max(2, int(0.6 * len(qt)))


def _parse_qa_json(text: str) -> Optional[dict]:
    """json.loads thẳng, trượt thì vớt object JSON CUỐI CÙNG chứa "answer"
    (JSON đáp án luôn đứng sau phần suy luận). None = không có JSON nào."""
    import re

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    m = None
    for m in re.finditer(r'\{[^{}]*"answer"[^{}]*\}', text, flags=re.DOTALL):
        pass
    if m is None:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


# --- ReAct loop --------------------------------------------------------------------
# Thought -> Action -> Observation, tối đa react_max_steps vòng (Yao et al. 2022).
# Chỉ chạy khi one-shot plan cho kết quả kém (hoặc deep=true): agent nhìn
# observation NÉN (điểm, phân bố video, OCR/ASR cảnh của top frame - không phải
# 200 kết quả thô), tự sửa query/filter, và có thể yêu cầu XEM ảnh (vision).

_REACT_PROMPT = """You are a ReAct agent refining a keyframe search over Vietnamese
news broadcasts. The first search plan gave weak results. Improve them.

TOOLS
- search        args {"query": "<English visual description>", "objects": "<OpenImages labels or ''>", "scene_keywords": "<on-screen/spoken keywords, original language, or ''>"}
- search_transcript args {"query": "<keywords, ORIGINAL language>", "channel": "asr" | "ocr"} -> which videos SAY (asr) or SHOW ON SCREEN (ocr) these words; returns video names + matched text
- graph_labels  args {"contains": "<substring>"} -> which object labels exist in the corpus
- scene_info    args {"frame_id": "<id>"} -> OCR/ASR text + time range of that frame's scene
- view_frames   args {"frame_ids": ["<id>", ...]} -> up to 8 keyframe IMAGES for you to look at;
                or {"video": "<video_name>", "around": "<frame_id>", "n": 6} -> n keyframes of ONE video
                in TIME ORDER around that frame (+-90s) - use this to check what happens before/after a hit
- video_timeline args {"video": "<video_name>", "from_s": <sec>, "to_s": <sec>} -> keyframes (id + time) and spoken lines (ASR) in that window of ONE video; shows where NO keyframe exists
- locate_by_asr args {"video": "<video_name>", "query": "<spoken words, ORIGINAL language>"} -> best spoken moments in THAT video, each with a frame id you may submit EVEN IF no keyframe exists there

PROTOCOL - reply with ONLY one JSON object per turn:
  {"thought": "<why>", "action": {"tool": "<name>", "args": {...}}}
or, when done:
  {"thought": "<why>", "final": {"reply": "<one short Vietnamese sentence for the user>", "frame_ids": ["<id>", ...]}}
  frame_ids is optional: ids (from results or from locate_by_asr) to put at the TOP of the final results, in order.

RULES
- You have at most {max_steps} actions. Be decisive.
- NEVER repeat an identical action; change something each time.
- A search with top score >= {threshold} and a clear video cluster is good enough -> finish.
- Vary the WORDING/detail of the query, never generalize the main subject.
- scene_keywords must stay in the original language (Vietnamese stays Vietnamese).
- The image encoder sees STILL frames: drop camera/editing words (pan, tilt,
  transition, static shot) and describe only what is visible in one frame.
- A drawing on a LECTURE SLIDE is a METAPHOR for the concept taught, not the topic
  of the video: two figures pulling a rope = "cạnh tranh / ganh đua", a red figure
  among white ones = "chủ thể kinh tế / cá nhân và tập thể". Call search_transcript
  on channel "asr" with the SENTENCE a teacher would SAY about that concept, NEVER
  with the literal object drawn ("kéo co") - that word appears nowhere in the
  lesson. Prefer asr over ocr here: the teacher says the concept aloud, whereas
  the exact wording printed on the slide is a guess you cannot verify.
- When the request names a broad CATEGORY ("a seafood ingredient", "a fruit"),
  try searches that GUESS concrete instances (squid / shrimp / fish...) - a right
  guess ranks the true frame far higher than the category word ever will.
- If the request contains a PROPER NOUN (place, person, nationality, brand, number,
  channel name), call search_transcript with it FIRST: spoken/on-screen text pins the
  exact video far more reliably than visuals.
- LECTURE / SLIDE videos (teacher + slides, exam review, language lesson) have long
  stretches with NO keyframe, so visual search cannot land on the right moment. For
  such a request the protocol is MANDATORY: (1) search_transcript to pin the video,
  (2) locate_by_asr on that video with the words the teacher would SAY about the
  described slide/table/figure (try 2 wordings if the first scores < 0.5),
  (3) finish with final.frame_ids = the located ids (best first). Finishing a
  lecture request without locate_by_asr is a failure - a visual frame of the same
  teacher is NOT the answer. Use video_timeline to see the gap if unsure.
- SAME-SERIES CHECK: when the top videos are episodes of the same show (same studio,
  same host, cooking/lecture/sports series), visual similarity cannot decide. Write
  down every COUNTABLE or ORDERED constraint of the request (how many items, which
  ingredient goes in first, "from the start of the video", number of riders...),
  then call view_frames in timeline mode on each candidate video and tick the
  constraints against what you SEE. Pick the video that satisfies ALL of them, even
  if it ranked lower; put its frames in final.frame_ids. Never finish on "looks
  similar" when a constraint is unchecked.
- CROSS-CHECK before finishing: if the top visual videos do not overlap the
  search_transcript videos for the request's proper nouns, the visual hit is probably
  a look-alike from a different event - trust the transcript videos and re-search
  restricted to them via scene_keywords.

User request (aggregated): {query_summary}
"""


def _observe_transcript(query: str, channel: str) -> str:
    """Chạy kênh text (ASR/OCR) và nén thành observation: video nào NÓI/HIỆN chữ đó.

    Mục đích chính là cross-check: tên riêng/địa danh trong transcript ghim đúng
    video, trong khi visual dễ dính cảnh giống nhau của sự kiện khác.
    """
    obs, _ = observe_transcript_pinned(query, channel)
    return obs


def observe_transcript_pinned(query: str, channel: str):
    """Như _observe_transcript nhưng trả thêm video ASR mạnh nhất ("" nếu không
    có) - để vòng ReAct nhớ video mà transcript đã ghim, phòng khi agent kết
    thúc mà chưa định vị."""
    q = query.strip()
    if not q:
        return "empty transcript query", ""
    if channel == "ocr":
        from services.ocr_service import search_ocr, _load_ocr

        hits = search_ocr(q, top_k=10, rerank=False)
        if not hits:
            return "OCR: no match", ""
        texts = _load_ocr()
        lines = [f"OCR frames for {q!r}:"]
        vids: dict = {}
        for h in hits:
            vids[h["id"].rsplit("_", 1)[0]] = vids.get(h["id"].rsplit("_", 1)[0], 0) + 1
        lines.append("videos: " + ", ".join(f"{v}×{n}" for v, n in
                                            sorted(vids.items(), key=lambda x: -x[1])[:5]))
        for h in hits[:5]:
            lines.append(f"  {h['score']:.3f} {h['id']} \"{texts.get(h['id'], '')[:100]}\"")
        return "\n".join(lines), ""

    from services.asr_service import search_asr

    videos = search_asr(q, "", rerank=False)
    if not videos:
        return "ASR: no match", ""
    lines = [f"ASR videos for {q!r}: " + ", ".join(v["video_name"] for v in videos[:5])]
    for v in videos[:3]:
        seg = max(v["segments"], key=lambda s: s["score"])
        lines.append(f"  {v['video_name']} [{seg['start_ms'] // 1000}s] "
                     f"({seg['score']:.3f}) \"{seg['text'][:150]}\"")
    return "\n".join(lines), videos[0]["video_name"]


def _observe(results: List[dict], limit: int = 5) -> str:
    """Nén một danh sách kết quả thành observation ngắn cho LLM."""
    if not results:
        return "NO RESULTS."
    from services.graph_service import frame_node

    top = results[:limit]
    lines = ["top-%d: %s" % (
        len(top), ", ".join(f"{r['score']:.3f} {r['id']}" for r in top))]
    vids: dict = {}
    for r in results[:20]:
        vids[r["video_name"]] = vids.get(r["video_name"], 0) + 1
    lines.append("videos in top-20: " + ", ".join(
        f"{v}×{n}" for v, n in sorted(vids.items(), key=lambda x: -x[1])[:5]))
    for i, r in enumerate(top[:3]):
        scene = (frame_node(r["id"]) or {}).get("scene") or {}
        lines.append(
            f"scene of #{i} {r['id']}: OCR=\"{scene.get('ocr', '')[:120]}\" "
            f"ASR=\"{scene.get('asr', '')[:180]}\""
        )
    return "\n".join(lines)


def _parse_json_obj(text: str) -> Optional[dict]:
    """JSON object từ reply LLM: chấp nhận ```json fence và chữ thừa quanh {...}.

    Reply không phải object (list, số) hay không có {} -> None. Vòng ReAct
    trước đây dừng im lặng ở ngay câu trả lời đầu tiên có fence - trace rỗng
    trông y hệt "agent thấy đủ tốt nên không làm gì".
    """
    if not text:
        return None
    t = text.strip()
    for cand in (t, t.strip("`").removeprefix("json").strip()):
        try:
            obj = json.loads(cand)
            return obj if isinstance(obj, dict) else None
        except ValueError:
            pass
    # Model hay trả NHIỀU object nối nhau (lên kế hoạch mấy bước một lượt) dù
    # protocol nói một object mỗi lượt -> lấy object ĐẦU TIÊN, tức action kế
    # tiếp; các object sau sẽ được sinh lại khi có observation thật.
    i = t.find("{")
    if i >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(t[i:])
            return obj if isinstance(obj, dict) else None
        except ValueError:
            return None
    return None


def _observe_timeline(video: str, from_s, to_s) -> str:
    """Keyframe + ASR của một video trong cửa sổ thời gian - để agent thấy khoảng
    trống không có keyframe (bài giảng slide) thay vì tin frame visual ở xa."""
    from services.asr_service import _load_asr
    from services.metadata_service import frames_in_range, frames_in_video, video_fps

    if not video or not frames_in_video(video):
        return f"unknown video {video!r}"
    try:
        lo = int(float(from_s or 0)) * 1000
        hi = int(float(to_s)) * 1000 if to_s is not None else lo + 120_000
    except (TypeError, ValueError):
        lo, hi = 0, 120_000
    hi = max(hi, lo + 1000)
    frames = [f for f in frames_in_range(video, lo, hi) if not f.get("virtual")]
    lines = [f"{video} fps={video_fps(video):.2f} window {lo // 1000}-{hi // 1000}s: "
             f"{len(frames)} keyframes" + ("" if frames else " (NO keyframe in this window)")]
    step = max(1, len(frames) // 12)
    lines.append("keyframes: " + ", ".join(
        f"{f['id']}@{f['timestamp_ms'] // 1000}s" for f in frames[::step][:12]))
    segs = [s for s in _load_asr().get(video, [])
            if s.get("end_ms", 0) >= lo and s.get("start_ms", 0) <= hi]
    for sg in segs[:10]:
        lines.append(f"  ASR [{sg['start_ms'] // 1000}s] {sg.get('text', '')[:120]}")
    if len(segs) > 10:
        lines.append(f"  ... {len(segs) - 10} more ASR lines")
    return "\n".join(lines)


def _observe_locate(video: str, query: str):
    """locate_by_asr: mốc ASR khớp nhất trong video + frame id ảo nộp được.

    Trả (observation, {frame_id: score}). Frame id được đăng ký vào frames_meta
    RAM (register_virtual_frame) nên build_search_results dựng được SearchResult
    dù không có ảnh keyframe tại đó.
    """
    from services.asr_service import locate_in_video
    from services.metadata_service import frames_in_video, register_virtual_frame, video_fps

    if not video or not frames_in_video(video):
        return f"unknown video {video!r}", {}
    hits = locate_in_video(video, query, top=3)
    if not hits:
        return f"no ASR match for {query!r} in {video}", {}
    fps = video_fps(video)
    found: Dict[str, float] = {}
    lines = [f"ASR moments in {video} for {query!r} (fps={fps:.2f}):"]
    for h in hits:
        # Giữa segment: thầy đang nói về slide thì slide đang hiện; đầu segment
        # hay dính slide trước.
        mid_ms = (int(h["start_ms"]) + int(h.get("end_ms", h["start_ms"]))) // 2
        fid = register_virtual_frame(video, round(mid_ms / 1000 * fps))
        found[fid] = float(h["score"])
        lines.append(f"  {fid} [{h['start_ms'] // 1000}-{int(h.get('end_ms', 0)) // 1000}s] "
                     f"({h['score']:.2f}) \"{h.get('text', '')[:140]}\"")
    lines.append("You may put these ids in final.frame_ids.")
    return "\n".join(lines), found


_LECTURE_WORDS = ("bài giảng", "giảng", "giáo viên", "thầy", "cô giáo", "slide",
                  "bảng số liệu", "đề thi", "thptqg", "câu hỏi môn", "lecture",
                  "teacher", "lesson", "exam question")


def _lecture_like(plan: dict) -> bool:
    """Yêu cầu có phải về video bài giảng / slide không (heuristic từ khoá trên
    query gốc + query tiếng Anh của plan)."""
    from services.text_norm import fold

    text = " ".join(str(plan.get(k, ""))
                    for k in ("user_query", "query", "scene_keywords", "reply"))
    text = fold(text) + " " + text.lower()
    return any(fold(w) in text or w in text for w in _LECTURE_WORDS)


def _timeline_rows(video: str, around: str, n: int, by_id: Dict[str, dict]) -> List[dict]:
    """n keyframe THẬT của `video` rải đều trong +-90s quanh `around` (frame id,
    hoặc rỗng = quanh frame tốt nhất của video trong kết quả), theo thứ tự thời
    gian. Trả SearchResult dict để lấy được bytes ảnh như view_frames thường."""
    from services.metadata_service import build_search_results, frames_in_range, get_meta

    n = max(1, min(int(n), 8))
    center_ms = None
    if around and around in by_id:
        center_ms = int(by_id[around]["timestamp_ms"])
    elif around:
        m = get_meta(around)
        if m.get("video_name") == video:
            center_ms = int(m["timestamp_ms"])
    if center_ms is None:
        cands = [r for r in by_id.values() if r["video_name"] == video]
        if not cands:
            return []
        center_ms = int(max(cands, key=lambda r: r["score"])["timestamp_ms"])
    frames = [f for f in frames_in_range(video, center_ms - 90_000, center_ms + 90_000)
              if not f.get("virtual")]
    if not frames:
        return []
    step = max(1, len(frames) // n)
    picked = frames[::step][:n]
    return build_search_results([{"id": f["id"], "score": 0.0} for f in picked], top_k=n)


def _merge_results(head: List[dict], tail: List[dict]) -> List[dict]:
    """head trước, phần còn lại của tail nối sau (bỏ trùng id), giữ độ dài tối đa
    bằng danh sách dài nhất trong hai cái."""
    seen = {r["id"] for r in head}
    merged = head + [r for r in tail if r["id"] not in seen]
    return merged[: max(len(head), len(tail))]


def _promote_frames(frame_ids: List[str], results: List[dict], virtual: Dict[str, float],
                    best_score: float) -> List[dict]:
    """Đưa các frame agent chỉ định lên đầu kết quả, giữ nguyên phần còn lại.

    Id phải là kết quả hiện có hoặc frame ảo do locate_by_asr sinh trong vòng
    này - id bịa ra bị bỏ qua, agent không thể nộp thứ nó chưa từng thấy.
    """
    if not frame_ids:
        return results
    from services.metadata_service import build_search_results

    by_id = {r["id"]: r for r in results}
    head: List[dict] = []
    for fid in frame_ids:
        fid = str(fid)
        if fid in by_id:
            head.append(by_id[fid])
        elif fid in virtual:
            built = build_search_results(
                [{"id": fid, "score": max(best_score, virtual[fid])}], top_k=1)
            head.extend(built)
    if not head:
        return results
    seen = {r["id"] for r in head}
    return head + [r for r in results if r["id"] not in seen]


async def react_refine(
    plan: dict, first_results: List[dict], top_k: int, model: str
) -> dict:
    """Vòng ReAct sau one-shot yếu. Trả {plan, results, reply, trace} (không raise)."""
    from routers.search_text import search_text  # local import: tránh vòng
    from services.graph_service import frame_node, label_stats
    from services.metadata_service import frame_bytes_many

    prompt = (_REACT_PROMPT
              .replace("{max_steps}", str(settings.react_max_steps))
              .replace("{threshold}", str(settings.react_score_threshold))
              .replace("{query_summary}", json.dumps(
                  {k: plan[k] for k in ("query", "objects", "scene_keywords")},
                  ensure_ascii=False)))
    parts: List[dict] = [{"text": prompt},
                         {"text": "Observation 0 (first plan's results):\n"
                                  + _observe(first_results)}]

    best_results, best_plan = first_results, dict(plan)
    best_score = first_results[0]["score"] if first_results else 0.0
    trace: List[dict] = []
    tried: set = set()
    virtual: Dict[str, float] = {}  # frame_id ảo do locate_by_asr sinh -> điểm ASR
    promoted: List[str] = []        # frame agent chỉ định đưa lên đầu (final.frame_ids)
    asr_pin: Optional[tuple] = None  # (video, query) transcript ASR ghim gần nhất
    react_model = settings.gemini_react_model or None

    for step in range(1, settings.react_max_steps + 1):
        text = _gemini_generate(parts, temperature=0.2, model=react_model,
                                task="react")
        if text is None:
            print(f"[react] step {step}: LLM returned None - stop")
            break
        msg = _parse_json_obj(text)
        if msg is None:
            print(f"[react] step {step}: unparseable reply ({len(text)} chars) {text!r} - stop")
            break
        thought = str(msg.get("thought", ""))[:300]
        action = msg.get("action")

        if not action or "final" in msg:
            final = msg.get("final") or {}
            reply = str(final.get("reply", "")) or plan["reply"]
            trace.append({"thought": thought, "action": None,
                          "frame_ids": list(final.get("frame_ids") or [])})
            best_plan["reply"] = reply
            promoted = list(final.get("frame_ids") or [])
            break

        tool = action.get("tool", "")
        args = action.get("args") or {}
        trace.append({"thought": thought, "action": {"tool": tool, "args": args}})
        parts.append({"text": json.dumps(
            {"thought": thought, "action": action}, ensure_ascii=False)})

        key = json.dumps(action, sort_keys=True, ensure_ascii=False)
        if key in tried:
            obs = "You already tried this EXACT action. Change the query/filters or finish."
        elif tool == "search":
            tried.add(key)
            res = await search_text(
                query=str(args.get("query", "")) or plan["query"],
                top_k=top_k, model=model, rerank=False, expand=False,
                objects=str(args.get("objects", "")), object_mode="boost",
                scene_keywords=str(args.get("scene_keywords", "")), scene_mode="boost",
            )
            results = res["results"]
            if results and results[0]["score"] > best_score:
                best_score = results[0]["score"]
                # GHÉP chứ không THAY: search của ReAct chạy một kênh, rerank=False,
                # expand=False nên danh sách của nó ngắn và nghèo đuôi hơn fan-out
                # ban đầu. Thay thẳng thì phần đuôi (rank 20-100) của fan-out bị
                # vứt đi - đo trên bộ eval: vid@100 51 -> 48, frm@100 36 -> 32,
                # tức mất đúng những câu mà bài nộp 100 dòng còn cứu được.
                best_results = _merge_results(results, best_results)
                best_plan.update(
                    query=str(args.get("query", "")) or plan["query"],
                    objects=str(args.get("objects", "")),
                    scene_keywords=str(args.get("scene_keywords", "")),
                )
            obs = _observe(results)
        elif tool == "search_transcript":
            tried.add(key)
            obs, pinned = observe_transcript_pinned(
                str(args.get("query", "")), str(args.get("channel", "asr")))
            if pinned:
                asr_pin = (pinned, str(args.get("query", "")))
        elif tool == "graph_labels":
            tried.add(key)
            q = str(args.get("contains", "")).lower()
            hits = [s for s in label_stats() if q in s["label"]][:15]
            obs = ", ".join(f"{s['label']}({s['scene_count']})" for s in hits) or "no matching label"
        elif tool == "scene_info":
            tried.add(key)
            scene = (frame_node(str(args.get("frame_id", ""))) or {}).get("scene") or {}
            obs = (f"[{scene.get('start_ms', 0)}–{scene.get('end_ms', 0)}ms] "
                   f"OCR=\"{scene.get('ocr', '')[:200]}\" ASR=\"{scene.get('asr', '')[:400]}\""
                   ) if scene else "frame not in graph"
        elif tool == "video_timeline":
            tried.add(key)
            obs = _observe_timeline(str(args.get("video", "")),
                                    args.get("from_s"), args.get("to_s"))
        elif tool == "locate_by_asr":
            tried.add(key)
            obs, found = _observe_locate(str(args.get("video", "")),
                                         str(args.get("query", "")))
            virtual.update(found)
        elif tool == "view_frames":
            tried.add(key)
            by_id = {r["id"]: r for r in best_results}
            if args.get("video"):
                # Chế độ timeline: n keyframe của MỘT video quanh một frame, theo
                # thứ tự thời gian - để agent kiểm ràng buộc "trước/sau", số đếm.
                rows = _timeline_rows(str(args["video"]), str(args.get("around", "")),
                                      int(args.get("n", 6) or 6), by_id)
                fids = [r["id"] for r in rows]
            else:
                fids = list(args.get("frame_ids", []))[:8]
                rows = [by_id.get(fid) for fid in fids]
            blobs = frame_bytes_many(
                [(r["video_name"], r["frame_name"]) for r in rows if r])
            it = iter(blobs)
            n = 0
            for fid, r in zip(fids, rows):
                img = None
                if r:
                    img = _image_part(next(it),
                                      suffix=r.get("frame_name", "").rsplit(".", 1)[-1])
                if img:
                    parts.append({"text": f"image of {fid}:"})
                    parts.append(img)
                    n += 1
            obs = f"{n} images attached above." if n else "no valid frame_id (must come from results)"
        else:
            obs = f"unknown tool {tool!r}"

        parts.append({"text": f"Observation {step}:\n{obs}"})
        print(f"[react] step {step}: {tool} -> {obs.splitlines()[0][:100]}")

    # Dù kết thúc kiểu gì (final, hết bước, reply hỏng): mốc ASR đã định vị
    # vẫn được dùng - bỏ đi thì các bước vừa chạy thành công cốc, kết quả y
    # như one-shot. Agent quên liệt kê frame_ids -> lấy mốc mạnh nhất.
    if not promoted and not virtual and asr_pin and _lecture_like(plan):
        # Agent đã ghim video bằng transcript rồi bỏ cuộc ("không xác định được
        # khung hình") trong khi video đó chưa lọt top-5 visual - đúng ca bài
        # giảng không có keyframe. Làm nốt việc nó bỏ dở: định vị mốc ASR.
        # Chỉ cho yêu cầu kiểu bài giảng: với tin tức/thể thao, video ASR ghim
        # được thường là video "cùng chủ đề" chứ không phải video đúng (đo trên
        # bộ eval: p2-24 đua xe, p2-26 slide kéo co bị kéo sang video sai).
        top_vids = {r["video_name"] for r in best_results[:5]}
        if asr_pin[0] not in top_vids:
            obs, found = _observe_locate(asr_pin[0], asr_pin[1])
            virtual.update(found)
            trace.append({"thought": "transcript fallback: locate_by_asr on pinned video",
                          "action": {"tool": "locate_by_asr",
                                     "args": {"video": asr_pin[0], "query": asr_pin[1]}}})
            print(f"[react] transcript fallback -> {obs.splitlines()[0][:100]}")
    if not promoted and virtual:
        promoted = sorted(virtual, key=virtual.get, reverse=True)[:2]
    best_results = _promote_frames(promoted, best_results, virtual, best_score)
    return {"plan": best_plan, "results": best_results,
            "reply": best_plan["reply"], "trace": trace}
