"""Step 09c — OCR + English captions with vLLM + Qwen2.5-VL (local runner).

Local port of ``kaggle/09c_caption-qwen-vllm.ipynb``. Same model, same prompt,
same per-video JSON, so the outputs are drop-in replacements for step 09 / 09b.

Differences from the Kaggle notebook, all because this box is one consumer GPU
instead of two T4s:

* No subprocess sharding. One engine in this process; ``--shard/--num-shards``
  stays available so several processes can split the work if more GPUs appear.
* ``dtype=auto`` (bfloat16 on Ampere+) and CUDA graphs left ON. The notebook
  forces fp16 + ``enforce_eager`` only because sm75 lacks bf16 and trips the
  graph backends. Use ``--eager`` to restore that behaviour.
* Reads keyframes straight from the frontend media tree via config.py.

Three modes, run in this order:

    # 1. generate — resumable, one <video_name>.json per video under --out
    python 09c_caption_qwen_vllm.py

    # 2. merge — collapse per-video files into flat ocr/caption dicts
    python 09c_caption_qwen_vllm.py --merge

    # 3. install — split the merged dicts into the per-batch files that
    #    09_merge_batches.py expects, backing up whatever was there
    python 09c_caption_qwen_vllm.py --install

One pipeline batch at a time, the way the rest of the pipeline is run. Batch
membership comes from data/indexes/id_map_clip_<batch>.json, the same source
09_merge_batches.py discovers batches from:

    python 09c_caption_qwen_vllm.py --batch l26
    python 09c_caption_qwen_vllm.py --batch l21-25
    python 09c_caption_qwen_vllm.py --batch l27-30
    python 09c_caption_qwen_vllm.py --install     # installs finished batches only

All batches share one --out directory: files are named per video, so they never
collide, and --install works out which batch each frame belongs to. A batch that
is only partly processed is reported and skipped rather than written over the
existing full file (--force overrides).

Useful during a first run:

    python 09c_caption_qwen_vllm.py --dry-run             # count work, no model
    python 09c_caption_qwen_vllm.py --limit 2             # smoke test, 2 videos
    python 09c_caption_qwen_vllm.py --videos L21_V001     # prefix filter
    python 09c_caption_qwen_vllm.py --stride 2            # half the frames
"""
import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

try:
    import config
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Keyframes live under the frontend media tree, nested <batch>/<video>/<n>.webp
DEFAULT_KEYFRAMES = config.FRAMES_DIR / "Keyframes"
DEFAULT_OUT = config.DATA_PROCESSING_DIR / "ocr_caption"

