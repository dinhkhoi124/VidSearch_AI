"""Application settings loaded from environment variables / .env file."""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    # Chỉ áp dụng khi chạy `python main.py`. Bật reload = uvicorn nạp lại toàn
    # bộ model mỗi lần file đổi (~2 phút + một lượt VRAM nữa), nên mặc định tắt.
    reload: bool = False

    # URL gốc mà FE serve static media từ (vd http://localhost:5173 ở dev,
    # https://fe.example.com ở prod). BE không còn mount /media hay đọc
    # file ảnh từ disk; ảnh keyframe/video đều do FE phục vụ.
    media_base_url: str = "http://localhost:5173"

    # Thư mục chứa kho keyframe NGAY TRÊN MÁY CHẠY BACKEND. Trống = BE kéo ảnh
    # qua HTTP từ MEDIA_BASE_URL như cũ.
    #
    # Chỉ đổi đường BE lấy pixel (rerank visual + /agent/qa). URL trả cho trình
    # duyệt vẫn dựng từ MEDIA_BASE_URL, vì trình duyệt không đọc được đĩa của BE.
    #
    # Dùng khi BE ở Colab: đặt kho ảnh lên đĩa Colab rồi trỏ vào đây, thay vì bắt
    # từng pixel chui qua tunnel về máy nhà. Đo thực tế trên tunnel ngrok free:
    # 100 ảnh/lượt rerank làm cạn hạn mức kết nối, lượt sau rụng 30-70%.
    #
    # Trỏ vào thư mục CHỨA `media/`, không phải chính `media/`:
    #   <media_dir>/media/frames/Keyframes/<batch>/<video_name>/<idx>.webp
    # Ở máy dev, đó chính là frontend/public.
    media_dir: str = ""

    cors_origins: str = "http://localhost:5173,http://localhost:4173,http://localhost:3000"

    data_dir: str = "./data"

    default_model: str = "metaclip2"

    # --- Ensemble search --------------------------------------------------------
    # model=ensemble: search song song nhiều index rồi trộn điểm đã chuẩn hoá theo
    # max từng model (Tran et al., arXiv:2504.08384, Alg. 3):
    #   S(frame) = Σ w_m * s_m(frame) / max(s_m)
    # Model thiếu encoder thật hoặc thiếu index sẽ tự bị bỏ qua.
    # SigLIP là backbone chính; CLIP góp góc nhìn thứ hai (train data khác).
    # Đã loại jina 07/2026: yếu rõ rệt trên dữ liệu AIC, nhất là query tiếng Việt.
    # Key khả dụng thêm khi đã build index (04b/05b): siglip512 (res 512, vật
    # thể nhỏ), metaclip (thay clip 2021), metaclip2 (MetaCLIP 2 worldwide, train
    # 300+ ngôn ngữ nên nuốt được cả query tiếng Việt chưa dịch - hướng đa ngữ
    # thay cho jina). Ví dụ: "siglip:0.4,siglip512:0.35,metaclip2:0.25" - model
    # thiếu index tự bị bỏ qua nên đổi trước cũng không vỡ.
    ensemble_models: str = "siglip512:0.5,metaclip2:0.5"

    # --- Gemini query expansion (dịch + mở rộng query) -------------------------
    # Mọi backbone visual (SigLIP/CLIP/BLIP) đều thiên tiếng Anh, nên query được
    # LLM dịch + sinh biến thể tiếng Anh trước khi search (Ngo et al.,
    # arXiv:2512.12935, Fig. 3): biến thể đầu luôn là bản dịch trực tiếp.
    # Lấy key miễn phí tại https://aistudio.google.com. Rỗng = tắt (dùng query gốc).
    gemini_api_key: str = ""
    # 2.5-flash-lite: nhanh + free tier; các model 2.0 đã bị Google cắt quota free.
    gemini_model: str = "gemini-3.5-flash-lite"
    # --- LLM OpenAI-compatible (OrcaRouter/OpenRouter/Groq/Ollama...) ---------
    # Lối thoát khi Gemini cạn quota / bị chặn. Bất kỳ endpoint nào nói chuẩn
    # /chat/completions đều dùng được. Rỗng = tắt.
    #   llm_provider: auto         = Gemini trước, lỗi/thiếu key thì rơi sang OpenAI
    #                 openai_first = NGƯỢC LẠI: OpenAI-compat trước, Gemini đỡ
    #                 gemini       = chỉ Gemini (kể cả khi openai_* có cấu hình)
    #                 openai       = chỉ OpenAI-compat, KHÔNG có đường lui
    # openai_first là chế độ dành cho endpoint tự dựng (Ollama trên Colab): không
    # quota nên cho chạy chính, nhưng vẫn còn Gemini đỡ khi máy hụt GPU to hoặc
    # Ollama chưa kịp nạp model. Đừng dùng "openai" cho trường hợp đó - mất lưới.
    # LƯU Ý: bước QA gửi ẢNH - model text-thuần (vd qwen3.8-27b) sẽ lỗi ở bước
    # đó; đặt openai_qa_model thành model vision, hoặc để Gemini lo QA.
    llm_provider: str = "auto"
    # Cho phép đổi cấu hình LLM từ giao diện khi hỏng giữa buổi thi - key Gemini
    # mới (POST /agent/llm_key), provider và model/endpoint OpenAI-compat
    # (POST /agent/llm_config). Tất cả chỉ nằm trong RAM, restart là quay về
    # .env. Endpoint không bao giờ TRẢ key (chỉ 4 ký tự cuối), nhưng ai vào được
    # backend cũng ghi đè được; đặt false nếu tunnel để công khai.
    allow_runtime_llm_key: bool = True
    openai_base_url: str = ""       # vd https://api.orcarouter.ai/v1
    openai_api_key: str = ""
    openai_model: str = ""          # vd qwen/qwen3.8-27b-free
    # Model riêng theo nhiệm vụ, song song với gemini_react_model/gemini_qa_model.
    # Rỗng = dùng openai_model. Cần khi endpoint phục vụ nhiều model cùng lúc:
    # QA đòi vision, ReAct đòi suy luận tốt, expansion/plan thì model nhỏ là đủ.
    openai_react_model: str = ""
    # Trần token output gửi kèm mọi call OpenAI-compat (0 = không gửi). Không
    # gửi thì endpoint tự chọn trần mặc định - có router đặt rất thấp, reply
    # ReAct tiếng Việt bị cắt giữa JSON và vòng lặp dừng ngay bước 1.
    openai_max_tokens: int = 2000
    openai_qa_model: str = ""       # PHẢI là model vision nếu muốn QA chạy

    # Header nhận diện app; chỉ OpenRouter dùng, endpoint khác bỏ qua. Rỗng = không gửi.
    openai_referer: str = ""
    openai_title: str = ""
    # response_format={"type":"json_object"}: auto = gửi kèm, endpoint nào trả 400
    # vì không hiểu thì tự gỡ và nhớ luôn cho model đó (_NO_JSON_MODE). Đặt "off"
    # khi biết chắc endpoint không hỗ trợ, để khỏi tốn một lượt gọi hỏng đầu tiên.
    openai_json_mode: str = "auto"
    # Ngân sách thinking gửi ở field `reasoning` (low/medium/high). Rỗng = KHÔNG
    # gửi field đó. Tách theo nhiệm vụ vì expand/plan là bài dễ, react/qa mới cần
    # suy luận; bật hết thì mỗi truy vấn đắt gấp nhiều lần mà không khá hơn.
    openai_reasoning_expand: str = ""
    openai_reasoning_plan: str = ""
    openai_reasoning_react: str = ""
    openai_reasoning_qa: str = ""

    # --- Giới hạn chung cho MỌI call LLM (dùng chung Gemini + OpenAI-compat) ---
    # Timeout rộng tay vì QA gửi ảnh và endpoint tự dựng (Ollama) có thể phải nạp
    # model trước khi trả chữ đầu tiên.
    llm_timeout_s: int = 120
    # Retry chỉ áp cho lỗi tạm (408/429/5xx); hết quota NGÀY thì bỏ retry ngay.
    llm_max_retries: int = 3
    # Backoff tuyến tính: lần thứ n chờ backoff * n giây.
    llm_retry_backoff_s: float = 2.0

    # Điểm mỗi biến thể được chuẩn hoá theo max của chính nó rồi nhân trọng số:
    # bản dịch trực tiếp (biến thể 0) giữ 1.0, các paraphrase bị chiết khấu để
    # không lấn át bản dịch khi diễn đạt lệch chủ thể.
    expansion_variant_weight: float = 0.85

    # --- HuggingFace Hub (đăng nhập + tăng tốc tải weight) ---------------------
    # Token KHÔNG làm băng thông nhanh hơn; nó cho quyền tải repo gated và hạn
    # mức request cao hơn (đáng kể trên Colab: IP dùng chung, request ẩn danh bị
    # siết trước và hay đứt giữa chừng). Lấy token ở
    # https://huggingface.co/settings/tokens (quyền read là đủ).
    hf_token: str = ""
    # Thư mục cache weight. Trên Colab trỏ vào Drive để KHÔNG phải tải lại mỗi
    # session - đây mới là thứ tiết kiệm nhiều nhất, vd
    #   HF_HOME=/content/drive/MyDrive/hf_cache
    hf_home: str = ""
    # hf_transfer: downloader Rust đa luồng cho repo chưa lên Xet. Đổi lại mất
    # thanh tiến trình và retry mềm -> đặt false nếu mạng chập chờn.
    hf_enable_transfer: bool = True
    hf_download_timeout: int = 60   # giây/chunk; 0 = giữ mặc định của hub

    # --- Warm-up lúc khởi động ------------------------------------------------
    # Mặc định mọi service nạp lazy -> câu search ĐẦU TIÊN phải chờ tải weight
    # (SigLIP/MetaCLIP/E5/reranker, hàng GB) rồi mới trả kết quả, và mỗi kênh
    # trả giá đó riêng ở lần đầu của nó. Bật warm-up để nạp hết ngay khi bật
    # server: đúng các model trong DEFAULT_MODEL + ENSEMBLE_MODELS, index FAISS
    # tương ứng, text encoder, reranker, metadata/OCR/ASR/caption/graph.
    warmup_on_startup: bool = True
    # background=True: server nhận request NGAY, warm-up chạy ở thread nền -
    # hợp khi chạy sau ngrok/Colab (tunnel lên sớm, không bị coi là chết).
    # background=False: chặn tới khi nạp xong, request đầu chắc chắn nhanh.
    warmup_background: bool = True
    # Reranker nặng nhất (bge-reranker-v2-m3 + BLIP ITM). Tắt khi VRAM eo hẹp -
    # chúng vẫn nạp lazy khi có request dùng rerank.
    warmup_rerankers: bool = True
    # Chạy song song hai luồng: đọc index/JSON từ đĩa và nạp weight lên GPU.
    # Hai việc này nghẽn ở hai chỗ khác nhau nên chồng lên nhau được. Đặt false
    # để về tuần tự (dễ đọc log hơn khi soi lỗi một bước cụ thể).
    warmup_parallel: bool = True

    # Embedding device & precision (đọc từ .env hoặc biến môi trường)
    #   embed_device: auto | cuda | cpu
    #   embed_dtype : auto | fp16 | fp32   (auto = fp16 trên cuda, fp32 trên cpu)
    embed_device: str = "auto"
    embed_dtype: str = "auto"

    # --- Semantic OCR/ASR text search (hybrid) -------------------------------
    # Sentence-embedding backbone cho tìm kiếm OCR/ASR theo ngữ nghĩa. Phải KHỚP
    # với model dùng khi build index (data_processing step 07). E5 yêu cầu prefix
    # "query: " / "passage: " - text_embedding_service tự thêm.
    text_embed_model: str = "intfloat/multilingual-e5-base"  # 768-d, đa ngữ (vi)
    # Hybrid scoring: điểm = sem_weight * cosine_ngữ_nghĩa + exact_bonus * (khớp_chuỗi?1:0)
    # Điểm ngữ nghĩa được GIÃN về [0,1] trước khi cộng (xem ocr_service.
    # rescale_semantic): cosine E5 có sàn ~0.80 gần như không đổi kể cả với query
    # vô nghĩa, cộng thẳng thì hằng số đó át hết. Thưởng khớp nguyên văn còn nhân
    # thêm ĐỘ HIẾM của cụm, nên bonus > 1 không làm cụm phổ thông ("NGUYÊN LIỆU",
    # khớp 1767 frame) lấn át. Quét 0.5/0.8/1.0 × 1.0/1.5/2.0 trên 5 cụm tên
    # riêng: 1.5 là mức nhỏ nhất đạt 5/5 câu vào top-5.
    ocr_sem_weight: float = 1.0
    ocr_exact_bonus: float = 1.5
    asr_sem_weight: float = 1.0
    asr_exact_bonus: float = 1.5
    # Caption (Qwen2.5-VL, kaggle step 9): exact bonus nhỏ hơn OCR/ASR vì caption
    # là văn bản SINH RA - khớp nguyên văn không có ý nghĩa bằng chứng như OCR
    caption_sem_weight: float = 1.0
    caption_exact_bonus: float = 0.25

    # --- Re-ranking (giai đoạn 2 sau retrieve) --------------------------------
    # Cross-encoder chấm lại cặp (query, văn bản OCR/ASR). Đặt "none" để tắt.
    # Máy ít VRAM có thể đổi sang Alibaba-NLP/gte-multilingual-reranker-base.
    text_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    # ITM chấm lại cặp (query, ảnh keyframe) cho /search_text. "none" để tắt.
    # blip2-itm-vit-g: ViT-g (~1B) + Q-Former, thay blip-itm-base-coco (ViT-B
    # ~86M, fine-tune COCO) vốn YẾU HƠN chính retriever nó đang chấm lại. Đánh
    # đổi: BLIP-2 chạy ảnh 224² còn BLIP base 384², nên vật thể/chữ nhỏ có thể
    # kém đi - đo trước khi tin. Nhận cả tên blip lẫn blip2, xem _visual_kind.
    visual_rerank_model: str = "Salesforce/blip-itm-large-coco"
    # Chỉ dùng cho họ crossencoder (Qwen3-VL-Reranker, nemotron-rerank-vl...):
    # các model này NHẬN INSTRUCTION, đổi câu này là đổi cách chúng hiểu nhiệm
    # vụ. blip/blip2 bỏ qua. Mặc định lấy đúng câu trong model card của Qwen.
    visual_rerank_prompt: str = "Retrieve images or text relevant to the user's query."
    # Trần token thị giác MỖI ẢNH cho họ crossencoder nền Qwen-VL. 0 = để mặc
    # định của model. Đây là knob tốc độ chính, không phải batch: keyframe
    # 1280x720 để mặc định tốn ~1176 token/ảnh -> 100 ảnh mất 37s trên RTX 3060.
    # Đo được: 200704 -> 8.6s, 100352 -> 5.7s, 50176 -> 4.0s (batch 16).
    # Đơn vị tính theo patch 28x28, nên 100352 = 128*28*28 = 128 token.
    visual_rerank_max_pixels: int = 0
    # Chỉ chấm lại tối đa N ứng viên đầu bảng; điểm trộn theo
    #   final = alpha * rerank + (1 - alpha) * retrieve   (sau min-max norm)
    rerank_candidates: int = 100
    text_rerank_alpha: float = 0.7
    visual_rerank_alpha: float = 0.3

    # --- Neighbor score aggregation (rerank không cần model) ------------------
    # Frame có hàng xóm cùng video điểm cao đáng tin hơn frame trúng lẻ loi
    # (Tran et al., arXiv:2504.08384). Điểm cộng suy giảm tuyến tính theo Δt:
    #   final = score + weight * Σ score_hàng_xóm * (1 − |Δt|/window)
    # Đặt weight = 0 để tắt.
    neighbor_weight: float = 0.5
    neighbor_window_ms: int = 10000

    # --- Gộp frame trùng thị giác ở tầng KẾT QUẢ (services/dedup_service) -----
    # Khác DEDUP_THRESHOLD của data_processing bước 03: bước đó chỉ so trong
    # cùng một video, nên nhiều bản của cùng phóng sự nằm ở video khác nhau vẫn
    # lấp kín top-K. Ở đây so mọi ứng viên với nhau bằng vector trong index.
    # Ngưỡng cosine: 0.975 bắt bản phát lại/re-encode mà chưa nuốt hai cảnh khác
    # nhau cùng bố cục (cùng trường quay, cùng phông). Hạ thấp = gộp mạnh tay
    # hơn nhưng dễ giấu mất frame đúng. 0 = tắt.
    # Tên KHÔNG được là dedup_threshold: data_processing đọc thẳng biến môi
    # trường DEDUP_THRESHOLD cho dedup lúc build index (0.9). Trùng tên thì một
    # dòng .env dùng chung sẽ lặng lẽ đổi ngưỡng của cả hai tầng cùng lúc.
    result_dedup_threshold: float = 0.975
    # Trần số ứng viên đem gộp - chi phí là ma trận n^2. Phần đuôi vượt trần ra
    # thẳng lưới, không gộp.
    result_dedup_max_candidates: int = 1200

    # --- Graph layer (data/graph, build bằng data_processing step 08) ---------
    # Thiếu file graph thì mọi hàm graph tự no-op - các trọng số dưới vô hiệu.
    # Scene bonus: như neighbor_weight nhưng gom theo ranh giới CẢNH (SceneJSON)
    # thay vì cửa sổ thời gian cố định: final = s + w * mean(điểm scene-mate).
    graph_scene_weight: float = 0.3
    # Boost khi scene của ứng viên chứa các object được yêu cầu (mode=boost):
    # final = s + bonus * (số label khớp / số label yêu cầu)
    graph_object_bonus: float = 0.3
    # Boost khi TEXT của cảnh (OCR các frame + ASR trùng khoảng thời gian) chứa
    # keyword yêu cầu - mịn hơn ocr_keywords (per-frame) / asr_keywords (per-video)
    graph_scene_text_bonus: float = 0.3
    # kNN expansion: hàng xóm similarity của top ứng viên vào pool với điểm
    # w * cosine * điểm_nguồn. Cần data/graph/knn_<model>.json (step 08 --knn).
    graph_knn_weight: float = 0
    graph_knn_expand_top: int = 20

    # --- Agent (MemoriEase-style, dùng chung gemini_api_key/gemini_model) -----
    # /search_feedback: v = w*encode(query) + (1-w)*mean(frame đã chọn)
    # (MemoriEase 3.0 §3.5: phải giữ query gốc, chỉ pooling ảnh sẽ trôi ý định)
    feedback_query_weight: float = 0.5
    # /agent/qa: số keyframe tối đa gửi cho Gemini vision mỗi câu hỏi
    # 15: 12 frame chọn theo điểm + qa_timeline_frames rải theo dòng thời gian,
    # nếu không frame rải thêm bị chính build_search_results cắt mất.
    agent_max_qa_frames: int = 15
    # /agent/qa pha 2: đọc lại frame bằng chứng ở 2x + 4 góc. TẮT: đo trên 13 câu
    # QA thì 10 lượt zoom không đổi được câu trả lời nào (keyframe vốn đã là
    # 1280x720, không phải 640x360 như giả thiết ban đầu), mà tốn thêm một call
    # vision mỗi câu. Xem _zoom_image_parts.
    qa_zoom_pass: bool = False
    # /agent/qa: thêm N frame rải đều theo dòng thời gian của video mạnh nhất,
    # ngoài các frame chọn theo điểm. 0 = tắt.
    qa_timeline_frames: int = 3
    # /agent/qa auto-retrieve: trọng số của tín hiệu "scene text" khi xếp hạng
    # frame bằng chứng. Nhiều câu trả lời nằm trong lời nói / chữ trên màn hình
    # của CẢNH (vd 2 câu thơ được đọc lên) chứ không nằm ở điểm ảnh - frame có
    # cảnh OCR/ASR liên quan câu hỏi phải được ưu tiên, không bị frame trúng
    # nhiều kênh visual trấn áp. 0 = tắt.
    qa_scene_text_weight: float = 0.4
    # /agent/qa: chọn bằng chứng theo VIDEO thay vì theo frame. Các kênh thường
    # trúng frame KHÁC NHAU của cùng video đúng (visual trúng cảnh, OCR trúng
    # khung chữ) nên fusion per-frame bỏ sót tín hiệu đa kênh; điểm video = tổng
    # best-frame mỗi kênh gom lại được. Lấy tối đa qa_max_videos video, mỗi video
    # qa_frames_per_video frame (ưu tiên frame tốt nhất của TỪNG kênh) - top-N
    # gửi Gemini luôn phủ nhiều video, không bị một video sai chiếm hết chỗ.
    qa_max_videos: int = 6
    qa_frames_per_video: int = 2
    # /agent/chat: trọng số kênh scene_text trong fusion. Keyword planner sinh
    # đôi khi CHUNG CHUNG ("tàu vũ trụ") -> kênh chấm 1.0 cho hàng chục video
    # cùng chủ đề, flood fusion và đè kênh visual vốn đang đúng. Giảm còn một
    # nửa: bằng chứng chữ vẫn góp điểm, video khớp chữ mạnh nhất vẫn LUÔN có
    # mặt nhờ champion injection (xem agent_chat), nhưng không nhấn chìm ai.
    chat_scene_text_weight: float = 0.5

    # /search_text?text_mode=fuse: trọng số pool visual khi trộn với các kênh
    # chữ (OCR/ASR/caption) người dùng gõ vào ô lọc. 1.0 = ba kênh ngang nhau.
    # Hạ xuống nếu muốn ô lọc chi phối mạnh hơn mô tả cảnh, nâng lên nếu thấy
    # kênh chữ kéo kết quả đi lạc.
    search_fuse_visual_weight: float = 1.0

    # --- ReAct (vòng lặp Thought→Action→Observation cho /agent/chat) ----------
    # Tự leo thang từ one-shot plan sang ReAct khi kết quả kém (top score dưới
    # ngưỡng hoặc rỗng), hoặc khi request đặt deep=true. 0 = tắt hẳn ReAct.
    # 6: protocol bài giảng cần search_transcript -> locate_by_asr (x2) -> final;
    # 3 bước thì vòng lặp hết hạn ngay sau khi vừa định vị xong.
    react_max_steps: int = 6
    # Fusion fan-out: thưởng thêm cho ĐỈNH NHỌN của kênh chữ (ocr/asr/scene_text)
    # - top1 >= 2x top2, tức khớp nguyên văn một cụm hiếm. TẮT (0.0): đo 3 lượt
    # x 55 câu thì nó đổi đuôi lấy đầu (vid@100 48.0 -> 49.0 nhưng vid@1
    # 19.3 -> 17.7, vid@5 32.7 -> 30.0), còn ở đường ReAct thì hỏng hẳn
    # (vid@20 44.5 -> 39.5) vì điểm bị bơm làm sai phép so best_score.
    fusion_peak_bonus: float = 0.0
    # Luật "hình vẽ trên slide bài giảng là ẩn dụ của khái niệm" trong prompt
    # planner. TẮT: cứu p2-26 (rank 18 -> 3) và p2-10 nhưng trên tổng 55 câu
    # không lãi cột nào (vid@5 32.7 -> 30.7, vid@20 42.7 -> 40.0) và nhiễu tăng
    # 13 -> 16 câu. Bật lại nếu bộ đề thiên về bài giảng.
    plan_slide_rule: bool = False
    react_score_threshold: float = 0.3
    # Model riêng cho vòng ReAct - flash-lite hay "quẩn" khi phải tự sửa hướng;
    # bản flash thường suy luận tốt hơn. Rỗng = dùng gemini_model.
    # LƯU Ý quota: free tier gemini-2.5-flash chỉ ~20 request/ngày - dễ cạn.
    # gemini-3.5-flash dùng bucket quota riêng và suy luận tốt hơn.
    gemini_react_model: str = "gemini-3.5-flash"
    # Model cho bước TRẢ LỜI QA (vision trên ~12 frame, 1 call/câu hỏi):
    # flash-lite hay chọn frame khớp một phần mà bỏ ràng buộc trong câu hỏi
    # (ai xuất hiện, đang cầm gì) - bản flash phân xử tốt hơn. Rỗng = gemini_model.
    gemini_qa_model: str = "gemini-3.5-flash"

    # --- Temporal search: beam search + suy giảm mũ ---------------------------
    # Điểm chuỗi sự kiện = Σ sᵢ·e^(−α·Δtᵢ) với Δt tính bằng giây
    # (Ngo et al., arXiv:2512.12935). α càng lớn phạt khoảng cách càng mạnh.
    temporal_decay_alpha: float = 0.01
    temporal_beam_width: int = 8
    # TRAKE: pool ứng viên SÂU mỗi event + số frame giữ lại mỗi video/event.
    # Cách cũ giao top-25 toàn cục của MỌI event -> gần như luôn rỗng với 3-4
    # event mô tả mịn (frame đúng nằm sâu dưới top vài trăm toàn cục nhưng vẫn
    # thuộc nhóm đầu trong video đúng). Pool sâu rồi mới gom giao theo video;
    # từ 3 event trở lên chấp nhận thiếu 1 event (coverage n-1).
    temporal_pool: int = 1200
    temporal_per_video: int = 8
    # Điểm ASR mềm cộng vào từng event (search_temporal): trước đây OCR/ASR chỉ
    # là FILTER cứng, mỗi event chấm thuần visual - video khớp hình nhưng "câm
    # chữ" (slide bài giảng trông giống thắng cảnh) đè được video đúng có lời
    # thuyết minh khớp. E5 đa ngữ nên event tiếng Anh vẫn match ASR tiếng Việt.
    # Điểm event = visual/max + weight * asr/max. 0 = tắt (về thuần visual).
    temporal_asr_weight: float = 0.5
    # Kênh caption mềm per event, cùng cơ chế với ASR. Bằng chứng từ vòng đánh
    # giá: query "mở đầu... kết thúc..." bị planner tách event và đi đường
    # temporal - đường này từng THUẦN visual nên caption không cứu được dù
    # index caption CÓ đáp án (vd "người tuyết khổng lồ" p2-7). 0 = tắt.
    temporal_caption_weight: float = 0.5

    # Khi semantic KHÔNG khả dụng (thiếu model/index) thì OCR/ASR fallback bằng:
    #   exact = khớp chuỗi con (mặc định cũ, chính xác tuyệt đối)
    #   fuzzy = khớp gần đúng (rapidfuzz) - chịu được sai chính tả / lỗi OCR-ASR
    # Nếu chọn fuzzy mà rapidfuzz chưa cài thì tự về exact (không bao giờ vỡ).
    text_fallback_mode: str = "fuzzy"   # exact | fuzzy
    fuzzy_threshold: float = 0.6        # điểm fuzzy tối thiểu (0..1) để giữ kết quả

    # --- Phòng thi nhóm (xem services/room_store.py) ---------------------------
    # 5 người dùng CHUNG một backend trên LAN: giỏ đáp án + lịch sử truy vấn nằm
    # ở server thay vì localStorage từng máy. Tắt = backend chạy y như cũ.
    room_enabled: bool = True
    # State phòng ghi ra ĐÂY, không ghi vào data_dir - data/ là read-only thuần
    # (index FAISS + JSON), giữ nguyên tính chất đó để backup/rsync không lẫn.
    room_dir: str = "./room_state"
    room_snapshot_debounce_s: float = 1.0
    room_history_max: int = 200

    # --- Lịch sử tra cứu Agent (xem services/agent_history_store.py) -----------
    # Riêng từng thành viên, mỗi member một file trong ROOM_DIR/agent-history.
    # Ba con số này là trần dung lượng: một lượt top_k=200 nặng ~70KB nên không
    # thể giữ vô hạn. Trần cắt PAYLOAD trước, cắt CHỮ sau - phần chữ rẻ và là
    # thứ giúp nhớ mình đã dò hướng nào.
    agent_history_max_chats: int = 30      # số cuộc trò chuyện giữ lại / member
    agent_history_result_cap: int = 200    # số frame giữ lại trong MỘT lượt
    agent_history_payload_turns: int = 60  # số lượt MỚI NHẤT còn giữ danh sách frame

    # CORS: đồng đội mở FE bằng IP LAN của máy chủ (http://192.168.x.y:5173), mà
    # IP đó đổi theo từng phòng thi nên không liệt kê trước được. Regex này cho
    # qua mọi origin thuộc dải IP riêng + localhost. Đặt false nếu deploy public.
    cors_allow_lan: bool = True

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_regex(self) -> str | None:
        """Regex origin cho LAN, hoặc None khi tắt.

        Dải riêng RFC1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, cộng
        localhost/127.x. Cổng tuỳ ý vì FE có thể chạy 5173 (dev) hay 4173
        (preview).
        """
        if not self.cors_allow_lan:
            return None
        return (
            r"^https?://("
            r"localhost|127\.\d+\.\d+\.\d+"
            r"|10\.\d+\.\d+\.\d+"
            r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
            r"|192\.168\.\d+\.\d+"
            r")(:\d+)?$"
        )

    @property
    def room_path(self) -> Path:
        return Path(self.room_dir).resolve()

    @property
    def media_base(self) -> str:
        return self.media_base_url.rstrip("/")

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).resolve()

    @property
    def media_path(self) -> Path:
        """Thư mục kho keyframe trên đĩa BE. Chỉ có nghĩa khi media_dir khác rỗng."""
        return Path(self.media_dir).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
