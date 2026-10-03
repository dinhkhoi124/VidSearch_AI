"""Pre-submit verifier (CLI): đối chiếu submission CSV với bằng chứng trong index.

Lõi kiểm chứng nằm ở services/verify_service.py (dùng chung với endpoint
/verify_answers mà giao diện gọi). File này chỉ lo: đọc thư mục đề + thư mục
CSV, parse dòng theo loại câu, in báo cáo, và tầng --vision cho câu QA.

Chạy từ backend/:
    python scripts/verify_submission.py --queries <dir .txt> --submission <dir .csv>
Thêm --vision để hỏi LLM vision lại câu QA trên chính frame nộp (cần key sống).
Exit code 1 nếu có cảnh báo ĐỎ - tiện nhét vào bước chặn trước khi nộp.

Đọc kết quả: RED = dừng lại xem (sai video thật hoặc lỗi format - tool in luôn
video gợi ý); YELLOW = nghi vấn nhẹ (lệch chủ đề / anchor chỉ nhìn thấy chứ
không nói-hiện chữ). RED oan có xảy ra: whisper nghe nhầm tên đường, đề viết
tắt còn ASR đọc đầy đủ (đo được 2/30 câu trên bộ SOTUYEN2).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.text_norm import fold  # noqa: E402
from services.verify_service import verify_rows  # noqa: E402


def vision_answer(query: str, video: str, frame_name: str) -> str:
    """Hỏi LLM vision chính câu hỏi trên chính frame được nộp."""
    from services.agent_service import _gemini_generate, _image_part
    from services.metadata_service import frame_bytes_many

    blobs = frame_bytes_many([(video, frame_name)])
    img = _image_part(blobs[0] if blobs else None,
                      suffix=frame_name.rsplit(".", 1)[-1]) if blobs else None
    if img is None:
        return "(không đọc được ảnh)"
    parts = [
        {"text": "Answer the question about THIS image only, in Vietnamese, "
                 "as short as possible (a number or a noun phrase). Question: "
                 + query},
        img,
    ]
    return (_gemini_generate(parts, temperature=0.0, task="verify") or "(LLM lỗi)").strip()


def parse_rows(csv_path: Path, qtype: str) -> List[dict]:
    rows = []
    for ln in csv_path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(",")
        video = parts[0]
        if qtype == "qa":
            # video,frame,answer - answer có thể là SỐ ("1204"), không được nuốt vào frame
            nums = [int(parts[1])] if len(parts) > 1 and parts[1].isdigit() else []
            answer = ",".join(parts[2:]) if len(parts) > 2 else ""
        else:
            nums = []
            for p in parts[1:]:
                if re.fullmatch(r"\d+", p):
                    nums.append(int(p))
                else:
                    break
            answer = ",".join(parts[1 + len(nums):]) if len(parts) > 1 + len(nums) else ""
        rows.append({"line": ln, "video_name": video, "frames": nums,
                     "answer": answer, "type": qtype})
    return rows


def format_warns(rows: List[dict], qtype: str) -> List[str]:
    warns = []
    for r in rows:
        if qtype == "kis" and (len(r["frames"]) != 1 or r["answer"]):
            warns.append(f"RED  format: dòng KIS phải là video,frame - '{r['line']}'")
        if qtype == "qa" and (len(r["frames"]) != 1 or not r["answer"]):
            warns.append(f"RED  format: dòng QA phải là video,frame,answer - '{r['line']}'")
        if qtype == "trake" and len(r["frames"]) < 2:
            warns.append(f"RED  format: dòng TRAKE cần >=2 frame - '{r['line']}'")
    if len(rows) > 100:
        warns.append(f"RED  format: {len(rows)} dòng > 100")
    return warns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queries", required=True, help="thư mục chứa query-*.txt")
    ap.add_argument("--submission", required=True, help="thư mục chứa query-*.csv")
    ap.add_argument("--vision", action="store_true",
                    help="bật tầng 3: LLM vision hỏi lại câu QA trên chính frame nộp")
    args = ap.parse_args()

    qdir, sdir = Path(args.queries), Path(args.submission)
    total_red = 0
    for qfile in sorted(qdir.glob("*.txt"),
                        key=lambda p: int(re.search(r"-(\d+)-", p.stem).group(1))):
        qtype = qfile.stem.rsplit("-", 1)[-1]
        csv_path = sdir / (qfile.stem + ".csv")
        if not csv_path.exists():
            print(f"❌ {qfile.stem}: THIẾU file submission")
            total_red += 1
            continue
        query = qfile.read_text(encoding="utf-8").strip()
        rows = parse_rows(csv_path, qtype)

        warns = format_warns(rows, qtype)
        warns += [f"{w['level'].upper():6} {w['msg']}"
                  for w in verify_rows(query, rows, task_type=qtype)]

        if args.vision and qtype == "qa" and rows:
            from services.metadata_service import frames_in_video

            r = rows[0]
            names = frames_in_video(r["video_name"])
            target = f"{r['frames'][0]:06d}" if r["frames"] else ""
            name = next((n for n in names if n.startswith(target)), None) if target else None
            if name:
                got = vision_answer(query, r["video_name"], name)
                if fold(r["answer"]) not in fold(got) and fold(got) not in fold(r["answer"]):
                    warns.append(f"YELLOW vision trả lời '{got}' khác đáp án nộp "
                                 f"'{r['answer']}' - kiểm tra bằng mắt")

        reds = [w for w in warns if w.startswith("RED")]
        total_red += len(reds)
        mark = "❌" if reds else ("⚠️ " if warns else "✅")
        print(f"{mark} {qfile.stem} ({len(rows)} dòng)")
        for w in warns:
            print(f"     {w}")
    print()
    print("KẾT LUẬN:", "CÓ CẢNH BÁO ĐỎ - xem lại trước khi nộp" if total_red
          else "sạch - không thấy dòng nào mâu thuẫn với bằng chứng")
    return 1 if total_red else 0


if __name__ == "__main__":
    raise SystemExit(main())
