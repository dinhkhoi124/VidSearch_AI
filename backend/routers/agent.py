"""Conversational agent endpoints (MemoriEase-style, Tran et al. LSC'24/'25).

POST /agent/chat  chat history -> ONE structured plan (Gemini) -> executes the
                  matching search (search_text pipeline or search_temporal) and
                  returns results + a conversational reply. The plan is included
                  in the response so the UI can show WHAT was searched - and the
                  user stays in the loop (the agent proposes, the human decides).
POST /agent/qa    RAG for question answering: retrieve candidate frames (or take
                  the user-picked ones), send them as images + scene OCR/ASR to
                  Gemini vision, return the answer with its evidence frames.
POST /agent/ask   MỘT ô nhập cho cả ba dạng đề: nhận dạng (hoặc nhận sẵn) kis /
                  qa / trake rồi gọi đúng đường ở trên. Xem agent_ask.
"""
from fastapi import APIRouter, HTTPException

from config import get_settings
from models.schemas import (
    AgentAskRequest,
    AgentAskResponse,
    AgentChatRequest,
    AgentChatResponse,
    AgentQaRequest,
    AgentQaResponse,
    LlmConfigRequest,
    LlmConfigResponse,
    LlmKeyRequest,
    LlmKeyResponse,
)
from services.agent_service import (
    answer_question,
    fuse_step_lists,
    is_available as agent_available,
    key_hint,
    plan_from_dialogue,
    qa_select_evidence,
    llm_config_snapshot,
    react_refine,
    run_step_lists,
    set_gemini_key,
    set_llm_config,
)
from services import llm_status
from services.task_classifier import TASK_TYPES, classify as classify_task
from services.dedup_service import group_duplicates
from services.ensemble_service import primary_model
from services.graph_service import aggregate_scene_scores
from services.metadata_service import build_search_results
from services.neighbor_service import aggregate_neighbor_scores
from routers.search_text import search_text
from routers.search_temporal import search_temporal

router = APIRouter()
settings = get_settings()


@router.get("/agent/llm_status")
def agent_llm_status():
    """Key LLM còn lượt không — nguồn cho banner cảnh báo trên giao diện.

    Mọi response đều mang sẵn header X-Llm-Quota (xem main.py), nên FE chỉ gọi
    endpoint này lúc mở trang / bấm kiểm tra lại: header chỉ nói được trạng
    thái kèm theo một request đang có.
    """
    status = llm_status.snapshot()
    status["configured"] = {
        "gemini": bool((settings.gemini_api_key or "").strip()),
        "openai": bool((settings.openai_api_key or "").strip()
                       and (settings.openai_base_url or "").strip()),
        "provider": (settings.llm_provider or "auto").strip().lower(),
        # Chỉ 4 ký tự cuối — đủ để biết key nào đang chạy sau khi cả nhóm dán
        # key lung tung, không đủ để ai đó nhặt key qua tunnel.
        "gemini_key_hint": key_hint(settings.gemini_api_key),
        "gemini_model": settings.gemini_model,
        "can_set_key": settings.allow_runtime_llm_key,
        # Khoá thêm cho ô "Provider & model" trong Cài đặt. Chỉ THÊM, không đổi
        # khoá cũ - banner quota của bản FE cũ vẫn đọc được response này.
        "openai_model": settings.openai_model,
        "openai_host": _openai_host_hint(),
    }
    return status


@router.post("/agent/llm_key", response_model=LlmKeyResponse)
def agent_set_llm_key(req: LlmKeyRequest):
    """Dán key Gemini mới trong lúc đang chạy (key cũ cạn quota giữa buổi thi).

    Key được thử bằng models.list TRƯỚC khi thay: dán nhầm key chết mà vẫn nhận
    thì tình huống còn tệ hơn lúc đầu. Chỉ sống trong RAM — restart backend là
    quay về .env.
    """
    if not settings.allow_runtime_llm_key:
        raise HTTPException(
            status_code=403,
            detail="Backend đang tắt đổi key runtime (ALLOW_RUNTIME_LLM_KEY=false).",
        )
    provider = (req.provider or "gemini").strip().lower()
    if provider != "gemini":
        raise HTTPException(status_code=400, detail=f"Chưa hỗ trợ provider '{provider}'.")

    try:
        applied = set_gemini_key(req.api_key, req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "provider": "gemini",
        "key_hint": applied["key_hint"],
        "model": applied["model"],
        "message": f"Đã đổi sang key {applied['key_hint']} (model {applied['model']}). "
                   "Key chỉ nằm trong RAM — restart backend là quay về .env.",
    }


