"""LLM query expansion - dịch + sinh biến thể tiếng Anh cho query (Gemini).

Mọi backbone visual của hệ (SigLIP, CLIP, cả BLIP reranker) đều thiên tiếng
Anh; query tiếng Việt vào thẳng cho kết quả kém tới sai hẳn. Theo Ngo et al.
(arXiv:2512.12935, Fig. 3), mỗi query được LLM biến thành N biến thể tiếng Anh
- biến thể đầu BẮT BUỘC là bản dịch trực tiếp, các biến thể sau đổi cách diễn
đạt / thêm bối cảnh - rồi search song song và gộp điểm theo max từng frame.

Gọi Gemini qua REST (generativelanguage.googleapis.com) với response JSON.
Không có GEMINI_API_KEY / lỗi mạng / JSON hỏng -> trả None, caller giữ nguyên
query gốc - API không bao giờ vỡ vì service này. Kết quả được cache theo query
trong process để không gọi lặp khi người dùng bấm search lại.
"""
from __future__ import annotations

import json
import threading
from typing import Dict, List, Optional

from config import get_settings

settings = get_settings()

_cache: Dict[str, Optional[List[str]]] = {}
_lock = threading.Lock()

_TIMEOUT_S = 10

_PROMPT = """You assist a video keyframe search engine over Vietnamese news broadcasts.
The user query below may be Vietnamese or English.

Return ONLY a JSON object: {{"queries": ["...", "...", "...", "..."]}}
Rules:
- Exactly 4 short English search queries describing the visual scene.
- queries[0] MUST be a direct, faithful English translation of the user query.
- The other 3 are variations: rephrase, add likely scene context, or change viewpoint.
- NEVER generalize the main subject: "tiger" must stay "tiger" in every variation,
  not "wild cat" / "feline" / "animal". Vary the wording around it instead.
- Keep proper names, on-screen text and numbers unchanged (do not translate them).
- The image encoder sees STILL frames only. Camera/editing words (pan, tilt, zoom,
  transition, static shot, close-up sequence, "clip starts/ends with") are invisible
  to it - DROP them and describe only what is visible inside one frame.
- The opposite of generalizing: when the query names a broad CATEGORY ("a seafood
  ingredient", "a fruit", "an animal"), queries[1..3] should each GUESS a concrete
  instance that fits the description (e.g. seafood -> squid / shrimp / fish), keeping
  the rest of the scene. A right guess ranks the true frame far above the category word.
- No explanations, no markdown, JSON only.

User query: {q}"""


def is_available() -> bool:
    # Đi qua router LLM chung (Gemini hoặc endpoint OpenAI-compatible)
    from services.agent_service import is_available as agent_llm_available

    return agent_llm_available()


_KEYWORD_PROMPT = """Translate the Vietnamese filter keywords below into ENGLISH keyword sets
for SUBSTRING matching against machine-generated captions of Vietnamese news keyframes.

Return ONLY a JSON object: {{"keywords": ["...", "...", "..."]}}
Rules:
- 2 or 3 alternative keyword sets. A caption matches if it contains EVERY word of
  ANY ONE set, so each set must be SHORT: 1-3 lowercase words, no punctuation.
- Set 1 = the single most essential noun (or noun pair). Sets 2-3 = the same idea
  with the SYNONYMS a caption writer might use instead
  ("motorbike" / "motorcycle" / "scooter"; "flag" / "banner").
- Drop prepositions, articles and generic verbs ("on", "the", "is", "running").
  Keep an action word only when it IS the subject of the request.
- Use the plainest wording a caption generator would write ("xe máy" -> "motorbike",
  "người đàn ông" -> "man", "cờ đỏ sao vàng" -> "red flag").
- Keep proper names unchanged.

Keywords: {q}"""

_kw_cache: Dict[str, Optional[List[str]]] = {}

# Từ chức năng: giữ lại chỉ làm điều kiện AND thừa, caption có thể diễn đạt khác
# ("on the road" / "along a street") nên chúng chỉ khiến bộ lọc trượt.
_STOPWORDS = {
    "a", "an", "the", "of", "on", "in", "at", "to", "with", "and", "or",
    "is", "are", "was", "were", "be", "being", "that", "this", "there",
}


def looks_vietnamese(text: str) -> bool:
    """Có dấu tiếng Việt (ký tự ngoài ASCII) thì chắc chắn không phải tiếng Anh.

    Tiếng Việt KHÔNG DẤU ("xe may") lọt lưới — nhưng đoán bừa còn tệ hơn: bộ lọc
    caption cũng nhận từ khoá tiếng Anh, dịch nhầm chuỗi tiếng Anh thành thứ
    khác là làm hỏng thứ đang chạy đúng.
    """
    return any(ord(c) > 127 for c in text)


