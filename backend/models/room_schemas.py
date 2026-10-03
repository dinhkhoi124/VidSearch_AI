"""Pydantic models cho phòng thi nhóm (xem services/room_store.py).

QUY ƯỚC ĐẶT TÊN TRƯỜNG - cố ý trộn hai kiểu, đừng "dọn" cho đồng nhất:
  * Trường của STATE (`numQuestions`, `taskType`, `queryId`, `maxRows`) giữ
    camelCase y hệt bên JS, để state đi thẳng vào frontend/src/hooks/basketReducer.js
    mà không cần lớp dịch tên nào cả - lớp dịch đó là chỗ rất dễ lệch âm thầm.
  * Trường của VỎ MESSAGE (`num_questions`, `member_id`, ...) dùng snake_case
    theo chuẩn Python, vì nó không bao giờ đi vào state.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Danh sách op PHẢI khớp frontend/src/hooks/basketReducer.js
OpType = Literal[
    "add",
    "remove",
    "move",
    "reorder",
    "set_answer",
    "set_note",
    # Sửa tay số frame của một mục (dùng `id` + `value`, không cần trường mới).
    "set_frame",
    "set_task_type",
    "set_query_id",
    "set_max_rows",
    # Thiếu các op này thì POST /room/op trả 422, roomClient lặng lẽ bỏ op (xem
    # drain() bên đó) -> nạp gói đề và số event TRAKE chỉ nằm trên máy người bấm,
    # rồi mất hẳn khi server phát snapshot về. _apply() vẫn luôn xử lý chúng.
    "set_num_events",
    "set_query_text",
    "clear_question",
    "clear_all",
    "set_num_questions",
    "import_package",
]


class PackageItem(BaseModel):
    """Cấu hình MỘT câu trong gói truy vấn BTC phát. camelCase theo quy ước
    trường-của-state ở đầu file: nó đi thẳng vào state.questions[qid]."""

    qid: int = 1
    taskType: Optional[str] = None
    queryId: Optional[str] = None
    queryText: Optional[str] = None
    numEvents: Optional[int] = None


class BasketItem(BaseModel):
    """Một frame trong giỏ. Shape khớp toEntry() bên JS."""

    id: str
    video_name: Optional[str] = None
    frame_name: Optional[str] = None
    frame_idx: Optional[int] = None
    # Số frame máy tự tính lúc thêm vào giỏ, chỉ có mặt khi đã bị SỬA TAY (op
    # "set_frame" ghi ở lần sửa đầu) - mốc để hoàn tác. Khai ở đây để item sửa
    # tay đi qua một op "add" nào đó cũng không bị pydantic lặng lẽ cắt mất.
    frame_idx0: Optional[int] = None
    timestamp_ms: Optional[float] = None
    fps: Optional[float] = None
    frame_url: Optional[str] = None
    video_url: Optional[str] = None
    answer: str = ""
    note: str = ""
    # Server tự đóng dấu 3 trường này, KHÔNG tin client: đồng hồ 5 máy lệch nhau
    # thì thứ tự "ai thêm trước" hiển thị sẽ sai.
    added_by: Optional[str] = None
    added_by_name: Optional[str] = None
    added_at: Optional[int] = None


class Op(BaseModel):
    """Một thao tác lên giỏ. `qid` luôn TUYỆT ĐỐI - server không biết máy nào
    đang mở câu nào, nên không có khái niệm "câu hiện tại" ở đây."""

    type: OpType
    qid: Optional[int] = None
    id: Optional[str] = None
    item: Optional[BasketItem] = None
    dir: Optional[int] = None
    # `from` là từ khoá Python -> phải alias.
    from_: Optional[int] = Field(default=None, alias="from")
    to: Optional[int] = None
    text: Optional[str] = None
    value: Optional[Any] = None
    # Chỉ op "import_package" dùng hai trường này. Không khai ở đây thì pydantic
    # lặng lẽ bỏ trường, op tới server rỗng và không nạp được gì.
    items: Optional[List[PackageItem]] = None
    # reset: True = "nhập lại từ đầu" (xoá sạch câu cũ rồi dựng lại theo gói),
    # None/False = gộp vào đề đang có. Bỏ trường thì server lặng lẽ chạy chế độ
    # gộp trong khi máy bấm đã xoá sạch tại chỗ - snapshot phát về sẽ dựng lại
    # đúng cái đề vừa bỏ.
    reset: Optional[bool] = None

    model_config = {"populate_by_name": True}


class OpRequest(BaseModel):
    member_id: str
    member_name: str = ""
    op: Op


class HistoryRequest(BaseModel):
    member_id: str
    member_name: str = ""
    mode: str
    query: str
    result_count: int = 0


class SubmitLogFile(BaseModel):
    """Một file csv trong gói zip đã tải. Chỉ giữ tên + số dòng: nội dung file
    không cần đi qua phòng, mà gửi cả nội dung thì message broadcast phình ra."""

    filename: str = ""
    rows: int = 0


class SubmitLogRequest(BaseModel):
    """Một lượt tải zip nộp bài. `id` do client sinh và server giữ nguyên để khử
    trùng (xem RoomStore.add_submission)."""

    member_id: str
    member_name: str = ""
    id: str
    # ISO string từ client - chỉ để hiển thị, thứ tự trong log theo thứ tự tới.
    at: str = ""
    package_name: str = ""
    zip_name: str = ""
    files: List[SubmitLogFile] = []


class HistoryEntry(BaseModel):
    id: str
    member_id: str
    member_name: str
    mode: str
    query: str
    result_count: int
    ts: int


class SubmitLogFile(BaseModel):
    filename: str
    rows: int = 0


class SubmitLogRequest(BaseModel):
    """Một lượt tải zip nộp bài, để CẢ PHÒNG cùng đếm được đã dùng mấy lượt.

    Chỉ metadata: nội dung CSV ở lại máy tạo ra nó (xem
    frontend/src/hooks/useSubmissionLog.js). `id` và `at` do client sinh để mục
    quay lại qua broadcast còn khử trùng được với bản local của chính nó.
    """

    member_id: str
    member_name: str = ""
    id: str
    at: str
    package_name: str = ""
    zip_name: str = ""
    files: List[SubmitLogFile] = []


class SubmitLogEntry(BaseModel):
    id: str
    at: str
    member_id: str
    member_name: str
    # camelCase: mục này đi thẳng vào state dùng chung với JS, như questions.
    packageName: str
    zipName: str
    files: List[SubmitLogFile] = []


# --- Lịch sử tra cứu Agent (riêng từng thành viên) ---------------------------
class AgentTurn(BaseModel):
    """Một lượt hỏi-đáp với Agent, KÈM kết quả để xem lại mà không tra lại.

    `results` / `videos` / `plan` / `trace` để nguyên kiểu mở (Any): dữ liệu này
    do CHÍNH backend sinh ra ở /agent/chat rồi quay về, validate lại theo
    SearchResult chỉ tốn CPU và thêm một đường 422 - mà 4xx thì drain() bên
    frontend/src/api/roomClient.js LẶNG LẼ vứt cả lượt, tức là mất đúng thứ ta
    đang cố lưu. Trần dung lượng do agent_history_store lo.
    """

    id: str
    ts: Optional[int] = None
    mode: str = "search"
    question: str = ""
    reply: str = ""
    plan: Optional[Dict[str, Any]] = None
    trace: List[Dict[str, Any]] = []
    result_type: str = "grid"
    results: List[Dict[str, Any]] = []
    videos: List[Dict[str, Any]] = []


class AgentTurnRequest(BaseModel):
    member_id: str
    member_name: str = ""
    chat_id: str
    # Tiêu đề cuộc = câu hỏi ĐẦU TIÊN, do client gửi kèm mỗi lượt cho đơn giản;
    # server chỉ nhận nó khi cuộc chưa có tiêu đề.
    title: str = ""
    turn: AgentTurn


class AgentChatDeleteRequest(BaseModel):
    member_id: str
    member_name: str = ""
    # Thiếu = xoá TOÀN BỘ lịch sử Agent của thành viên này.
    chat_id: Optional[str] = None


class MemberPresence(BaseModel):
    id: str
    name: str
    current: int = 1
    online_since: int


class RoomStateResponse(BaseModel):
    rev: int
    numQuestions: int
    questions: Dict[str, Dict[str, Any]]
    history: List[HistoryEntry]
    submitLog: List[SubmitLogEntry] = []
    members: List[MemberPresence] = []
