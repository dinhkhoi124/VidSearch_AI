"""A/B ba ô lọc OCR/ASR/caption của /search_text: cổng AND vs trộn điểm.

    python scripts/eval_search_text.py                    # cả 3 nhánh, top_k=100
    python scripts/eval_search_text.py --only p2-17-kis
    python scripts/eval_search_text.py --no_rerank        # nhanh hơn, bỏ BLIP

Ba nhánh chạy trên CÙNG một câu, khác nhau đúng một tham số:

    none    /search_text không có ô lọc nào   -> mốc để biết ô lọc giúp hay hại
    filter  text_mode=filter (mặc định hiện tại) -> cổng AND trên pool visual
    fuse    text_mode=fuse                       -> OCR/ASR/caption thành kênh
                                                    retrieval riêng, cộng điểm

Câu hỏi + ground truth lấy từ eval/sotuyen12.json; từ khoá gõ vào ô lọc lấy từ
eval/search_filters.json (chỉ trích từ chính đề bài - xem trường `from` ở đó).
Chấm bằng đúng hàm của scripts/eval_agent.py nên số liệu so được với eval agent.

Chỉ gọi HTTP tới backend đang chạy - không nạp model, không build gì.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_agent import KS, frame_idx, score_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODES = ("none", "filter", "fuse")


def run_one(client: httpx.Client, base: str, q: dict, kw: dict, mode: str,
            args) -> dict:
    """Một câu, một nhánh -> {video_rank, frame_rank, n, sec}."""
    params = {
        "query": q["query"], "top_k": args.top_k, "model": args.model,
        "rerank": not args.no_rerank, "expand": not args.no_expand,
        "text_mode": "fuse" if mode == "fuse" else "filter",
    }
    if mode != "none":
        params["ocr_keywords"] = kw.get("ocr", "")
        params["asr_keywords"] = kw.get("asr", "")
        params["caption_keywords"] = kw.get("caption", "")

    t0 = time.time()
    res = client.post(f"{base}/search_text", params=params, timeout=args.timeout).json()
    rows = [(r["video_name"], frame_idx(r), r.get("fps")) for r in res.get("results", [])]
    out = score_rows(q, rows)
    out["n"] = len(rows)
    out["sec"] = round(time.time() - t0, 1)
    out["top"] = [(v, f) for v, f, _ in rows[:3]]
    return out


def rank_str(r) -> str:
    return str(r) if r else "-"


def summarize(results: list) -> None:
    print(f"\n== Tổng hợp ({len(results)} câu)")
    head = f"{'nhánh':7} " + " ".join(f"vid@{k:<3}" for k in KS) + "  " \
        + " ".join(f"frm@{k:<3}" for k in KS) + "  rỗng  giây/câu"
    print(head)
    for mode in MODES:
        rs = [r[mode] for r in results]
        vid = " ".join(f"{sum(1 for x in rs if x['video_rank'] and x['video_rank'] <= k):>6} "
                       for k in KS)
        frm = " ".join(f"{sum(1 for x in rs if x['frame_rank'] and x['frame_rank'] <= k):>6} "
                       for k in KS)
        empty = sum(1 for x in rs if x["n"] == 0)
        sec = sum(x["sec"] for x in rs) / max(len(rs), 1)
        print(f"{mode:7} {vid}  {frm}  {empty:>4}  {sec:>7.1f}")

    print("\n== Từng câu (hạng video / hạng frame)")
    print(f"{'id':12} {'none':>12} {'filter':>12} {'fuse':>12}  từ khoá")
    for r in results:
        cells = " ".join(
            f"{rank_str(r[m]['video_rank']) + '/' + rank_str(r[m]['frame_rank']):>12}"
            for m in MODES)
        kw = " · ".join(f"{k}={v}" for k, v in r["kw"].items() if v)
        print(f"{r['id']:12} {cells}  {kw}")

    # Ai thắng ai, tính theo hạng video (thấp hơn = tốt hơn).
    def better(a, b) -> int:
        ra = a["video_rank"] or 10**6
        rb = b["video_rank"] or 10**6
        return (ra < rb) - (ra > rb)

    wins = sum(1 for r in results if better(r["fuse"], r["filter"]) > 0)
    loses = sum(1 for r in results if better(r["fuse"], r["filter"]) < 0)
    print(f"\nfuse vs filter theo hạng video: thắng {wins}, thua {loses}, "
          f"hoà {len(results) - wins - loses}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--set", default=str(ROOT / "eval" / "sotuyen12.json"))
    ap.add_argument("--filters", default=str(ROOT / "eval" / "search_filters.json"))
    ap.add_argument("--top_k", type=int, default=100)
    ap.add_argument("--model", default="ensemble")
    ap.add_argument("--no_rerank", action="store_true")
    ap.add_argument("--no_expand", action="store_true")
    ap.add_argument("--only", default="", help="danh sách id, phẩy")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--out", default="", help="ghi kết quả thô ra file JSON")
    args = ap.parse_args()

    gt = {q["id"]: q for q in json.load(open(args.set, encoding="utf-8"))["queries"]}
    ann = json.load(open(args.filters, encoding="utf-8"))["queries"]
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    if only:
        ann = [a for a in ann if a["id"] in only]

    results = []
    with httpx.Client() as client:
        for i, a in enumerate(ann, 1):
            q = gt.get(a["id"])
            if q is None:
                print(f"[bỏ qua] {a['id']} không có trong {args.set}")
                continue
            kw = {k: a.get(k, "") for k in ("ocr", "asr", "caption")}
            row = {"id": a["id"], "task": q["task"], "kw": kw}
            for mode in MODES:
                row[mode] = run_one(client, args.base, q, kw, mode, args)
            results.append(row)
            cells = "  ".join(
                f"{m}={rank_str(row[m]['video_rank'])}/{rank_str(row[m]['frame_rank'])}"
                for m in MODES)
            print(f"[{i}/{len(ann)}] {a['id']:12} {cells}")

    if not results:
        print("Không có câu nào chạy được.")
        return 2
    summarize(results)
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\nĐã ghi {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
