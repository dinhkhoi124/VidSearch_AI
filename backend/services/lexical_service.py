"""Chấm điểm lexical (BM25) cho các kênh text - thay cho so chuỗi liền.

Vì sao phải thay: cách cũ ở ocr/asr/caption_service đều là cùng một đoạn

    if q in text_l:
        hits[key] = text_l.count(q) / len(text_l.split())

tức lấy TOÀN BỘ query làm một chuỗi liền. Query nhiều từ ("phát hiện hai người
tử vong dưới kênh") gần như không bao giờ xuất hiện nguyên văn trong OCR một
frame, nên nhánh này trả rỗng và `ocr_exact_bonus = 0.5` trở thành số trang trí.
Thêm nữa `count/len` coi mọi từ quan trọng như nhau: "của" và "sụt lún" cùng
trọng số.

BM25 sửa cả hai: chấm theo từng term, term hiếm (IDF cao) được trọng số lớn, và
chuẩn hoá theo độ dài document. Tự cài (~60 dòng) thay vì thêm `rank_bm25` vì ta
cần kiểm soát bước fold dấu ở `text_norm` - OCR tiếng Việt sai dấu liên tục nên
tokenizer phải bỏ dấu, thứ mà thư viện ngoài không cho can thiệp.

Điểm trả về đã chuẩn hoá về [0, 1] theo max của chính truy vấn đó, nên cộng
thẳng được với cosine ngữ nghĩa mà không phải chỉnh lại các `*_exact_bonus`.
"""
from __future__ import annotations

import math
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Hashable, List, Mapping, Optional, Tuple

from services.file_cache import Stamp, stamp
from services.text_norm import fold, tokens

# Tham số BM25 chuẩn (Robertson & Zaragoza). k1 điều tiết mức bão hoà theo tần
# suất, b mức phạt document dài.
_K1 = 1.5
_B = 0.75

# Điểm cuối = (1-w)*bm25 + w*phrase. Giữ lại tín hiệu precision cao của cách cũ
# (cả cụm xuất hiện nguyên văn) mà không để nó lấn át BM25 như trước.
_PHRASE_WEIGHT = 0.3


class Bm25Index:
    """Inverted index trên token đã fold dấu.

    Với OCR (~55k doc × ~20 token) thì postings ~1.1M cặp - vài chục MB, nạp một
    lần rồi dùng lại cho mọi truy vấn.
    """

    __slots__ = ("postings", "doclen", "avgdl", "n_docs", "_idf", "texts")

    def __init__(self, corpus: Mapping[Hashable, str]):
        self.postings: Dict[str, List[Tuple[Hashable, int]]] = defaultdict(list)
        self.doclen: Dict[Hashable, int] = {}
        self.texts: Mapping[Hashable, str] = corpus

        total = 0
        for key, text in corpus.items():
            tf = Counter(tokens(text))
            if not tf:
                continue
            length = sum(tf.values())
            self.doclen[key] = length
            total += length
            for token, freq in tf.items():
                self.postings[token].append((key, freq))

        self.n_docs = len(self.doclen)
        self.avgdl = (total / self.n_docs) if self.n_docs else 1.0
        self._idf: Dict[str, float] = {}

    def idf(self, token: str) -> float:
        """IDF dạng có làm mượt; token phổ biến quá nửa corpus được ép về ~0."""
        if token not in self._idf:
            df = len(self.postings.get(token, ()))
            self._idf[token] = max(
                0.0, math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))
            )
        return self._idf[token]

    def scores(self, query: str, limit: Optional[int] = None) -> Dict[Hashable, float]:
        """{key: điểm trong [0,1]} cho các document có ít nhất một term của query."""
        qt = tokens(query)
        if not qt or not self.n_docs:
            return {}

        acc: Dict[Hashable, float] = defaultdict(float)
        for token in set(qt):
            idf = self.idf(token)
            if idf <= 0.0:
                continue
            for key, freq in self.postings.get(token, ()):
                dl = self.doclen[key]
                denom = freq + _K1 * (1.0 - _B + _B * dl / self.avgdl)
                acc[key] += idf * freq * (_K1 + 1.0) / denom

        if not acc:
            return {}

        # Cắt về `limit` TRƯỚC khi cộng phrase bonus. Bonus phải fold lại text của
        # từng ứng viên - làm trên cả chục nghìn hit thì tốn nửa giây, trong khi
        # document chứa nguyên cụm query chắc chắn đã chứa mọi term của nó nên
        # điểm BM25 vốn đã cao, không thể nằm ngoài top-`limit`.
        keys = sorted(acc, key=acc.get, reverse=True)
        if limit is not None:
            keys = keys[:limit]

        top = acc[keys[0]] or 1.0
        phrase = fold(query)
        out: Dict[Hashable, float] = {}
        for key in keys:
            score = acc[key] / top
            if phrase and phrase in fold(self.texts.get(key, "")):
                score = (1.0 - _PHRASE_WEIGHT) * score + _PHRASE_WEIGHT
            out[key] = score
        return out


# --- cache: một index cho mỗi (tên kênh, phiên bản file nguồn) -------------------

_INDEXES: Dict[str, Tuple[Stamp, Bm25Index]] = {}
_LOCK = threading.Lock()


def get_index(name: str, source: Path, corpus: Mapping[Hashable, str]) -> Bm25Index:
    """Index của kênh `name`, tự dựng lại khi `source` trên đĩa đổi.

    `source` là file dữ liệu gốc (ocr_data.json...). Gắn theo mtime của nó để khi
    dữ liệu Qwen mới được copy đè, index cũ không còn sống sót - đúng lý do
    `file_cache` tồn tại.
    """
    cur = stamp(source)
    hit = _INDEXES.get(name)
    if hit is not None and hit[0] == cur:
        return hit[1]

    with _LOCK:
        hit = _INDEXES.get(name)
        if hit is not None and hit[0] == cur:
            return hit[1]
        index = Bm25Index(corpus)
        print(f"[lexical] built BM25 '{name}': {index.n_docs} docs, "
              f"{len(index.postings)} terms, avgdl={index.avgdl:.1f}")
        _INDEXES[name] = (cur, index)
        return index


def clear() -> None:
    """Dùng cho test."""
    with _LOCK:
        _INDEXES.clear()


def substring_scores(query: str, corpus: Mapping[Hashable, str]) -> Dict[Hashable, float]:
    """Hành vi CŨ, giữ nguyên để `lexical_mode=substring` quay lui được 1:1.

    Không dùng text_norm ở đây - mục đích của nó là tái hiện chính xác cách cũ
    để so sánh A/B, nên phải giữ cả những chỗ chưa chuẩn hoá.
    """
    q = query.lower().strip()
    hits: Dict[Hashable, float] = {}
    if not q:
        return hits
    for key, text in corpus.items():
        text_l = text.lower()
        if q in text_l:
            hits[key] = text_l.count(q) / max(len(text_l.split()), 1)
    return hits
