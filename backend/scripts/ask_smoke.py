"""Smoke test cho POST /agent/ask - chạy KHÔNG cần nạp model.

    python scripts/ask_smoke.py

Dựng một FastAPI chỉ gắn router `agent` rồi THAY hai đường xử lý bên dưới
(agent_chat / agent_qa) bằng bản giả. Thứ được kiểm ở đây là ĐỊNH TUYẾN - phần
duy nhất /agent/ask tự làm:

  1. câu hỏi gõ tay -> đường QA;
  2. đề đánh số E1..E4 -> đường temporal, kèm hint "trake" xuống planner;
  3. mô tả cảnh -> đường KIS;
  4. nhãn dạng từ bộ đề THẮNG bộ nhận dạng (đề KIS có dấu ? trong mô tả);
  5. frame người dùng chọn sẵn đi đúng sang QA;
  6. đề TRAKE mà planner chỉ tách được 1 cảnh -> hạ về KIS và nói rõ lý do;
  7. không có message người dùng -> 400.

Chất lượng NHẬN DẠNG dạng đề là việc của scripts/eval_task_classifier.py (đo
trên toàn bộ đề mẫu trong query_example/), không phải của file này.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI                                   # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402

import routers.agent as A                                     # noqa: E402

calls = []


def frame(fid):
    return {"id": fid, "score": 0.5, "frame_name": "001.webp", "video_name": "L01_V001",
            "timestamp_ms": 0, "fps": 25.0, "frame_url": "/f", "video_url": "/v"}


async def fake_chat(req):
    calls.append(("chat", req.task_type))
    videos = ([{"video_name": "L01_V001",
                "best_sequence": {"total_score": 1.0, "events": []}}]
              if req.task_type == "trake" else [])
    return {"reply": "r", "plan": {"mode": "temporal" if videos else "search",
                                   "events": ["a", "b", "c"] if videos else []},
            "results": [] if videos else [frame("L01_V001_1")], "videos": videos, "trace": []}


async def fake_qa(req):
    calls.append(("qa", req.question, tuple(req.frame_ids or ())))
    return {"answer": "cá lóc", "frames": [frame("L01_V001_9")]}


A.agent_chat = fake_chat
A.agent_qa = fake_qa

app = FastAPI()
app.include_router(A.router)
client = TestClient(app)
fails = []


def ask(text, **kw):
    r = client.post("/agent/ask", json={"messages": [{"role": "user", "content": text}], **kw})
    assert r.status_code == 200, r.text
    return r.json()


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" != {want!r}"))
    if not ok:
        fails.append(name)


def main() -> int:
    out = ask("Trong video nấu ăn, đầu bếp cho sả vào bụng cá. Đây là loài cá gì?")
    check("qa/dạng", (out["task_type"], out["task_source"]), ("qa", "auto"))
    check("qa/trả lời", out["answer"], "cá lóc")
    check("qa/đường xử lý", calls[-1][0], "qa")

    calls.clear()
    out = ask("Chuỗi cảnh trong vườn.\nE1: sầu riêng.\nE2: măng cụt.\nE3: bưởi.\nE4: dâu.")
    check("trake/dạng", out["task_type"], "trake")
    check("trake/hint xuống planner", calls[-1], ("chat", "trake"))
    check("trake/nhóm video", len(out["videos"]), 1)
    check("trake/số cảnh theo planner", out["num_events"], 3)

    calls.clear()
    out = ask("Hai bạn trẻ đang treo băng-rôn lớn màu xanh dương trước sân trường.")
    check("kis/dạng", out["task_type"], "kis")
    check("kis/hint xuống planner", calls[-1], ("chat", "kis"))
    check("kis/lưới frame", len(out["results"]), 1)

    calls.clear()
    out = ask("Một chú lân (hay sư tử?) màu vàng rơi từ trên cao xuống.", task_type="qa")
    check("bộ đề/thắng bộ nhận dạng", (out["task_type"], out["task_source"]), ("qa", "explicit"))
    check("bộ đề/đường xử lý", calls[-1][0], "qa")

    calls.clear()
    ask("Trên dĩa có mấy quả cà chua?", frame_ids=["L01_V001_5"])
    check("frame đã chọn -> QA", calls[-1][2], ("L01_V001_5",))

    calls.clear()
    A.agent_chat = lambda req: fake_chat(
        A.AgentChatRequest(**{**req.model_dump(), "task_type": "kis"}))
    out = ask("E1: cảnh A.\nE2: cảnh B.")
    check("trake/hạ về kis khi thiếu event", out["task_type"], "kis")
    check("trake/nói rõ lý do", "planner chỉ tách được 1 cảnh" in out["task_reason"], True)
    A.agent_chat = fake_chat

    r = client.post("/agent/ask", json={"messages": [{"role": "assistant", "content": "hi"}]})
    check("thiếu câu người dùng -> 400", r.status_code, 400)

    print("\n" + ("TAT CA PASS" if not fails else f"{len(fails)} FAIL: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
