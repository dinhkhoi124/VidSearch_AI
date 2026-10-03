"""Nhận dạng dạng câu hỏi (kis | qa | trake) từ chính văn bản đề bài.

Ba dạng của cuộc thi cần ba đường xử lý khác nhau (xem routers/agent.py):
KIS -> tìm keyframe, TRAKE -> chuỗi sự kiện theo thời gian, QA -> trả lời câu
hỏi kèm frame bằng chứng. Khi người dùng đã nạp bộ đề thì task_type có sẵn
trong gói câu hỏi và luôn được ưu tiên; module này chỉ lo trường hợp gõ tay
vào ô chat, nơi không có nhãn nào đi kèm.

Luật thuần regex, không gọi LLM: rẻ, tất định, và giải thích được cho người
dùng (mỗi kết quả kèm `reason` để hiển thị). Đo trên toàn bộ đề mẫu trong
query_example/ bằng backend/scripts/eval_task_classifier.py.

Thứ tự xét quan trọng: TRAKE trước QA trước KIS. Một câu TRAKE liệt kê nhiều
cảnh vẫn có thể chứa dấu "?" trong lời mô tả, nhưng cấu trúc liệt kê E1/E2/...
là dấu hiệu mạnh hơn nhiều so với một dấu chấm hỏi.
"""
import re

# Danh sách sự kiện đánh số. Cần >= 2 mục mới tính là TRAKE (một "Cảnh 1:" đơn
# độc là câu KIS mô tả cảnh).
#
# Hai regex vì dấu ngăn cách chỉ được phép vắng mặt ở nhãn E/Event/Step: "E1
# Khoảnh khắc..." (p1-16) không có dấu hai chấm nhưng vẫn rõ ràng, trong khi
# "Cảnh 3 người đàn ông đi bộ" là câu mô tả bình thường - nhãn bằng chữ bắt
# buộc phải có dấu ngăn cách.
_TRAKE_ITEM = re.compile(
    r"(?im)(?:^|[\n;])\s*(?:E|Event|Step)\s*0?([1-9])\b\s*[:.)\-–]?\s*\S"
)
_TRAKE_ITEM_WORD = re.compile(
    r"(?im)(?:^|[\n;])\s*(?:Cảnh|Sự\s*kiện|Bước|Scene)\s*0?([1-9])\s*[:.)\-–]"
)

# Người ra đề nói thẳng "đây là chuỗi cảnh liên tiếp" mà không đánh số.
_TRAKE_PHRASE = re.compile(
    r"(?i)("
    r"chuỗi\s+(?:liên\s*tiếp|hành\s*động|sự\s*kiện|cảnh)"
    r"|(?:xảy\s*ra|diễn\s*ra|nối\s*tiếp|xuất\s*hiện)\s+liên\s*tiếp"
    r"|liên\s*tiếp\s+nhau"
    r"|theo\s+thứ\s*tự\s+(?:thời\s*gian|xuất\s*hiện)"
    r")"
)

# Từ để hỏi tiếng Việt + tiếng Anh. Chỉ dò trong ĐUÔI đề bài (xem _tail): câu
# KIS hay có "?" hoặc "nào" nằm giữa phần mô tả ("một chú lân (hay sư tử?) màu
# vàng..."), còn câu QA luôn đặt câu hỏi ở cuối.
#
# "đâu" trần bị loại: "không thấy quả bí đỏ đâu" (p2-1) là phủ định, không phải
# hỏi nơi chốn - chỉ nhận "ở đâu / tại đâu".
_QA_WORD = re.compile(
    r"(?i)\b("
    r"gì|nào|ai|mấy|bao\s*nhiêu|bao\s*lâu|thế\s*nào|như\s*thế\s*nào"
    r"|[ởtạiừvề]\w*\s+đâu|tại\s*sao|vì\s*sao|khi\s*nào|lúc\s*nào"
    r"|what|which|who|where|when|how\s+many|how\s+much"
    r")\b"
)

# Câu hỏi dạng mệnh lệnh, KHÔNG có từ để hỏi: "Đếm số lượng các miếng trên vỉ
# nướng." (p3-32). Bắt buộc đứng ĐẦU câu cuối - giữa câu thì "cho biết" là động
# từ mô tả ("biển báo cho biết tốc độ tối đa", p3-11) chứ không phải yêu cầu.
_QA_IMPERATIVE = re.compile(
    r"(?i)^[\s\"'(]*(hãy\s+\w+|cho\s+biết|đếm\s+|xác\s+định\s+|liệt\s+kê\s+"
    r"|count\s+|list\s+|identify\s+)"
)

# "nào đó" = bất định, KHÔNG phải câu hỏi ("một người nào đó bước vào").
_QA_WORD_FALSE = re.compile(r"(?i)\b(nào\s+đó|gì\s+đó|ai\s+đó|đâu\s+đó)\b")

TASK_TYPES = ("kis", "qa", "trake")


def _sentences(body: str) -> list:
    """Tách câu theo dấu kết câu VÀ xuống dòng - đề viết liền một khối cũng cắt được."""
    return [p.strip() for p in re.split(r"(?<=[.?!])\s+|\n+", body) if p.strip()]


def _tail(parts: list, n: int = 2, max_chars: int = 240) -> str:
    """n câu cuối của đề bài - nơi câu hỏi luôn nằm.

    Lấy 2 câu chứ không phải 1: nhiều đề chốt bằng một mệnh đề bổ sung sau câu
    hỏi ("Hỏi xã này có tên là gì? (tại thời điểm đó)", p1-15).
    """
    return " ".join(parts[-n:])[-max_chars:]


def classify(text: str) -> dict:
    """text -> {"task_type", "reason", "num_events"}.

    num_events chỉ có nghĩa với TRAKE (số cảnh đếm được, 0 nếu không đếm nổi);
    UI dùng nó để gợi ý số dòng phải nộp cho câu đó.
    """
    body = (text or "").strip()
    if not body:
        return {"task_type": "kis", "reason": "rỗng", "num_events": 0}

    nums = [int(m) for m in _TRAKE_ITEM.findall(body)]
    nums += [int(m) for m in _TRAKE_ITEM_WORD.findall(body)]
    if len(nums) >= 2:
        return {"task_type": "trake",
                "reason": f"liệt kê {len(nums)} sự kiện đánh số",
                "num_events": max(nums)}
    phrase = _TRAKE_PHRASE.search(body)
    if phrase:
        return {"task_type": "trake",
                "reason": f'"{phrase.group(1)}"',
                "num_events": len(nums)}

    parts = _sentences(body)
    last = parts[-1] if parts else body
    if last.endswith("?") or body.endswith("?"):
        return {"task_type": "qa", "reason": "câu cuối là câu hỏi", "num_events": 0}
    imperative = _QA_IMPERATIVE.search(last)
    if imperative:
        return {"task_type": "qa",
                "reason": f'yêu cầu "{imperative.group(1).strip()}" ở câu cuối',
                "num_events": 0}
    hit = _QA_WORD.search(_QA_WORD_FALSE.sub("", _tail(parts)))
    if hit:
        return {"task_type": "qa",
                "reason": f'từ để hỏi "{hit.group(1)}" ở cuối đề',
                "num_events": 0}

    return {"task_type": "kis", "reason": "mô tả cảnh, không có câu hỏi",
            "num_events": 0}