# Identical to step 09 so the two can be mixed per video without a format skew.
PROMPT = (
    "You are analyzing one keyframe from a Vietnamese TV broadcast.\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    '{"ocr": "<ALL text visible in the image, verbatim, keep Vietnamese diacritics; '
    '\"\" if none>",\n'
    ' "caption": "<1-2 English sentences describing the visual scene: subjects, '
    "actions, setting. Do not mention the channel logo or timestamps.>\"}\n"
    "No markdown, no explanations, JSON only."
)
# Fallback if the tokenizer ships no usable chat template: the Qwen2.5-VL
# template written out by hand, with exactly one image placeholder.
CHAT_FALLBACK = (
    "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>"
    + PROMPT
    + "<|im_end|>\n<|im_start|>assistant\n"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_argument_group("mode (default: generate)")
    mode.add_argument("--merge", action="store_true",
                      help="merge per-video JSON into ocr_data.json + caption_data.json")
    mode.add_argument("--install", action="store_true",
                      help="split merged dicts into backend per-batch files (implies --merge)")
    mode.add_argument("--dry-run", action="store_true",
                      help="report how many frames are outstanding, load no model")
    mode.add_argument("--force", action="store_true",
                      help="--install: write batches even when partly processed")

    io = p.add_argument_group("paths")
    io.add_argument("--keyframes", type=Path, default=DEFAULT_KEYFRAMES)
    io.add_argument("--out", type=Path, default=DEFAULT_OUT)

    sel = p.add_argument_group("selection")
    sel.add_argument("--stride", type=int, default=1,
                     help="keep every Nth keyframe (1 = all)")
    sel.add_argument("--batch", default="",
                     help="comma-separated pipeline batches, e.g. l21-25,l26. "
                          "Membership comes from id_map_clip_<batch>.json, so it "
                          "matches what 09_merge_batches.py will merge.")
    sel.add_argument("--videos", default="",
                     help="comma-separated video-name prefixes, e.g. L21,L26_V004")
    sel.add_argument("--limit", type=int, default=0,
                     help="stop after N videos (0 = no limit)")
    sel.add_argument("--shard", type=int, default=0)
    sel.add_argument("--num-shards", type=int, default=1)

    eng = p.add_argument_group("engine")
    eng.add_argument("--model", default="Qwen/Qwen2.5-VL-3B-Instruct")
    eng.add_argument("--chunk", type=int, default=128,
                     help="requests handed to the engine at once (vLLM batches internally)")
    eng.add_argument("--max-pixels", type=int, default=640,
                     help="vision-token ceiling per image, in 28x28 patches. "
                          "640 patches is about a 900x560 image. Main cost knob.")
    eng.add_argument("--min-pixels", type=int, default=256)
    # The notebook says 4096; one request actually uses ~950 tokens (about 640
    # image tokens at --max-pixels 640, ~120 of prompt, 220 of output). On 12 GiB
    # the slack is not free: it is KV cache the engine reserves and cannot use.
    eng.add_argument("--max-model-len", type=int, default=2048)
    # 220 (the notebook's value) truncates any frame showing a document or a
    # full-screen text slide. salvage_field() rescues those, but a higher ceiling
    # is cheap: it only costs decode time on the replies that actually need it.
    eng.add_argument("--max-tokens", type=int, default=512)
    eng.add_argument("--repetition-penalty", type=float, default=1.05,
                     help="breaks the greedy-decode loops that otherwise burn the "
                          "whole token budget on one repeated unit. Keep it mild: "
                          "broadcast OCR legitimately repeats (tickers, logos).")
    # The notebook uses 0.90 because a Kaggle T4 is empty and dedicated. This box
    # runs a desktop (and sometimes the backend), so 0.90 of total is usually more
    # than what is actually free and vLLM refuses to start. clamp_gpu_mem() lowers
    # this further if the GPU is busier still.
    eng.add_argument("--gpu-mem", type=float, default=0.80)
    eng.add_argument("--vram-headroom", type=float, default=1.0,
                     help="GiB left outside the vLLM budget for vision-encoder "
                          "activations (they are NOT covered by --gpu-mem)")
    eng.add_argument("--max-num-seqs", type=int, default=32,
                     help="concurrent sequences. Caps how many images the vision "
                          "encoder holds at once, i.e. the activation spike.")
    eng.add_argument("--dtype", default="auto",
                     help="auto picks bfloat16 on Ampere+; use 'half' on sm75")
    eng.add_argument("--eager", action="store_true",
                     help="disable CUDA graphs (needed on sm75, slower elsewhere)")
    return p.parse_args()


# --- work discovery ----------------------------------------------------------

def lesson_prefixes(batches: set[str]) -> tuple[str, ...]:
    """'l21-25' / 'l26' -> video-name prefixes ('L21_', ..., 'L25_')."""
    prefixes = []
    for b in batches:
        m = re.fullmatch(r"[lL](\d+)(?:-(\d+))?", b.strip())
        if not m:
            raise SystemExit(f"[ERROR] cannot read '{b}' as a lesson range "
                             "(expected like l26 or l21-25)")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        prefixes += [f"L{n}_" for n in range(lo, hi + 1)]
    return tuple(prefixes)


def list_videos(args: argparse.Namespace) -> list[Path]:
    """Video directories under <keyframes>/<batch>/<video_name>/, sharded."""
    if not args.keyframes.is_dir():
        raise SystemExit(f"[ERROR] keyframes dir not found: {args.keyframes}")
    dirs = sorted(d for d in args.keyframes.glob("*/*") if d.is_dir())
    if not dirs:
        raise SystemExit(f"[ERROR] no <batch>/<video> dirs under {args.keyframes}")
    if args.batch:
        wanted = {b.strip() for b in args.batch.split(",") if b.strip()}
        v2b = batch_of_video(required=False)
        if v2b:
            known = sorted(set(v2b.values()))
            unknown = wanted - set(known)
            if unknown:
                raise SystemExit(f"[ERROR] unknown batch {sorted(unknown)}; have {known}")
            dirs = [d for d in dirs if v2b.get(d.name) in wanted]
        else:
            # A machine that only runs captioning has no FAISS indexes, so the
            # id_map files that define batch membership are absent. Fall back to
            # the lesson range the batch name spells out ("l21-25" -> L21..L25).
            print(f"[WARN] no id_map_clip_*.json in {config.INDEXES_DIR}; "
                  "reading the batch name as a lesson range")
            dirs = [d for d in dirs if d.name.startswith(lesson_prefixes(wanted))]
        if not dirs:
            raise SystemExit(f"[ERROR] no keyframe dirs for batch {sorted(wanted)}")
    if args.videos:
        prefixes = tuple(v.strip() for v in args.videos.split(",") if v.strip())
        dirs = [d for d in dirs if d.name.startswith(prefixes)]
    dirs = [d for i, d in enumerate(dirs) if i % args.num_shards == args.shard]
    if args.limit:
        dirs = dirs[: args.limit]
    return dirs


def outstanding(video_dir: Path, out_dir: Path, stride: int):
    """(already-done dict, [(frame_id, path), ...] still to do) for one video."""
    out_path = out_dir / f"{video_dir.name}.json"
    done = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    frames = sorted(p for p in video_dir.iterdir()
                    if p.suffix.lower() in IMAGE_EXTS)[::stride]
    todo = [(f"{video_dir.name}_{p.stem}", p) for p in frames
            if f"{video_dir.name}_{p.stem}" not in done]
    return out_path, done, todo


# --- generation --------------------------------------------------------------

def strip_loop(s: str) -> str:
    """Cut a degenerate repeated tail, keeping one copy of the unit.

    Greedy decoding (temperature=0) latches onto a short unit on some frames and
    emits it until it runs out of budget: "119 119 119 ..." off a jersey number,
    "MEDI\\nMEDI\\n..." off a banner. Raising --max-tokens does not help, it just
    buys more of the same. The notebook never saw this because a looped reply is
    unparseable and it discarded the frame; salvage_field() recovers the text, so
    the loop has to be removed here or it lands in the OCR text index.
    """
    m = re.search(r"(.{1,40}?)\1{3,}\s*$", s, flags=re.DOTALL)
    return (s[:m.start()] + m.group(1)).strip() if m else s


def salvage_field(text: str, key: str) -> str:
    """Read one JSON string field out of a reply that will not parse.

    A frame holding a full page of text (a contract, a document held to camera)
    makes the model emit OCR past --max-tokens, and the JSON arrives with no
    closing quote or brace. The notebook returns blank for both fields there,
    which loses exactly the text-dense frames OCR search exists to find. Walk
    the field by hand instead, accepting an unterminated tail.
    """
    m = re.search(rf'"{key}"\s*:\s*"', text)
    if not m:
        return ""
    body, out, i = text[m.end():], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):   # keep escapes intact for json below
            out.append(body[i:i + 2])
            i += 2
            continue
        if c == '"':                          # unescaped quote closes the field
            break
        out.append(c)
        i += 1
    raw = "".join(out)
    try:
        return json.loads(f'"{raw}"').strip()
    except ValueError:                        # trailing half-escape, take it raw
        return raw.strip()