def _openai_host_hint() -> str:
    """Host endpoint OpenAI-compat, để giao diện nói rõ đang gọi vào ĐÂU.
    Không trả cả base URL ở đây vì nó có thể mang token trong path (tunnel)."""
    return llm_config_snapshot()["openai"]["host"]


@router.get("/agent/llm_config")
def agent_llm_config():
    """Cấu hình LLM đang chạy (key đã che, chỉ 4 ký tự cuối) — nguồn cho ô
    "Provider & model" trong Cài đặt. Không gọi mạng, gọi bao nhiêu lần cũng rẻ."""
    return llm_config_snapshot()


@router.post("/agent/llm_config", response_model=LlmConfigResponse)
def agent_set_llm_config(req: LlmConfigRequest):
    """Đổi provider / model / endpoint OpenAI-compat mà KHÔNG restart backend.

    Restart tốn ~10 phút nạp lại model visual, trong khi thứ hỏng giữa buổi thi
    lại là phía LLM (hết credit, tunnel Colab đứt, model không nhận ảnh ở bước
    QA). Chỉ sống trong RAM — cùng đánh đổi như POST /agent/llm_key.
    """
    if not settings.allow_runtime_llm_key:
        raise HTTPException(
            status_code=403,
            detail="Backend đang tắt đổi cấu hình LLM runtime (ALLOW_RUNTIME_LLM_KEY=false).",
        )
    try:
        applied = set_llm_config(**req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "message": applied["message"], "config": applied["config"]}


async def _qa_auto_retrieve(req: AgentQaRequest) -> list:
    """Tự tìm frame bằng chứng cho câu hỏi - retrieval ĐA PHƯƠNG THỨC.

    Bằng chứng của một câu hỏi có thể nằm ở bất kỳ đâu: cảnh quay (visual),
    lời nói (ASR), chữ trên màn hình (OCR) hoặc caption sinh ra. Chạy riêng
    kênh visual (cách cũ) làm trượt những câu mà câu trả lời nằm trong lời nói
    / chữ trên màn hình - vd hỏi "2 câu thơ ca ngợi anh hùng Nguyễn Trung
    Trực" thì hai câu thơ được đọc trong ASR và hiện trong OCR, không nằm ở
    điểm ảnh. Mỗi kênh dùng query riêng hợp ngữ cảnh (visual = bản dịch tiếng
    Anh, text = chính câu hỏi chứa keyword); chọn frame bằng chứng bằng
    qa_select_evidence - fusion theo VIDEO + đa dạng hoá video/kênh, KHÔNG dùng
    neighbor/scene aggregation (chúng khuếch đại video sai đông frame trong
    pool và đè mất video đúng chỉ trúng một kênh).
    """
    from services.caption_service import captions_available

    plan = plan_from_dialogue([{"role": "user", "content": req.question}])
    steps = [
        {"channel": "visual", "query": plan["query"], "objects": plan["objects"],
         "scene_keywords": plan["scene_keywords"]},
        {"channel": "asr", "query": req.question, "objects": "", "scene_keywords": ""},
        {"channel": "ocr", "query": req.question, "objects": "", "scene_keywords": ""},
    ]
    if captions_available():
        steps.append({"channel": "caption", "query": req.question,
                      "objects": "", "scene_keywords": ""})
    if str(plan["scene_keywords"]).strip():
        # chi tiết đặc trưng planner trích được (tên riêng, "200g thịt nạc xay"...)
        # -> kênh khớp token với OCR+ASR scene, độc lập thứ tự từ và lỗi OCR
        steps.append({"channel": "scene_text", "query": str(plan["scene_keywords"]),
                      "objects": "", "scene_keywords": ""})

    lists = await run_step_lists(
        steps, top_k=max(settings.agent_max_qa_frames * 3, 60), model=req.model,
    )
    raw = qa_select_evidence(steps, lists, req.question)
    frames = build_search_results(raw, top_k=settings.agent_max_qa_frames)
    if frames:
        return frames

    # plan-and-execute rỗng (mọi kênh text vô hiệu) -> visual search thuần
    res = await search_text(
        query=req.question, top_k=settings.agent_max_qa_frames,
        model=req.model, rerank=False, expand=True,
    )
    return res["results"]


