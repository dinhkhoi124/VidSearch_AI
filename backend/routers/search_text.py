from typing import List

from fastapi import APIRouter, HTTPException

from config import get_settings
from models.schemas import SearchResponse
from services.embedding_service import encode_text
from services.ensemble_service import (
    ensemble_search,
    ensemble_spec,
    is_ensemble,
    primary_model,
)
from services.faiss_service import search_index
from services.graph_service import (
    aggregate_scene_scores,
    apply_object_filter,
    apply_scene_text_filter,
    expand_knn,
)
from services.dedup_service import group_duplicates
from services.metadata_service import build_search_results, filter_candidates
from services.neighbor_service import aggregate_neighbor_scores
from services.query_expansion_service import (
    expand_query,
    looks_vietnamese,
    translate_keywords,
)
from services.rerank_service import rerank_frames

router = APIRouter()
settings = get_settings()


async def _fuse_text_channels(visual: List[dict], ocr_kw: str, asr_kw: str,
                              caption_kw: str, top_k: int, model: str) -> List[dict]:
    """Trộn pool visual với các kênh chữ người dùng gõ vào ô lọc (text_mode=fuse).

    Khác `filter_candidates` ở BẢN CHẤT: ô lọc không còn là cổng AND vứt ứng
    viên, mà thành một kênh retrieval RIÊNG - `search_ocr` / `search_asr` /
    `search_captions` tự tìm trên index chữ của chúng, rồi điểm mỗi kênh được
    chuẩn hoá theo max và CỘNG theo frame (đúng cơ chế fan-out của /agent/chat,
    xem agent_service.fuse_step_lists). Nhờ vậy frame mà visual xếp hạng thấp
    nhưng OCR khớp nguyên văn vẫn nổi lên - điều cổng AND không bao giờ làm
    được, vì frame đó chưa từng vào pool.

    KHÔNG gọi kênh "visual" của _run_step: pool visual đã tính sẵn ở trên,
    gọi lại vừa thừa một lượt search vừa đệ quy ngược vào chính route này.
    """
    from services.agent_service import fuse_step_lists, run_step_lists

    steps = [{"channel": ch, "query": q.strip(), "objects": "", "scene_keywords": ""}
             for ch, q in (("ocr", ocr_kw), ("asr", asr_kw), ("caption", caption_kw))
             if q.strip()]
    if not steps:
        return visual

    lists = await run_step_lists(steps, top_k=top_k, model=model)
    fused = fuse_step_lists(
        [{"channel": "visual", "query": "(pool visual)"}] + steps,
        [visual] + lists,
        {"visual": settings.search_fuse_visual_weight},
    )
    # Chặn trần pool trước các bước đắt phía sau (aggregation, dedup, rerank) -
    # ba kênh chữ có thể góp vài nghìn frame mà chỉ top mới có cơ vào kết quả.
    return fused[: max(top_k * 4, 200)]


def _retrieve(query: str, model: str, top_k: int) -> List[dict]:
    # model = "ensemble" (theo .env) hoặc tổ hợp ad-hoc UI gửi lên, vd
    # "siglip512+metaclip" - trộn đúng những model đó cho riêng lượt search này.
    if is_ensemble(model):
        return ensemble_search(lambda m: encode_text(query, model=m), top_k=top_k,
                               spec=ensemble_spec(model))
    return search_index(encode_text(query, model=model), top_k=top_k, model=model)