def parse_reply(text: str) -> dict:
    """Pull ocr/caption out of the model reply; never raise, never blank both."""
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            return {"ocr": strip_loop(str(d.get("ocr", "")).strip()),
                    "caption": strip_loop(str(d.get("caption", "")).strip())}
        except ValueError:
            pass
    return {"ocr": strip_loop(salvage_field(text, "ocr")),
            "caption": strip_loop(salvage_field(text, "caption"))}


def build_chat_prompt(llm) -> str:
    """Prefer the tokenizer's own chat template; fall back to the literal one.

    Hand-writing the template breaks silently on a model whose special tokens
    differ (Qwen3-VL, a finetune), and a wrong template shows up as plausible
    but wrong captions rather than an error. Ask the tokenizer first.
    """
    try:
        tok = llm.get_tokenizer()
        chat = tok.apply_chat_template(
            [{"role": "user", "content": [{"type": "image"},
                                          {"type": "text", "text": PROMPT}]}],
            tokenize=False, add_generation_prompt=True)
        if "image_pad" in chat or "<image>" in chat:
            return chat
        print("[WARN] chat template has no image placeholder, using fallback")
    except Exception as e:  # noqa: BLE001 - any template failure falls back
        print(f"[WARN] apply_chat_template failed ({type(e).__name__}), using fallback")
    return CHAT_FALLBACK


