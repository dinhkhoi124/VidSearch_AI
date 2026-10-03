"""Pydantic schemas matching BACKEND_API_SPEC.md."""
from typing import List, Optional

from pydantic import BaseModel

from config import get_settings

settings = get_settings()


# ---------- text / image / ocr ----------
class SearchResult(BaseModel):
    id: str
    score: float
    frame_name: str
    video_name: str
    timestamp_ms: int
    fps: float
    frame_url: str
    video_url: str
    # Khoảng shot chứa frame (từ graph.json). None khi chưa build graph -
    # frontend tự ẩn phần hiển thị shot.
    scene_id: Optional[str] = None
    shot_start_ms: Optional[int] = None
    shot_end_ms: Optional[int] = None
    # Các frame TRÙNG THỊ GIÁC với frame này, đã bị gộp khỏi lưới chính (xem
    # services/dedup_service). Trả kèm chứ không xoá: frame đúng để nộp nhiều
    # khi là bản thứ bảy của cụm chứ không phải bản điểm cao nhất, và UI cho
    # bung cụm ra mà không phải search lại. Luôn rỗng ở chính các phần tử này
    # (không lồng hai tầng).
    duplicates: List["SearchResult"] = []
    duplicate_count: int = 0


class SearchResponse(BaseModel):
    results: List[SearchResult]
    # Bộ lọc caption gõ tiếng Việt được LLM dịch sang tiếng Anh (caption do
    # Qwen2.5-VL sinh bằng tiếng Anh). None = không dịch gì. UI hiện lại cho
    # người dùng thấy mình đang thực sự lọc theo chữ nào — dịch sai mà im lặng
    # thì chỉ thấy "không có kết quả" và không hiểu vì sao.
    caption_translation: Optional[str] = None


# ---------- asr ----------
class AsrFrame(BaseModel):
    id: str
    frame_name: str
    frame_url: str
    video_url: str
    timestamp_ms: int
    fps: float
    score: float


class AsrSegment(BaseModel):
    asr_text: str
    frames: List[AsrFrame]


class AsrVideoGroup(BaseModel):
    video_name: str
    segments: List[AsrSegment]


class AsrSearchResponse(BaseModel):
    videos: List[AsrVideoGroup]


# ---------- temporal ----------
class TemporalEvent(BaseModel):
    id: str
    event_index: int
    frame_name: str
    frame_url: str
    video_url: str
    timestamp_ms: int
    fps: float
    score: float


class TemporalBestSequence(BaseModel):
    total_score: float
    events: List[TemporalEvent]


class TemporalVideoGroup(BaseModel):
    video_name: str
    best_sequence: TemporalBestSequence


class TemporalSearchResponse(BaseModel):
    videos: List[TemporalVideoGroup]


# ---------- relevance feedback ----------
class FeedbackSearchRequest(BaseModel):
    frame_ids: List[str]            # frames the user marked as relevant
    query: str = ""                 # original query; "" = pure visual pooling
    top_k: int = 25
    # Theo DEFAULT_MODEL thay vì ghim cứng - ghim cứng sẽ lệch backbone với
    # /search_text ngay khi đổi cấu hình, và lệch chiều vector so với index.
    model: str = settings.default_model


# ---------- agent ----------
class ChatMessage(BaseModel):
    role: str                       # "user" | "assistant"
    content: str


class AgentChatRequest(BaseModel):
    messages: List[ChatMessage]
    top_k: int = 25
    # ensemble: thắng rõ backbone đơn trên tập câu khó - các backbone bù góc
    # nhìn nhau. Thành phần lấy từ ENSEMBLE_MODELS trong .env (hiện tại
    # siglip512:0.5,metaclip:0.5), không ghim ở đây. Temporal tự quy về member
    # trọng số cao nhất khi nhận "ensemble".
    model: str = "ensemble"
    # BLIP chấm lại head fan-out (~100 ảnh, vài giây GPU). Bật mặc định: chat
    # là đường chính của thi đấu, độ chính xác đáng vài giây; model thiếu/OOM
    # thì rerank tự bỏ qua nên không có rủi ro vỡ.
    rerank: bool = True
    deep: bool = False              # true = ép chạy vòng ReAct (kể cả khi kết quả tốt)
    # Dạng đề đã biết ("kis" | "trake"), "" = để planner tự quyết. Biết trước
    # dạng thì planner khỏi phải đoán mode: đề TRAKE luôn ra mode="temporal".
    task_type: str = ""


