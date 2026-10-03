"""POST /verify_answers - kiểm chứng giỏ đáp án trước khi nộp.

Giao diện gửi nguyên trạng các câu (đề bài + giỏ đáp án), backend đối chiếu với
bằng chứng ASR/OCR/caption trong index (services/verify_service). Chạy offline,
không LLM - đủ nhanh để bấm ngay trước mỗi lần đóng gói nộp.
"""
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class VerifyRow(BaseModel):
    video_name: str
    frames: List[int] = Field(default_factory=list)
    answer: str = ""


class VerifyQuestion(BaseModel):
    qid: int
    task_type: str = ""
    query_text: str = ""
    rows: List[VerifyRow] = Field(default_factory=list)


class VerifyRequest(BaseModel):
    questions: List[VerifyQuestion] = Field(default_factory=list)


class VerifyWarning(BaseModel):
    level: str  # "red" | "yellow"
    msg: str


class VerifyReport(BaseModel):
    qid: int
    warnings: List[VerifyWarning] = Field(default_factory=list)


class VerifyResponse(BaseModel):
    reports: List[VerifyReport] = Field(default_factory=list)


@router.post("/verify_answers", response_model=VerifyResponse)
def verify_answers(req: VerifyRequest) -> VerifyResponse:
    from services.verify_service import verify_rows

    reports: List[VerifyReport] = []
    for q in req.questions:
        if not q.query_text.strip() or not q.rows:
            continue  # câu trống / chưa nhập đề - không có gì để đối chiếu
        warns = verify_rows(
            q.query_text,
            [r.model_dump() for r in q.rows],
            task_type=q.task_type,
        )
        reports.append(VerifyReport(
            qid=q.qid, warnings=[VerifyWarning(**w) for w in warns]))
    return VerifyResponse(reports=reports)
