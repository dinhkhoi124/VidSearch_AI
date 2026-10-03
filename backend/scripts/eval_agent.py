"""Đo agent trên bộ ground truth eval/sotuyen12.json (55 câu SOTUYEN1+2).

    python scripts/eval_agent.py                         # /agent/chat, top_k=100
    python scripts/eval_agent.py --deep                  # ép vòng ReAct mọi câu
    python scripts/eval_agent.py --qa                    # thêm /agent/qa cho câu QA
    python scripts/eval_agent.py --only p2-20,p1-23      # vài câu
    python scripts/eval_agent.py --compare eval/runs/<cũ>.json

Mỗi lần chạy ghi eval/runs/<timestamp>.json (kết quả thô từng câu) để A/B.
Chỉ gọi HTTP tới backend đang chạy - không nạp model, không build gì.

Điểm:
  video@k  : video đúng xuất hiện trong k dòng đầu
  frame@k  : video đúng VÀ |frame - gt| <= frame_tol_s * fps trong k dòng đầu
  qa       : answer chuẩn hoá (bỏ dấu, bỏ "con ", số so bằng float) khớp 1 trong answers
  trake    : video@k theo nhóm temporal; frame = mọi event trong tolerance
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
KS = (1, 5, 20, 100)


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def norm_answer(s: str) -> str:
    s = fold(s)
    s = re.sub(r"^(con|cai|chiec|so|deo)\s+", "", s)
    s = s.replace("‰", "").replace("%", "").replace(",", ".")
    return re.sub(r"\s+", " ", s).strip(" .")


def answer_match(pred: str, answers: list) -> bool:
    p = norm_answer(pred)
    if not p:
        return False
    for a in answers:
        a = norm_answer(a)
        if p == a:
            return True
        try:
            if abs(float(re.sub(r"[^0-9.]", "", p)) - float(re.sub(r"[^0-9.]", "", a))) < 1e-6 \
                    and re.search(r"\d", a):
                return True
        except ValueError:
            pass
        if len(a) >= 3 and (a in p or p in a):
            return True
    return False


def frame_idx(r: dict):
    stem = str(r.get("frame_name", "")).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if stem.isdigit():
        return int(stem)
    if r.get("timestamp_ms") is not None and r.get("fps"):
        return round(r["timestamp_ms"] / 1000 * r["fps"])
    return None


def score_rows(q: dict, rows: list) -> dict:
    """rows: [(video, frame_idx_or_list, fps)] theo thứ tự rank."""
    tol_s = q.get("frame_tol_s", 3)
    vrank = frank = None
    for i, (v, f, fps) in enumerate(rows, 1):
        if v not in q["videos"]:
            continue
        vrank = vrank or i
        gts = q["frames"].get(v) or []
        tol = tol_s * (fps or 25)
        if q["task"] == "trake":
            ok = any(isinstance(f, list) and len(f) == len(g)
                     and all(abs(a - b) <= tol for a, b in zip(f, g)) for g in gts)
        else:
            # planner có thể xếp KIS vào temporal -> f là list frame của chuỗi
            fs = f if isinstance(f, list) else [f]
            ok = any(isinstance(x, int) and abs(x - g) <= tol for x in fs for g in gts)
        if ok and frank is None:
            frank = i
        if vrank and (frank or not gts):
            break
    return {"video_rank": vrank, "frame_rank": frank}


def run_query(client: httpx.Client, base: str, q: dict, args) -> dict:
    t0 = time.time()
    body = {"messages": [{"role": "user", "content": q["query"]}],
            "top_k": args.top_k, "model": args.model, "rerank": not args.no_rerank,
            "deep": args.deep}
    res = client.post(f"{base}/agent/chat", json=body, timeout=args.timeout).json()
    rows, out = [], {"id": q["id"], "task": q["task"], "confidence": q["confidence"]}
    if res.get("videos"):
        for g in res["videos"]:
            ev = g["best_sequence"].get("events") or g["best_sequence"].get("frames") or []
            fr = [frame_idx(e) for e in ev]
            fps = ev[0].get("fps") if ev else 25
            rows.append((g["video_name"], fr, fps))
        out["mode"] = "temporal"
    else:
        for r in res.get("results", []):
            rows.append((r["video_name"], frame_idx(r), r.get("fps")))
        out["mode"] = "search"
    out.update(score_rows(q, rows))
    out["top"] = [(v, f) for v, f, _ in rows[:5]]
    out["react_steps"] = len(res.get("trace") or [])
    out["trace"] = res.get("trace") or []
    out["plan_mode"] = (res.get("plan") or {}).get("mode")
    if q["task"] == "qa" and args.qa:
        qa = client.post(f"{base}/agent/qa", json={"question": q["query"], "model": args.model},
                         timeout=args.timeout).json()
        out["answer"] = qa.get("answer", "")
        out["qa_ok"] = answer_match(out["answer"], q["answers"]) if q["answers"] else None
        fr = [(f["video_name"], frame_idx(f), f.get("fps")) for f in qa.get("frames", [])]
        out["qa_evidence_video_rank"] = score_rows(q, fr)["video_rank"]
    out["sec"] = round(time.time() - t0, 1)
    return out


def summarize(results: list, label: str = "") -> None:
    def at(key, k, rs):
        return sum(1 for r in rs if r.get(key) and r[key] <= k)

    groups = {"all": results}
    for r in results:
        groups.setdefault(r["task"], []).append(r)
        groups.setdefault(f"round{r['id'][1]}", []).append(r)
    print(f"\n== Summary {label}")
    print(f"{'group':8} {'n':>3} " + " ".join(f"vid@{k:<3}" for k in KS) + "  " + " ".join(f"frm@{k:<3}" for k in KS) + "  qa_acc")
    for g, rs in groups.items():
        qa = [r for r in rs if r.get("qa_ok") is not None]
        qa_s = f"{sum(1 for r in qa if r['qa_ok'])}/{len(qa)}" if qa else "-"
        print(f"{g:8} {len(rs):>3} " + " ".join(f"{at('video_rank', k, rs):>6} " for k in KS)
              + "  " + " ".join(f"{at('frame_rank', k, rs):>6} " for k in KS) + f"  {qa_s}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--set", default=str(ROOT / "eval" / "sotuyen12.json"))
    ap.add_argument("--top_k", type=int, default=100)
    ap.add_argument("--model", default="ensemble")
    ap.add_argument("--deep", action="store_true", help="ép vòng ReAct mọi câu")
    ap.add_argument("--qa", action="store_true", help="gọi thêm /agent/qa cho câu QA")
    ap.add_argument("--no_rerank", action="store_true")
    ap.add_argument("--only", default="", help="danh sách id, phẩy: p2-20,p1-23")
    ap.add_argument("--task", default="", help="kis|qa|trake")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--compare", default="", help="file run cũ để in diff")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    data = json.load(open(args.set, encoding="utf-8"))
    qs = data["queries"]
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        qs = [q for q in qs if any(q["id"] == w or q["id"].startswith(w + "-") for w in want)]
    if args.task:
        qs = [q for q in qs if q["task"] == args.task]

    client = httpx.Client()
    results = []
    print(f"{'id':14} {'conf':10} {'vid':>4} {'frm':>4} {'steps':>5} {'sec':>6}  top1 | answer")
    for q in qs:
        try:
            r = run_query(client, args.base, q, args)
        except Exception as e:  # noqa: BLE001 - một câu hỏng không chặn cả bộ
            r = {"id": q["id"], "task": q["task"], "confidence": q["confidence"],
                 "error": str(e)[:200], "video_rank": None, "frame_rank": None}
        results.append(r)
        top1 = r.get("top", [None])[0] if r.get("top") else None
        ans = r.get("answer", "")
        flag = "" if r.get("qa_ok") is None else (" OK" if r["qa_ok"] else " XX")
        print(f"{r['id']:14} {r['confidence']:10} {str(r.get('video_rank')):>4} {str(r.get('frame_rank')):>4} "
              f"{str(r.get('react_steps', '')):>5} {str(r.get('sec', '')):>6}  {top1} | {ans[:40]}{flag}"
              + (f"  ERR {r['error']}" if r.get("error") else ""))
        sys.stdout.flush()

    summarize(results, Path(args.set).name)
    run_dir = ROOT / "eval" / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else run_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    json.dump({"args": vars(args), "results": results}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nsaved {out}")

    if args.compare:
        old = {r["id"]: r for r in json.load(open(args.compare, encoding="utf-8"))["results"]}
        print("\n== Diff vs", args.compare)
        for r in results:
            o = old.get(r["id"])
            if not o:
                continue
            for key in ("video_rank", "frame_rank", "qa_ok"):
                if o.get(key) != r.get(key):
                    print(f"  {r['id']:14} {key}: {o.get(key)} -> {r.get(key)}")
        summarize(list(old.values()), "(old)")


if __name__ == "__main__":
    main()