@router.post("/search_text", response_model=SearchResponse)
async def search_text(
    query: str,
    top_k: int = 25,
    model: str = settings.default_model,
    ocr_keywords: str = "",
    asr_keywords: str = "",
    # Lọc theo caption sinh sẵn (Qwen2.5-VL, tiếng Anh): mọi từ phải xuất hiện
    # trong caption của frame. Xem caption_service.frame_has_caption_text.
    caption_keywords: str = "",
    # Ba ô lọc trên hoạt động thế nào:
    #   filter (mặc định) - cổng AND: chỉ giữ ứng viên visual có đủ chữ. Nhanh,
    #                       chính xác, nhưng recall trần đúng bằng pool visual.
    #   fuse              - kênh retrieval riêng, cộng điểm với visual. Kéo được
    #                       frame mà visual trượt hẳn; xem _fuse_text_channels.
    text_mode: str = "filter",
    rerank: bool = True,
    expand: bool = True,
    objects: str = "",
    object_mode: str = "boost",
    scene_keywords: str = "",
    scene_mode: str = "boost",
    # Gộp frame trùng thị giác (kể cả khác video) - xem services/dedup_service.
    # dedup_threshold <= 0: dùng RESULT_DEDUP_THRESHOLD trong config.
    dedup: bool = True,
    dedup_threshold: float = 0.0,
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Dịch + mở rộng query thành các biến thể tiếng Anh (Gemini). Không có key
    # hoặc lỗi -> giữ query gốc. queries[0] luôn là bản dịch trực tiếp.
    queries = [query]
    if expand:
        expanded = expand_query(query)
        if expanded:
            queries = expanded

    if len(queries) == 1:
        raw = _retrieve(queries[0], model, top_k * 4)
    else:
        # Search từng biến thể rồi CỘNG điểm theo frame. Điểm mỗi biến thể phải
        # chuẩn hoá theo max của chính nó trước khi trộn - thang cosine giữa các
        # query khác nhau một cách hệ thống (query chung chung cho điểm cao đại
        # trà), gộp điểm thô sẽ để biến thể "lạm phát" chèn frame sai lên giữa
        # bảng. Bản dịch trực tiếp giữ trọng số 1.0.
        #
        # Trước đây lấy MAX qua các biến thể với lập luận "biến thể tương quan
        # nhau, trúng nhiều bản diễn đạt không phải bằng chứng mới". Đo trên bộ
        # test 23 query (26/8, ensemble .env) cho kết quả ngược lại: max làm 3
        # biến thể phụ vô dụng đúng bằng 0 (kết quả giống hệt chỉ-q0 ở mọi mức),
        # còn cộng nâng @1 11->14, @100 20->21 - frame khớp cả 4 cách diễn đạt
        # đáng tin hơn frame chỉ khớp một. Bền với trọng số phụ (0.6-1.0 cùng
        # kết quả), nên giữ expansion_variant_weight như cũ.
        fused: dict[str, float] = {}
        for i, q in enumerate(queries):
            hits = _retrieve(q, model, top_k * 4)
            if not hits:
                continue
            smax = max(h["score"] for h in hits)
            if smax <= 0:
                continue
            w = 1.0 if i == 0 else settings.expansion_variant_weight
            for r in hits:
                fused[r["id"]] = fused.get(r["id"], 0.0) + w * r["score"] / smax
        raw = [{"id": fid, "score": s} for fid, s in fused.items()]
        raw.sort(key=lambda x: x["score"], reverse=True)
        raw = raw[: top_k * 4]

    # Caption sinh bằng TIẾNG ANH -> từ khoá lọc tiếng Việt (có dấu) được LLM
    # dịch trước. Giữ CẢ hai bộ: bản dịch tồi hoặc LLM chết quota thì bản gốc
    # vẫn lọc, thay vì lọc sạch kết quả rồi để người dùng đoán vì sao rỗng.
    caption_filter = caption_keywords
    caption_translation = None
    caption_query = caption_keywords.strip()   # bản dùng cho kênh fuse (1 chuỗi)
    if caption_keywords.strip() and looks_vietnamese(caption_keywords):
        translated = translate_keywords(caption_keywords)
        if translated:
            # Nhiều bộ ngắn, khớp MỘT bộ là đủ (xem translate_keywords).
            caption_filter = [caption_keywords, *translated]
            caption_translation = " / ".join(translated)
            # Index caption là tiếng Anh -> kênh fuse phải hỏi bằng bản dịch.
            caption_query = translated[0]

    # Graph layer (no-op nếu chưa build data/graph - xem graph_service):
    # kNN expansion mở rộng pool trước, rồi bonus theo cửa sổ thời gian
    # (neighbor) + theo ranh giới cảnh (scene), cuối cùng lọc/boost object.
    raw = expand_knn(raw, model=primary_model(model))
    # fuse: trộn kênh chữ TRƯỚC aggregation, đúng thứ tự của fan-out ở
    # /agent/chat - frame kênh chữ mang về cũng được gộp bằng chứng theo cụm
    # thời gian và theo cảnh, thay vì chỉ frame visual mới được.
    fuse = text_mode == "fuse" and any(
        s.strip() for s in (ocr_keywords, asr_keywords, caption_query))
    if fuse:
        raw = await _fuse_text_channels(
            raw, ocr_keywords, asr_keywords, caption_query, top_k=top_k, model=model)
    raw = aggregate_neighbor_scores(raw)
    raw = aggregate_scene_scores(raw)
    if objects.strip():
        raw = apply_object_filter(raw, objects, mode=object_mode)
    if scene_keywords.strip():
        raw = apply_scene_text_filter(raw, scene_keywords, mode=scene_mode)

    # THỨ TỰ QUAN TRỌNG: lọc -> gộp trùng -> rerank. rerank_frames chỉ chấm
    # rerank_candidates (100) ứng viên đầu bảng và mỗi ứng viên tốn một lượt
    # kéo ảnh + một lượt BLIP. Chấm trước khi lọc/gộp thì 100 lượt đó đổ vào
    # các frame sắp bị vứt và vào hàng chục bản của CÙNG một hình - phần đuôi,
    # tức những frame thật sự khác nội dung, không bao giờ được chấm.
    if not fuse:
        raw = filter_candidates(raw, ocr_keywords, asr_keywords, caption_filter)
    if dedup:
        # Ensemble không có index riêng -> lấy vector ở backbone chính.
        raw = group_duplicates(
            raw, model=primary_model(model),
            threshold=dedup_threshold if dedup_threshold > 0 else None,
        )
    if rerank:
        # BLIP reranker cũng chỉ hiểu tiếng Anh -> đưa bản dịch, không phải query gốc.
        # Bản trùng đi theo đại diện qua đây (rerank_frames giữ nguyên các khoá
        # khác) - chúng không được chấm lại, chỉ là ảnh thay thế để người dùng xem.
        raw = rerank_frames(queries[0], raw)

    results = build_search_results(raw, top_k=top_k)
    return {"results": results, "caption_translation": caption_translation}