def clamp_gpu_mem(requested: float, headroom_gib: float) -> float:
    """Shrink gpu_memory_utilization to fit free VRAM, minus vision headroom.

    Two traps, both invisible on a 15 GiB Kaggle T4 and both fatal on a 12 GiB
    desktop card:

    * vLLM compares the fraction against FREE memory, not total, and refuses to
      start when it does not fit. The free share moves run to run here (desktop,
      sometimes the backend), so read it instead of assuming.
    * The fraction budgets weights + KV cache ONLY. Vision-encoder activations
      are allocated on top of it. Give the engine everything free and the ViT
      OOMs mid-run, which kills the engine rather than just one request. Reserve
      `headroom_gib` for it; the spike scales with --max-pixels and --max-num-seqs.
    """
    try:
        import torch
        free, total = torch.cuda.mem_get_info()
    except Exception:  # noqa: BLE001 - no CUDA, no clamp; let vLLM report it
        return requested
    usable = (free - headroom_gib * 2**30) / total
    if usable <= 0:
        raise SystemExit(
            f"[ERROR] only {free / 2**30:.1f} GiB free on the GPU, less than the "
            f"{headroom_gib:.1f} GiB vision headroom. Free VRAM (is the backend "
            "running?) or lower --vram-headroom.")
    if requested <= usable:
        return requested
    print(f"[WARN] --gpu-mem {requested:.2f} leaves no room for the vision encoder "
          f"({free / 2**30:.1f}/{total / 2**30:.1f} GiB free, keeping "
          f"{headroom_gib:.1f} GiB); using {usable:.2f}")
    return round(usable, 2)


