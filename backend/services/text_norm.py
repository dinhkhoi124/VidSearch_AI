"""Chuẩn hoá text tiếng Việt dùng chung cho mọi kênh lexical (OCR / ASR / caption).

Ba mức, dùng cho ba mục đích khác nhau:

    nfc(s)    hợp nhất biểu diễn Unicode  - "tiếng" (tổ hợp) == "tiếng" (dựng sẵn)
    norm(s)   nfc + lower + gộp khoảng trắng - so khớp phân biệt dấu
    fold(s)   norm + BỎ dấu                - so khớp chịu được OCR sai dấu

Vì sao cần `nfc`: tiếng Việt có hai cách biểu diễn cùng một chữ (dựng sẵn NFC vs
tổ hợp NFD). EasyOCR/Qwen/người dùng gõ tay có thể sinh ra dạng khác nhau; nếu
không hợp nhất thì `"tiếng" in text` trượt một cách ngẫu nhiên mà không ai hiểu vì sao.

Vì sao cần `fold`: OCR trên frame broadcast sai dấu liên tục
(`TỈNH TRaNG` ← *TÌNH TRẠNG*, `thủy lgi` ← *thủy lợi*, `mẩl tích` ← *mất tích*).
So khớp bỏ dấu biến lỗi đó từ *trượt hoàn toàn* thành *vẫn tìm được*, đổi lại
mất phân biệt `hoa`/`hòa`/`hóa` - đánh đổi có chủ đích, xem `ocr_filter_mode`.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import List, Tuple

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[0-9a-z]+")

# NFD tách được dấu của mọi nguyên âm tiếng Việt, NHƯNG KHÔNG tách được đ/Đ
# (U+0111/U+0110 là ký tự độc lập, không phải d + dấu gạch). Phải map tay.
_D_STROKE = str.maketrans({"đ": "d", "Đ": "D"})


def nfc(s: str) -> str:
    """Hợp nhất về dạng dựng sẵn (NFC)."""
    return unicodedata.normalize("NFC", s or "")


def norm(s: str) -> str:
    """nfc + lower + gộp khoảng trắng. Giữ nguyên dấu."""
    return _WS.sub(" ", nfc(s).lower()).strip()


@lru_cache(maxsize=8192)
def fold(s: str) -> str:
    """norm + bỏ dấu. `Đá lăn` -> `da lan`, `thủy lợi` -> `thuy loi`.

    Cache vì cùng một keyword/query bị fold lặp lại rất nhiều lần trong một
    request (mỗi document một lần ở nhánh so khớp).
    """
    decomposed = unicodedata.normalize("NFD", norm(s).translate(_D_STROKE))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def tokens(s: str) -> List[str]:
    """Token đã fold: chỉ [0-9a-z], bỏ mọi dấu câu và ký tự rác OCR."""
    return _TOKEN.findall(fold(s))


def token_set(s: str) -> frozenset:
    return frozenset(tokens(s))


def contains(text: str, keyword: str, folded: bool = True) -> bool:
    """Keyword có trong text không?

    folded=True (mặc định): so bỏ dấu, và chấp nhận cả trường hợp mọi token của
    keyword đều xuất hiện trong text dù không liền nhau - OCR hay chèn rác
    (đồng hồ, logo) vào giữa cụm từ, làm vỡ so khớp chuỗi liền.
    folded=False: hành vi cũ, so chuỗi liền có phân biệt dấu.
    """
    if not keyword:
        return True
    if not folded:
        return norm(keyword) in norm(text)

    ft, fk = fold(text), fold(keyword)
    if fk in ft:
        return True
    kt = tokens(keyword)
    return bool(kt) and token_set(text).issuperset(kt)


def split_words(s: str) -> Tuple[str, ...]:
    """Dùng cho thống kê n-gram ở bước hậu xử lý; giữ dấu, chỉ tách khoảng trắng."""
    return tuple(norm(s).split())