class AgentChatResponse(BaseModel):
    reply: str                      # câu trả lời hội thoại cho người dùng
    plan: dict                      # structured query mà agent đã suy ra
    results: List[SearchResult] = []            # mode=search
    videos: List[TemporalVideoGroup] = []       # mode=temporal
    trace: List[dict] = []          # các bước ReAct (thought + action), [] nếu one-shot


class AgentQaRequest(BaseModel):
    question: str
    frame_ids: Optional[List[str]] = None       # None = tự retrieve từ question
    top_k: int = 6
    model: str = "ensemble"         # cùng lý do AgentChatRequest


class AgentQaResponse(BaseModel):
    answer: str
    frames: List[SearchResult]      # các frame đã dùng làm bằng chứng


class AgentAskRequest(BaseModel):
    """Một ô nhập cho cả ba dạng đề - xem POST /agent/ask."""
    messages: List[ChatMessage]
    # "kis" | "qa" | "trake" lấy từ gói đề BTC phát. "" = tự nhận dạng từ chính
    # câu đề (services/task_classifier).
    task_type: str = ""
    frame_ids: Optional[List[str]] = None       # QA: frame người dùng đã chọn
    top_k: int = 25
    model: str = "ensemble"
    rerank: bool = True
    deep: bool = False


class AgentAskResponse(BaseModel):
    task_type: str                  # dạng đã dùng để xử lý
    task_source: str                # "explicit" (từ bộ đề) | "auto" (tự nhận dạng)
    task_reason: str                # vì sao ra dạng đó - UI hiện cho người dùng biết
    num_events: int = 0             # TRAKE: số cảnh đếm được, 0 nếu không rõ
    reply: str
    answer: str = ""                # QA: câu trả lời; dạng khác để rỗng
    plan: dict = {}
    results: List[SearchResult] = []
    videos: List[TemporalVideoGroup] = []
    trace: List[dict] = []


class LlmKeyRequest(BaseModel):
    """Đổi key LLM lúc đang chạy — key free tier cạn quota giữa buổi thi thì
    dán key khác vào, khỏi phải restart backend (nạp lại model mất ~10 phút)."""
    api_key: str
    provider: str = "gemini"        # hiện chỉ nhận "gemini"
    # Rỗng = giữ model đang dùng. Có ích khi key mới thuộc project khác và chỉ
    # được cấp quota cho một model nhất định.
    model: str = ""


class LlmKeyResponse(BaseModel):
    ok: bool
    provider: str
    key_hint: str                   # 4 ký tự cuối, KHÔNG bao giờ trả key đầy đủ
    model: str
    message: str


class LlmConfigRequest(BaseModel):
    """Đổi provider LLM / model OpenAI-compat lúc đang chạy.

    None = GIỮ NGUYÊN field đó. Chuỗi rỗng = XOÁ nó (react/qa rỗng nghĩa là
    dùng lại openai_model). Phân biệt hai thứ đó là lý do mọi field là Optional
    chứ không phải str mặc định rỗng: gửi kèm cả form thì mỗi lần bấm Áp dụng
    sẽ ghi đè cả những ô người dùng không hề chạm vào.
    """
    provider: Optional[str] = None           # auto | openai_first | gemini | openai
    openai_model: Optional[str] = None
    openai_react_model: Optional[str] = None
    openai_qa_model: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_api_key: Optional[str] = None


class LlmConfigResponse(BaseModel):
    ok: bool
    message: str
    # Snapshot sau khi đổi (đã che key) — FE khỏi phải GET lại để vẽ lại form.
    config: dict