def generate(args: argparse.Namespace) -> None:
    from PIL import Image
    from vllm import LLM, SamplingParams

    video_dirs = list_videos(args)
    args.out.mkdir(parents=True, exist_ok=True)

    total_todo = sum(len(outstanding(d, args.out, args.stride)[2]) for d in video_dirs)
    print(f"[INFO] {len(video_dirs)} videos | {total_todo} frames outstanding "
          f"| stride={args.stride}")
    if args.dry_run:
        return
    if not total_todo:
        print("[DONE] nothing to do")
        return

    llm = LLM(
        model=args.model,
        dtype=args.dtype,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=clamp_gpu_mem(args.gpu_mem, args.vram_headroom),
        max_num_seqs=args.max_num_seqs,
        enforce_eager=args.eager,
        limit_mm_per_prompt={"image": 1},
        mm_processor_kwargs={"min_pixels": args.min_pixels * 28 * 28,
                             "max_pixels": args.max_pixels * 28 * 28},
    )
    chat = build_chat_prompt(llm)
    sampling = SamplingParams(temperature=0.0, max_tokens=args.max_tokens,
                              repetition_penalty=args.repetition_penalty)
    print(f"[INFO] engine ready | model={args.model}")

    t0, n_done, n_cut = time.time(), 0, 0
    for vi, video_dir in enumerate(video_dirs, 1):
        out_path, done, todo = outstanding(video_dir, args.out, args.stride)
        for b in range(0, len(todo), args.chunk):
            batch = todo[b:b + args.chunk]
            reqs = [{"prompt": chat,
                     "multi_modal_data": {"image": Image.open(p).convert("RGB")}}
                    for _, p in batch]
            try:
                outs = llm.generate(reqs, sampling, use_tqdm=False)
                for (frame_id, _), o in zip(batch, outs):
                    done[frame_id] = parse_reply(o.outputs[0].text)
                    if o.outputs[0].finish_reason == "length":
                        n_cut += 1
            except Exception as e:  # noqa: BLE001 - one bad chunk must not kill the run
                # ...but a dead engine or an OOM is not a bad chunk: every later
                # chunk fails the same way, and blanking them out would write
                # empty OCR over the whole run and still exit 0. Stop instead,
                # leaving the frames unwritten so a re-run picks them up.
                if type(e).__name__ in ("EngineDeadError", "OutOfMemoryError"):
                    out_path.write_text(json.dumps(done, ensure_ascii=False),
                                        encoding="utf-8")
                    raise SystemExit(
                        f"[FATAL] engine died on {video_dir.name}: "
                        f"{type(e).__name__}: {e}\n"
                        "Lower --max-num-seqs or --max-pixels, or raise "
                        "--vram-headroom, then re-run to resume.") from e
                print(f"[WARN] {video_dir.name}: {type(e).__name__}: {e}", flush=True)
                for frame_id, _ in batch:
                    done.setdefault(frame_id, {"ocr": "", "caption": ""})
            # Flush per chunk, not per video: a video can hold 1000+ frames and
            # a crash between writes would redo all of them.
            out_path.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        n_done += len(todo)
        elapsed = time.time() - t0
        rate = n_done / max(elapsed, 1e-9)
        eta_h = (total_todo - n_done) / max(rate, 1e-9) / 3600
        print(f"[{vi}/{len(video_dirs)}] {video_dir.name}: +{len(todo)} frames | "
              f"{n_done}/{total_todo} | {rate:.1f} f/s | ETA {eta_h:.1f} h", flush=True)

    print(f"[DONE] {n_done} frames in {(time.time() - t0) / 3600:.2f} h")
    if n_cut:
        print(f"[INFO] {n_cut} replies hit --max-tokens ({args.max_tokens}) and were "
              "salvaged mid-string; raise it if that share looks large")


# --- merge / install ---------------------------------------------------------

def merge(args: argparse.Namespace) -> tuple[dict, dict, set[str]]:
    """Per-video JSON -> ({frame_id: ocr}, {frame_id: caption}, processed ids).

    The two dicts hold only non-empty values, so their size says nothing about
    how much was processed. The id set does, and install() needs that to tell a
    finished batch from a half-finished one.
    """
    ocr, cap, seen = {}, {}, set()
    files = sorted(p for p in args.out.glob("*.json")
                   if p.name not in ("ocr_data.json", "caption_data.json"))
    if not files:
        raise SystemExit(f"[ERROR] no per-video JSON in {args.out} — run generation first")
    for f in files:
        for frame_id, d in json.loads(f.read_text(encoding="utf-8")).items():
            seen.add(frame_id)
            if d.get("ocr"):
                ocr[frame_id] = d["ocr"]
            if d.get("caption"):
                cap[frame_id] = d["caption"]
    (args.out / "ocr_data.json").write_text(json.dumps(ocr, ensure_ascii=False),
                                            encoding="utf-8")
    (args.out / "caption_data.json").write_text(json.dumps(cap, ensure_ascii=False),
                                                encoding="utf-8")
    print(f"[OK] {len(files)} videos, {len(seen)} frames -> ocr_data.json {len(ocr)} | "
          f"caption_data.json {len(cap)}  (in {args.out})")
    return ocr, cap, seen


def batch_of_video(required: bool = True) -> dict[str, str]:
    """{video_name: batch} from id_map_<model>_<batch>.json of ANY model.

    Same source 09_merge_batches.py discovers batches from, so the per-batch
    files this writes land exactly where that script expects them. Không ghim
    vào một model cụ thể: bộ clip từng bị xoá dọn đĩa (26/8) làm mọi script dò
    id_map_clip_* mù hết — model nào còn file thì dùng, nội dung id_map giống
    nhau giữa các model. Empty (with required=False) on a machine that has no
    indexes; --install always requires it because without it there is no batch
    layout to install into.
    """
    mapping: dict[str, str] = {}
    for p in sorted(config.INDEXES_DIR.glob("id_map_*_*.json")):
        rest = p.stem[len("id_map_"):]
        if "_" not in rest:
            continue
        batch = rest.rsplit("_", 1)[1]
        for frame_id in json.loads(p.read_text(encoding="utf-8")):
            mapping[frame_id.rsplit("_", 1)[0]] = batch
    if not mapping and required:
        raise SystemExit(f"[ERROR] no id_map_<model>_<batch>.json in {config.INDEXES_DIR}")
    return mapping


