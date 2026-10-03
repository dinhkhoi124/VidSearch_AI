"""Ensemble search - fuse retrieval scores from multiple backbones.

Each backbone sees the data differently (SigLIP: broad multilingual concepts;
Jina-CLIP v2: multilingual incl. Vietnamese, different training data), so a
frame missed by one is often surfaced by the other (Tran et al.,
arXiv:2504.08384, Alg. 3). Scores are normalised by each model's max before
the weighted sum, since cosine ranges differ between backbones:

    S(frame) = Σ_m  w_m * s_m(frame) / max(s_m)

Configured by settings.ensemble_models ("<model>:<weight>,..."). A model whose
encoder weights are unavailable (mock) or whose index is missing is skipped -
searching with a mock vector would inject noise, not signal. Nhưng nếu MỌI model
đều bị bỏ qua thì ném IndexUnavailable (-> 503) chứ không trả []: rỗng vì cấu
hình hỏng và rỗng vì query không khớp gì là hai chuyện khác hẳn nhau, mà nhìn
từ UI thì giống hệt.
"""
from __future__ import annotations

from typing import Callable, List, Tuple

import numpy as np

from config import get_settings
from services.embedding_service import has_real_encoder
from services.faiss_service import IndexUnavailable, search_index

settings = get_settings()


def parse_ensemble_models(spec: str = "") -> List[Tuple[str, float]]:
    """"siglip:0.6,jina:0.4" -> [("siglip", 0.6), ("jina", 0.4)].

    spec rỗng = lấy settings.ensemble_models (.env). Dấu phân cách nhận ",",
    "+" và cả KHOẢNG TRẮNG: UI gửi tổ hợp ad-hoc qua tham số `model` của URL
    dưới dạng "siglip512+metaclip", mà trong query string "+" là ký tự có thể
    bị proxy/tunnel giải mã thành khoảng trắng. Coi khoảng trắng cũng là dấu
    phân cách thì đường nào tới nơi cũng ra đúng danh sách.
    """
    out: List[Tuple[str, float]] = []
    text = (spec or settings.ensemble_models or "").replace("+", ",").replace(" ", ",")
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, w = part.partition(":")
        try:
            out.append((name.strip(), float(w) if w else 1.0))
        except ValueError:
            print(f"[ensemble] bỏ qua cấu hình không hợp lệ: {part!r}")
    return out


def is_ensemble(model: str) -> bool:
    """"ensemble" (theo .env) hay tổ hợp ad-hoc "siglip512+metaclip" từ UI.

    Nhận mọi dấu phân cách mà parse_ensemble_models hiểu — nếu không thì
    "siglip512 metaclip" (bản đã bị proxy đổi "+" thành khoảng trắng) sẽ lọt
    xuống nhánh search đơn với tên model không tồn tại.
    """
    model = (model or "").strip()
    return model == "ensemble" or any(sep in model for sep in ("+", ",", " "))


def ensemble_spec(model: str) -> str:
    """Chuỗi cấu hình ứng với `model`; "" = dùng .env."""
    model = (model or "").strip()
    return "" if model == "ensemble" else model


def primary_model(model: str) -> str:
    """Model ĐƠN đại diện cho một tổ hợp.

    Vài bước chỉ chạy được trong MỘT không gian vector — kNN graph, beam search
    temporal, reconstruct vector cho relevance feedback — nên phải quy tổ hợp về
    một thành viên: cái có trọng số cao nhất. Rơi về DEFAULT_MODEL nếu tổ hợp rỗng.
    """
    if not is_ensemble(model):
        return model
    members = parse_ensemble_models(ensemble_spec(model))
    if not members:
        return settings.default_model
    return max(members, key=lambda pair: pair[1])[0]


def ensemble_label(model: str) -> str:
    """Tên gọn để in log / báo lỗi."""
    members = parse_ensemble_models(ensemble_spec(model))
    return " + ".join(name for name, _ in members) or "(rỗng)"


def ensemble_search(
    encode: Callable[[str], np.ndarray], top_k: int, spec: str = "",
) -> List[dict]:
    """Run `encode(model) -> vector` + FAISS per configured model, fuse scores.

    spec rỗng = tổ hợp trong .env; khác rỗng = tổ hợp người dùng chọn cho ĐÚNG
    lượt search này (không đụng vào cấu hình chung — cả nhóm dùng chung một
    backend, đổi trạng thái toàn cục giữa buổi thi là đổi kết quả của người
    khác mà họ không biết).

    Returns [{id, score}, ...] sorted desc, same shape as search_index().
    """
    fused: dict[str, float] = {}
    used = 0
    skipped: List[str] = []
    for model, weight in parse_ensemble_models(spec):
        if weight <= 0:
            continue
        if not has_real_encoder(model):
            print(f"[ensemble] {model}: encoder không khả dụng -> bỏ qua")
            skipped.append(f"{model} (thiếu encoder)")
            continue
        try:
            raw = search_index(encode(model), top_k=top_k, model=model)
        except (ValueError, IndexUnavailable) as e:  # lệch chiều vector, hoặc thiếu index
            print(f"[ensemble] {model}: {e} -> bỏ qua")
            skipped.append(f"{model} ({e})")
            continue
        if not raw:
            continue
        smax = max(r["score"] for r in raw)
        if smax <= 0:
            continue
        for r in raw:
            fused[r["id"]] = fused.get(r["id"], 0.0) + weight * r["score"] / smax
        used += 1

    # Không nhánh nào chạy được = ensemble trả rỗng. Trước đây chỉ in log rồi trả
    # [] - nhìn từ UI không phân biệt được với "search xong, không có kết quả".
    if not used:
        source = f"tổ hợp {spec!r}" if spec else "ENSEMBLE_MODELS"
        raise IndexUnavailable(
            f"{source} không có model nào dùng được: "
            + ("; ".join(skipped) if skipped else "danh sách rỗng")
        )
    hits = [{"id": fid, "score": s} for fid, s in fused.items()]
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]
