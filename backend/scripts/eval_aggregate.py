"""Gộp nhiều run của eval_agent.py: trung vị rank từng câu + tổng hợp.

    python scripts/eval_aggregate.py eval/runs/full_baseline*.json
    python scripts/eval_aggregate.py --a "eval/runs/full_baseline*.json" --b "eval/runs/full_deep*.json"

Một lần chạy nhiễu (model qua router không tất định): so hai cấu hình bằng
TRUNG VỊ rank qua >= 3 lần, và chỉ tin khác biệt khi vượt độ dao động giữa các
lần cùng cấu hình (cột min-max).
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
from collections import defaultdict

KS = (1, 5, 20, 100)
MISS = 10 ** 6  # rank None = ngoài top-k


def load(pattern: str) -> list:
    files = sorted(f for p in pattern.split(",") for f in glob.glob(p.strip()))
    runs = [json.load(open(f, encoding="utf-8"))["results"] for f in files]
    return files, runs


def per_query(runs: list, key: str) -> dict:
    d = defaultdict(list)
    for res in runs:
        for r in res:
            d[r["id"]].append(r.get(key) if r.get(key) is not None else MISS)
    return d


def at(ranks: dict, k: int) -> float:
    """Recall@k TRUNG BÌNH qua các lần chạy = số câu đúng kỳ vọng của MỘT lần chạy.

    KHÔNG dùng trung vị rank rồi so với k: `statistics.median` lấy trung bình hai
    giá trị giữa khi số lần chạy CHẴN, nên rank (1, 2) ra 1.5 và trượt @1 - cấu
    hình chạy 2 lần bị chấm thấp hơn cấu hình chạy 3 lần một cách hệ thống, dù
    dữ liệu y hệt.
    """
    per_run = [sum(1 for v in ranks.values() if v[i] <= k) for i in range(len(next(iter(ranks.values()))))]
    return sum(per_run) / len(per_run)


def summary(label: str, runs: list) -> None:
    v = per_query(runs, "video_rank")
    f = per_query(runs, "frame_rank")
    n = len(v)
    print(f"{label:22} n={n} runs={len(runs)} | " +
          " ".join(f"vid@{k}={at(v, k):>5.1f}" for k in KS) + " | " +
          " ".join(f"frm@{k}={at(f, k):>5.1f}" for k in KS))
    # dao động: số câu mà vid@1 đổi giữa các lần chạy
    flip = sum(1 for vals in v.values() if len({x <= 1 for x in vals}) > 1)
    print(f"{'':22} vid@1 đổi giữa các lần chạy ở {flip}/{n} câu")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="*")
    ap.add_argument("--a", default="", help="glob nhóm A (vd baseline)")
    ap.add_argument("--b", default="", help="glob nhóm B (vd deep)")
    args = ap.parse_args()

    if args.a or args.b:
        fa, ra = load(args.a) if args.a else ([], [])
        fb, rb = load(args.b) if args.b else ([], [])
        print("A:", fa); print("B:", fb)
        if ra:
            summary("A", ra)
        if rb:
            summary("B", rb)
        if ra and rb:
            va, vb = per_query(ra, "video_rank"), per_query(rb, "video_rank")
            print(f"\n{'id':14} {'A ranks':>18} {'B ranks':>18}  verdict")
            for qid in sorted(va, key=lambda q: (int(q[1]), int(q.split('-')[1]))):
                a, b = va[qid], vb.get(qid, [])
                ma, mb = statistics.median(a), statistics.median(b) if b else MISS
                verdict = ""
                if b and (mb <= 1 < ma or ma <= 1 < mb or abs(ma - mb) >= 5):
                    verdict = "B better" if mb < ma else "B worse"
                fmt = lambda xs: ",".join("-" if x == MISS else str(x) for x in xs)
                print(f"{qid:14} {fmt(a):>18} {fmt(b):>18}  {verdict}")
        return

    files, runs = load(",".join(args.patterns))
    print("files:", files)
    summary("all", runs)


if __name__ == "__main__":
    main()
