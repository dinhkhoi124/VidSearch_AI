"""Gộp các frame TRÙNG THỊ GIÁC ở tầng kết quả, không phân biệt video.

Vì sao cần, khi data_processing bước 03 đã dedup rồi: bước đó chỉ so mỗi frame
với frame ĐÃ GIỮ liền trước TRONG CÙNG VIDEO (xem DEDUP_THRESHOLD). Kho AIC có
nhiều bản của cùng một phóng sự nằm ở các video khác nhau, và hai bản đó không
bao giờ được đem so với nhau — nên top-K vẫn có thể là vài trăm ảnh giống hệt
đến từ vài chục video.

Cách gộp: leader clustering trên chính vector đã nằm trong FAISS index
(IndexFlatIP trên vector đã L2-norm -> tích vô hướng = cosine). Duyệt theo thứ
tự điểm giảm dần; frame chưa thuộc cụm nào trở thành ĐẠI DIỆN, mọi frame còn
lại có cosine >= ngưỡng với nó trở thành bản trùng của nó.

Không xoá bản trùng — trả kèm đại diện để UI bung ra xem. Frame đúng để nộp
nhiều khi là bản thứ bảy của cụm chứ không phải bản điểm cao nhất.

Frame không có trong index của model đang dùng (bước 03 giữ tập khác nhau cho
từng model; ứng viên có thể do một thành viên ensemble khác lôi về) luôn được
giữ nguyên làm đại diện — không có vector thì không có cơ sở để gộp.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np

from config import get_settings
from services.faiss_service import reconstruct_matrix

settings = get_settings()


def group_duplicates(
    raw: List[dict],
    model: str,
    threshold: Optional[float] = None,
    max_candidates: Optional[int] = None,
) -> List[dict]:
    """[{id, score}, ...] đã sort giảm dần -> [{id, score, duplicates: [...]}].

    Thứ tự đại diện giữ nguyên thứ tự điểm của đầu vào. Ngưỡng <= 0 = tắt.
    """
    thr = settings.result_dedup_threshold if threshold is None else float(threshold)
    if thr <= 0 or len(raw) < 2:
        return [{**r, "duplicates": []} for r in raw]

    # Gram matrix là n^2 nên phải có trần: pool có thể lên tới top_k * 4. Phần
    # đuôi vượt trần đi thẳng ra ngoài, không gộp — thà sót vài ô trùng ở cuối
    # bảng còn hơn để một truy vấn top_k=1000 treo cả giây.
    cap = int(settings.result_dedup_max_candidates
              if max_candidates is None else max_candidates)
    head, tail = raw[:cap], raw[cap:]

    rows, matrix = reconstruct_matrix([r["id"] for r in head], model=model)
    if matrix is None:
        return [{**r, "duplicates": []} for r in raw]

    # Vector trong index đã L2-norm nên tích vô hướng CHÍNH LÀ cosine. Chuẩn hoá
    # lại lần nữa cho chắc: index cũ build trước khi bước 03 gọi normalize_L2 sẽ
    # cho cosine > 1 và gộp sạch mọi thứ.
    matrix /= np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)
    gram = matrix @ matrix.T

    pos = {fid: i for i, fid in enumerate(rows)}
    by_id = {r["id"]: r for r in head}
    taken = np.zeros(len(rows), dtype=bool)
    out: List[dict] = []

    for item in head:
        i = pos.get(item["id"])
        if i is None:                      # không có vector -> luôn là đại diện
            out.append({**item, "duplicates": []})
            continue
        if taken[i]:
            continue
        taken[i] = True
        members = np.flatnonzero((gram[i] >= thr) & ~taken)
        taken[members] = True
        # `rows` giữ nguyên thứ tự của head (đã sort theo điểm) và flatnonzero
        # trả chỉ số tăng dần -> bản trùng ra theo điểm giảm dần, khỏi sort lại.
        out.append({
            **item,
            "duplicates": [{**by_id[rows[j]], "duplicates": []} for j in members],
        })

    out.extend({**r, "duplicates": []} for r in tail)
    return out
