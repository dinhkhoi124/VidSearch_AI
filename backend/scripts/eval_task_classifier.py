"""Đo services.task_classifier trên các bộ đề mẫu.

Nhãn lấy từ tên file BTC đặt: query-p2-9-qa.txt -> qa. Các bộ đề trùng nội dung
(de1/ và SOTUYEN1-bo-de-thi/ là một) được gộp theo hash nội dung để không thổi
phồng số liệu.

    python backend/scripts/eval_task_classifier.py [thư_mục_đề]

Mặc định thư mục đề là ../query_example so với gốc repo.
"""
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.task_classifier import TASK_TYPES, classify  # noqa: E402

_LABEL = re.compile(r"-(kis|qa|trake)\.txt$", re.I)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[2].parent / "query_example")
    if not root.is_dir():
        print(f"Không thấy thư mục đề: {root}")
        return 2

    seen: set = set()
    rows = []
    for path in sorted(root.rglob("*.txt")):
        m = _LABEL.search(path.name)
        if not m:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        key = hashlib.sha1(text.strip().encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        rows.append((path, m.group(1).lower(), text))

    confusion: Counter = Counter()
    wrong = []
    for path, gold, text in rows:
        out = classify(text)
        confusion[(gold, out["task_type"])] += 1
        if out["task_type"] != gold:
            wrong.append((path, gold, out, text))

    total = len(rows)
    ok = sum(n for (g, p), n in confusion.items() if g == p)
    print(f"{total} câu (đã bỏ trùng), đúng {ok} ({ok / total:.1%})\n")

    print("gold \\ pred   " + "".join(f"{t:>8}" for t in TASK_TYPES))
    for g in TASK_TYPES:
        line = f"{g:<14}" + "".join(f"{confusion[(g, p)]:>8}" for p in TASK_TYPES)
        n = sum(confusion[(g, p)] for p in TASK_TYPES)
        rec = confusion[(g, g)] / n if n else 0.0
        print(f"{line}    recall {rec:.0%}")

    if wrong:
        print(f"\n{len(wrong)} câu sai:")
        for path, gold, out, text in wrong:
            snippet = " ".join(text.split())[:110]
            print(f"  {path.name}: {gold} -> {out['task_type']} "
                  f"({out['reason']})\n      {snippet}")
    return 0 if not wrong else 1


if __name__ == "__main__":
    raise SystemExit(main())