@router.post("/agent/chat", response_model=AgentChatResponse)
async def agent_chat(req: AgentChatRequest):
    messages = [m.model_dump() for m in req.messages]
    if not any(m.get("role") == "user" and m.get("content", "").strip() for m in messages):
        raise HTTPException(status_code=400, detail="Need at least one user message")

    plan = plan_from_dialogue(messages, task_hint=req.task_type.strip().lower())
    # Câu gốc tiếng Việt của người dùng - ReAct cần để nhận dạng yêu cầu kiểu
    # bài giảng (plan["query"] đã dịch sang tiếng Anh, mất "bài giảng"/"giảng giải").
    plan["user_query"] = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

    if plan["mode"] == "temporal":
        events = (plan["events"] + ["", "", "", ""])[:4]
        temporal = await search_temporal(
            q1=events[0], q2=events[1], q3=events[2], q4=events[3],
            model=req.model, topk_per_event=req.top_k,
        )
        return {"reply": plan["reply"], "plan": plan,
                "results": [], "videos": temporal["videos"], "trace": []}

    steps = plan.get("steps") or []
    # Chi tiết đặc trưng planner trích được (tên riêng, cụm chữ trên màn hình /
    # lời nói) -> luôn thêm kênh scene_text khớp token vào fan-out. Boost
    # scene_keywords trong search_text chỉ chấm lại ứng viên VISUAL - video mà
    # visual trượt hẳn (bảng chữ, tên phim) không thể được cứu; kênh độc lập
    # này đưa thẳng các scene khớp chữ vào fusion (đúng bài học từ /agent/qa).
    if str(plan["scene_keywords"]).strip():
        if not steps:
            steps = [{"channel": "visual", "query": plan["query"],
                      "objects": plan["objects"],
                      "scene_keywords": plan["scene_keywords"]}]
        if not any(s["channel"] == "scene_text" for s in steps):
            steps = steps + [{"channel": "scene_text",
                              "query": str(plan["scene_keywords"]),
                              "objects": "", "scene_keywords": ""}]
        plan["steps"] = steps
    # Kênh caption rẻ (E5 encode + index nhỏ) - có dữ liệu caption thì LUÔN góp
    # vào fan-out, không phụ thuộc planner (flash-lite hay bỏ sót kênh này).
    # Không giới hạn số step: plan 1 step (KIS đơn giản - rất nhiều) và plan
    # 4 step trước đây bị loại khỏi caption, đúng nhóm query cần nó nhất
    # (chi tiết hiếm mà visual embedding nén mất). Plan 1 step được nâng thành
    # fan-out 2 kênh - mất nhánh search_text đơn nhưng được fusion + caption.
    from services.caption_service import captions_available
    if captions_available() and not any(s["channel"] == "caption" for s in steps):
        if not steps:
            steps = [{"channel": "visual", "query": plan["query"],
                      "objects": plan["objects"],
                      "scene_keywords": plan["scene_keywords"]}]
        steps = steps + [{"channel": "caption", "query": plan["query"],
                          "objects": "", "scene_keywords": ""}]
        plan["steps"] = steps  # để UI chips hiển thị đủ các kênh đã chạy
    if len(steps) >= 2:
        # Plan-and-Execute: các kênh chạy song song, fuse điểm max-norm.
        # Fan-out tự nó đã là chiến lược "sâu" -> chỉ leo thang ReAct khi
        # fusion rỗng hoặc người dùng ép deep=true (điểm fused khác thang
        # cosine nên không so với react_score_threshold được).
        lists = await run_step_lists(steps, top_k=req.top_k, model=req.model)
        raw = fuse_step_lists(
            steps, lists, {"scene_text": settings.chat_scene_text_weight})
        # Các kênh trúng frame KHÁC NHAU của cùng cảnh -> gộp bằng chứng theo
        # cụm thời gian (neighbor) + ranh giới cảnh (scene) để cộng hưởng điểm.
        raw = raw[: max(req.top_k * 4, 200)]
        raw = aggregate_neighbor_scores(raw)
        raw = aggregate_scene_scores(raw)
        # Gộp trùng TRƯỚC rerank — xem ghi chú thứ tự ở routers/search_text.
        raw = group_duplicates(raw, model=primary_model(req.model))
        if req.rerank:
            # BLIP ITM chấm lại head (rerank_candidates) bằng cross-attention
            # thật trên cặp (query tiếng Anh của plan, ảnh) - trước đây fan-out
            # đặt rerank=False ở MỌI kênh và không có lượt chấm cuối, nên frame
            # trúng-bề-mặt (đúng chủ đề, sai nội dung) không bị lọc. Model
            # thiếu/OOM thì rerank_frames tự giữ nguyên thứ tự - không thể vỡ.
            import asyncio
            from services.rerank_service import rerank_frames
            raw = await asyncio.to_thread(rerank_frames, plan["query"], raw)
        results = build_search_results(raw, top_k=req.top_k)
        # Bảo hiểm đại diện kênh: video mà MỘT kênh tin nhất (vd scene_text
        # khớp nguyên bảng chữ) nhưng chỉ trúng kênh đó sẽ bị fusion cộng dồn
        # + aggregation của các video đa kênh đè mất (đo được ở /agent/qa cũ:
        # ground truth rơi #5 -> #29). Frame mạnh nhất của từng kênh luôn phải
        # có mặt trong top-k - thế chỗ đuôi danh sách, không phá phần đầu.
        present = {r["video_name"] for r in results}
        champions: list = []
        for step, lst in zip(steps, lists):
            if not lst:
                continue
            best = max(lst, key=lambda x: float(x["score"]))
            meta_vid = best["id"].rsplit("_", 1)[0]
            if meta_vid not in present:
                champions.append({"id": best["id"], "score": float(best["score"])})
                present.add(meta_vid)
        if champions:
            champ_res = build_search_results(champions, top_k=len(champions))
            keep = max(req.top_k - len(champ_res), 0)
            results = results[:keep] + champ_res
        if (req.deep or not results) and settings.react_max_steps > 0 and agent_available():
            refined = await react_refine(plan, results, top_k=req.top_k, model=req.model)
            plan, results = refined["plan"], refined["results"]
            plan["react_steps"] = len(refined["trace"])
            return {"reply": refined["reply"], "plan": plan,
                    "results": results, "videos": [], "trace": refined["trace"]}
        return {"reply": plan["reply"], "plan": plan,
                "results": results, "videos": [], "trace": []}

    # plan query đã là tiếng Anh -> expand=False, khỏi tốn thêm 1 call Gemini
    res = await search_text(
        query=plan["query"],
        top_k=req.top_k,
        model=req.model,
        rerank=req.rerank,
        expand=False,
        objects=plan["objects"],
        object_mode="boost",
        scene_keywords=plan["scene_keywords"],
        scene_mode="boost",
    )
    results, trace = res["results"], []

    # Tự leo thang sang ReAct khi one-shot yếu (rỗng / top score dưới ngưỡng)
    # hoặc khi người dùng ép deep=true. Xem agent_service.react_refine.
    weak = not results or results[0]["score"] < settings.react_score_threshold
    if (req.deep or weak) and settings.react_max_steps > 0 and agent_available():
        refined = await react_refine(plan, results, top_k=req.top_k, model=req.model)
        plan, results, trace = refined["plan"], refined["results"], refined["trace"]
        plan["react_steps"] = len(trace)
        return {"reply": refined["reply"], "plan": plan,
                "results": results, "videos": [], "trace": trace}

    return {"reply": plan["reply"], "plan": plan,
            "results": results, "videos": [], "trace": trace}