def translate_keywords(text: str) -> Optional[List[str]]:
    """Từ khoá lọc tiếng Việt -> CÁC bộ từ khoá tiếng Anh. None = không dịch được.

    Trả nhiều bộ ngắn thay vì một chuỗi dài vì bộ lọc caption khớp AND trong một
    bộ: "motorbike running on road" đòi caption chứa đủ 4 từ, mà caption thật hay
    viết "riding a motorcycle" — lọc sạch kết quả. Nhiều bộ ngắn phủ đúng cách
    diễn đạt khác nhau (motorbike / motorcycle / scooter) và OR với nhau.

    Tách khỏi expand_query vì hai việc khác nhau: expand_query sinh CÂU mô tả
    cảnh cho backbone visual, còn ở đây cần vài TỪ để so khớp chuỗi với caption.
    Cache riêng, cùng lý do: gõ đi gõ lại một bộ lọc không nên tốn thêm request.
    """
    q = text.strip()
    if not q or not is_available():
        return None
    with _lock:
        if q in _kw_cache:
            return _kw_cache[q]

    result = _call_keyword_llm(q)
    with _lock:
        _kw_cache[q] = result
    return result


def _call_keyword_llm(q: str) -> Optional[List[str]]:
    from services.agent_service import _gemini_generate

    try:
        text = _gemini_generate([{"text": _KEYWORD_PROMPT.format(q=q)}], temperature=0.0,
                                task="expand")
        if text is None:
            return None
        raw = json.loads(text).get("keywords", [])
        # Model thỉnh thoảng trả một chuỗi thay vì mảng — nhận cả hai.
        if isinstance(raw, str):
            raw = [raw]
        sets, seen = [], set()
        for item in raw:
            if not isinstance(item, str):
                continue
            words = [w for w in item.lower().split() if w not in _STOPWORDS]
            # Cắt còn 3 từ: mỗi từ thêm vào là một điều kiện AND nữa, mà bộ lọc
            # dài thì trượt hết chứ không "lọc chặt hơn".
            phrase = " ".join(words[:3]).strip()
            if phrase and phrase not in seen:
                seen.add(phrase)
                sets.append(phrase)
        if not sets:
            return None
        print(f"[caption-filter] {q!r} -> {sets}")
        return sets[:3]
    except Exception as e:  # noqa: BLE001 - lỗi nào cũng giữ nguyên từ khoá gốc
        print(f"[caption-filter] không dịch được ({e!r}); giữ từ khoá gốc")
        return None


def clear_failed_cache() -> int:
    """Xoá các entry THẤT BẠI (None = "LLM không trả lời, dùng query gốc").

    Gọi sau khi đổi key: nếu không, mọi query đã trượt lúc cạn quota sẽ vĩnh
    viễn trượt trong cả phiên. Bản dịch THÀNH CÔNG thì giữ — chúng vẫn đúng và
    tốn tiền mới có.
    """
    with _lock:
        failed = [q for q, v in _cache.items() if v is None]
        for q in failed:
            del _cache[q]
        # Cùng lý do cho cache dịch từ khoá lọc caption.
        failed_kw = [q for q, v in _kw_cache.items() if v is None]
        for q in failed_kw:
            del _kw_cache[q]
    return len(failed) + len(failed_kw)


def expand_query(query: str) -> Optional[List[str]]:
    """Trả về danh sách biến thể tiếng Anh (phần tử 0 = bản dịch trực tiếp),
    hoặc None nếu không khả dụng -> caller dùng query gốc."""
    if not is_available():
        return None

    q = query.strip()
    with _lock:
        if q in _cache:
            return _cache[q]

    result = _call_llm(q)
    with _lock:
        _cache[q] = result
    return result


def _call_llm(q: str) -> Optional[List[str]]:
    # Router LLM chung của agent_service: Gemini chính, OpenAI-compat dự phòng
    # (theo llm_provider). temperature 0: biến thể dịch phải tất định giữa các
    # lần chạy - cache chỉ sống trong process, restart là gọi lại.
    from services.agent_service import _gemini_generate

    try:
        text = _gemini_generate([{"text": _PROMPT.format(q=q)}], temperature=0.0,
                                task="expand")
        if text is None:
            return None
        queries = json.loads(text).get("queries", [])
        queries = [s.strip() for s in queries if isinstance(s, str) and s.strip()]
        # dedupe giữ thứ tự (biến thể 0 = bản dịch phải đứng đầu)
        seen, out = set(), []
        for s in queries:
            if s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        if not out:
            return None
        print(f"[query-expand] {q!r} -> {out}")
        return out[:4]
    except Exception as e:  # noqa: BLE001 - mọi lỗi -> dùng query gốc
        print(f"[query-expand] unavailable ({e!r}); dùng query gốc")
        return None