def write_per_batch(kind: str, data: dict, out_dir: Path, name_tpl: str,
                    allowed: set[str]) -> None:
    """Split {frame_id: value} into <name_tpl>.format(batch=...) files.

    Only batches in `allowed` are written — see complete_batches().
    """
    v2b = batch_of_video()
    split: dict[str, dict] = {}
    unassigned = 0
    for frame_id, value in data.items():
        batch = v2b.get(frame_id.rsplit("_", 1)[0])
        if batch is None:
            unassigned += 1
            continue
        if batch not in allowed:
            continue
        split.setdefault(batch, {})[frame_id] = value
    if unassigned:
        print(f"  [WARN] {unassigned} {kind} frames belong to no known batch (skipped)")

    out_dir.mkdir(parents=True, exist_ok=True)
    for batch, part in sorted(split.items()):
        dst = out_dir / name_tpl.format(batch=batch)
        if dst.exists():
            # These currently hold EasyOCR / Florence output. Keep one copy —
            # regenerating them costs GPU-hours.
            bak = dst.with_suffix(dst.suffix + ".bak")
            if not bak.exists():
                shutil.copy2(dst, bak)
                print(f"  backed up {dst.name} -> {bak.name}")
        dst.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
        print(f"  [OK] {dst} ({len(part)} keys)")


def complete_batches(seen: set[str], force: bool) -> set[str]:
    """Batches this run covered end to end, per id_map_siglip_<batch>.json.

    Installing a half-finished batch would replace the full existing OCR for
    those lessons with a partial file, and 09_merge_batches.py would then bake
    the hole into ocr_data.json. Since the run is resumable, the right answer to
    an incomplete batch is to finish it, not to install it. --force overrides.
    """
    allowed, report = set(), []
    for p in sorted(config.INDEXES_DIR.glob("id_map_siglip_*.json")):
        batch = p.name[len("id_map_siglip_"):-len(".json")]
        ids = set(json.loads(p.read_text(encoding="utf-8")))
        have = len(ids & seen)
        if not have:
            continue
        pct = have / len(ids)
        report.append(f"  {batch}: {have}/{len(ids)} frames ({pct:.1%})")
        if have == len(ids) or force:
            allowed.add(batch)
    print("[INFO] coverage")
    print("\n".join(report) if report else "  (nothing matches a known batch)")
    skipped = {b for b in (r.split(":")[0].strip() for r in report)} - allowed
    if skipped:
        print(f"[WARN] incomplete, NOT installing: {sorted(skipped)}\n"
              "       re-run generation to finish them, or pass --force")
    if not allowed:
        raise SystemExit("[ERROR] no complete batch to install")
    return allowed


def install(args: argparse.Namespace) -> None:
    ocr, cap, seen = merge(args)
    allowed = complete_batches(seen, args.force)
    print(f"[INFO] installing batches: {sorted(allowed)}")
    print("[INFO] writing per-batch ocr files")
    write_per_batch("ocr", ocr, config.OCR_DIR, "ocr_data_{batch}.json", allowed)
    print("[INFO] writing per-batch caption files")
    write_per_batch("caption", cap, config.CAPTION_DIR, "caption_data_{batch}.json",
                    allowed)
    print("\nNext:\n"
          "  python 09_merge_batches.py      # rebuild ocr_data.json + caption_data.json\n"
          "  python 07_build_text_indexes.py # OCR/caption text changed -> reindex\n"
          "  python 08_build_graph.py        # scene.ocr comes from the new OCR")


def main() -> None:
    args = parse_args()
    if args.install:
        install(args)
    elif args.merge:
        merge(args)
    else:
        generate(args)


if __name__ == "__main__":
    main()