@router.post("/agent/qa", response_model=AgentQaResponse)
async def agent_qa(req: AgentQaRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if req.frame_ids:
        # người dùng đã khoanh vùng frame -> dùng đúng các frame đó làm bằng chứng
        raw = [{"id": fid, "score": 1.0} for fid in req.frame_ids]
        frames = build_search_results(raw, top_k=settings.agent_max_qa_frames)
    else:
        frames = await _qa_auto_retrieve(req)

    if not frames:
        raise HTTPException(status_code=404, detail="No candidate frame found")

    out = answer_question(req.question, frames)
    if settings.qa_zoom_pass:
        import asyncio

        from services.agent_service import zoom_reread
        zoomed = await asyncio.to_thread(
            zoom_reread, req.question, frames, out["evidence_index"], out["answer"])
        if zoomed:
            out = zoomed
    ev = out["evidence_index"]
    if 0 <= ev < len(frames):  # frame bằng chứng lên đầu để UI highlight
        frames = [frames[ev]] + frames[:ev] + frames[ev + 1:]
    return {"answer": out["answer"], "frames": frames}


@router.post("/agent/ask", response_model=AgentAskResponse)
async def agent_ask(req: AgentAskRequest):
    """Một ô nhập -> ba đường xử lý. Người thi dán nguyên đề, khỏi chọn tab.

    Chỉ GỘP LỐI VÀO, không gộp pipeline: ba dạng đề khác nhau ở bản chất
    retrieval (KIS fuse theo frame + gom neighbor/scene; TRAKE fuse theo từng
    event rồi ghép chuỗi trong một video; QA fuse theo VIDEO, luôn bật kênh
    asr/ocr và KHÔNG gom neighbor - xem _qa_auto_retrieve và
    agent_service.qa_select_evidence). Ép chung một pipeline làm hỏng cả hai
    đầu: đo trên bộ SOTUYEN2, ép thêm kênh asr/ocr cho KIS kéo top-5 từ 22/30
    xuống 13/30, còn gom neighbor cho QA đè mất video đúng.

    Thứ tự tin cậy khi chọn dạng:
      1. task_type người dùng gửi lên - lấy từ gói đề BTC phát, luôn đúng;
      2. task_classifier đọc chính câu đề (không tốn LLM, không tốn thời gian).
    """
    messages = [m.model_dump() for m in req.messages]
    question = next(
        (m["content"] for m in reversed(messages)
         if m.get("role") == "user" and m.get("content", "").strip()), "")
    if not question:
        raise HTTPException(status_code=400, detail="Need at least one user message")

    task_type = req.task_type.strip().lower()
    guess = classify_task(question)
    if task_type in TASK_TYPES:
        source, reason = "explicit", "dạng lấy từ bộ đề"
        # num_events vẫn lấy từ bộ nhận dạng: đề TRAKE đánh số sẵn E1..E4 thì
        # đếm được ngay, UI khỏi bắt người dùng khai tay số dòng phải nộp.
        num_events = guess["num_events"] if task_type == "trake" else 0
    else:
        task_type, source = guess["task_type"], "auto"
        reason, num_events = guess["reason"], guess["num_events"]
    print(f"[agent] ask: task={task_type} ({source}: {reason})")

    if task_type == "qa":
        out = await agent_qa(AgentQaRequest(
            question=question, frame_ids=req.frame_ids, model=req.model))
        return {"task_type": task_type, "task_source": source, "task_reason": reason,
                "num_events": num_events, "reply": out["answer"], "answer": out["answer"],
                "plan": {}, "results": out["frames"], "videos": [], "trace": []}

    out = await agent_chat(AgentChatRequest(
        messages=req.messages, top_k=req.top_k, model=req.model,
        rerank=req.rerank, deep=req.deep, task_type=task_type))
    # Planner là bên chốt cuối: đề TRAKE mà nó chỉ tách được 1 event thì kết
    # quả trả về là lưới frame chứ không phải chuỗi - nói đúng cho UI vẽ.
    if task_type == "trake":
        if out["videos"]:
            num_events = len(out["plan"].get("events") or []) or num_events
        else:
            task_type, reason = "kis", f"{reason}, nhưng planner chỉ tách được 1 cảnh"
    return {"task_type": task_type, "task_source": source, "task_reason": reason,
            "num_events": num_events, "reply": out["reply"], "answer": "",
            "plan": out["plan"], "results": out["results"], "videos": out["videos"],
            "trace": out["trace"]}
