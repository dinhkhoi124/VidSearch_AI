"""Step 09 - Merge per-batch FAISS indexes + metadata into the combined set.

The pipeline may be run in batches (e.g. lessons L21-25, then L26, then L27-30),
each batch producing its own files under ``data/indexes`` and ``data/metadata``:

    data/indexes/clip_<batch>.index         + id_map_clip_<batch>.json
    data/indexes/siglip_<batch>.index       + id_map_siglip_<batch>.json
    data/metadata/frames_meta_<batch>.json
    data/ocr/ocr_data_<batch>.json           {frame_id: "text"}
    data/asr/asr_data_<batch>.json           {video_name: [{start_ms,...}]}
    data/objects/objects_data_<batch>.json   {frame_id: {label: score}}
    data/captions/caption_data_<batch>.json  {frame_id: "English caption"}

The backend loads only the merged artifacts:
    data/indexes/<model>.index               + id_map_<model>.json
    data/metadata/frames_meta.json
    data/ocr/ocr_data.json
    data/asr/asr_data.json
    data/objects/objects_data.json
    data/captions/caption_data.json

This step concatenates every discovered batch into those files. Batches are
auto-discovered from ``id_map_clip_*.json``, so re-running after building a new
batch picks it up automatically. Merged files are overwritten.

Usage:
    python 09_merge_batches.py              # default: backend/data
    DATA_DIR=/path/to/data python 09_merge_batches.py
"""
import json
import sys
from pathlib import Path

import faiss

try:
    import config
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config

DATA_DIR = config.DATA_DIR
INDEXES_DIR = config.INDEXES_DIR
METADATA_DIR = config.METADATA_DIR


def discover_batches() -> list[str]:
    """Batch names from id_map_<model>_<batch>.json of ANY model.

    Từng dò riêng id_map_clip_*: ngày clip bị xoá dọn đĩa thì merge mù luôn dù
    các model khác vẫn đủ file batch. Tên model không chứa "_" (clip, siglip512,
    metaclip2...) nên phần sau dấu "_" cuối cùng chính là batch.
    """
    names = {p.stem[len("id_map_"):].rsplit("_", 1)[1]
             for p in INDEXES_DIR.glob("id_map_*_*.json")
             if "_" in p.stem[len("id_map_"):]}
    if not names:
        raise SystemExit(f"[ERROR] no batches found in {INDEXES_DIR} "
                         "(no id_map_<model>_<batch>.json)")
    return sorted(names)


def discover_models(batches: list[str]) -> list[str]:
    """Model names from id_map_<model>_<batch>.json across every batch.

    Dò trên đĩa thay vì gõ cứng danh sách: build thêm index cho backbone mới
    (jina, metaclip2, beit3...) là merge tự nhận, không phải nhớ sửa file này.
    Danh sách gõ cứng từng làm công sức build index nằm không vì không ai nhớ
    đồng bộ — xem backend/routers/catalog.py.
    """
    models: set[str] = set()
    for batch in batches:
        suffix = f"_{batch}.json"
        for p in INDEXES_DIR.glob(f"id_map_*{suffix}"):
            name = p.name[len("id_map_"):-len(suffix)]
            if name:
                models.add(name)
    return sorted(models)


def metadata_file_for(batch: str) -> Path | None:
    """Match frames_meta_<batch>.json, tolerant of case (L21-25 vs l21-25)."""
    lower = batch.lower()
    for p in METADATA_DIR.glob("frames_meta_*.json"):
        if p.name[len("frames_meta_"):-len(".json")].lower() == lower:
            return p
    return None


def load_id_map(model: str, batch: str) -> list[str]:
    with (INDEXES_DIR / f"id_map_{model}_{batch}.json").open() as f:
        return json.load(f)


# {kind: (batch_dir, per-batch file, merged file)} - all are flat {key: value} dicts
DICT_FILES = {
    "ocr": (config.OCR_DIR, "ocr_data_{batch}.json", config.OCR_FILE),
    "asr": (config.ASR_DIR, "asr_data_{batch}.json", config.ASR_FILE),
    "objects": (config.OBJECTS_DATA_FILE.parent, "objects_data_{batch}.json",
                config.OBJECTS_DATA_FILE),
    "captions": (config.CAPTION_DIR, "caption_data_{batch}.json",
                 config.CAPTION_FILE),
}


def merge_dict_file(kind: str, batches: list[str]) -> None:
    src_dir, name_tpl, out_file = DICT_FILES[kind]
    merged: dict = {}
    missing = []
    for batch in batches:
        src = src_dir / name_tpl.format(batch=batch)
        if not src.exists():
            missing.append(batch)
            continue
        with src.open() as f:
            merged.update(json.load(f))
        print(f"  + {name_tpl.format(batch=batch)} -> {len(merged)} keys")
    if missing:
        print(f"  [WARN] no {kind} files for batches {missing} (skipped)")

    if not merged:
        print(f"  [SKIP] no {kind} data to merge")
        return
    src_dir.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f"  [OK] wrote {out_file} ({len(merged)} keys)")


def merge_metadata(batches: list[str]) -> None:
    merged: dict = {}
    missing = []
    for batch in batches:
        src = metadata_file_for(batch)
        if src is None:
            missing.append(batch)
            continue
        with src.open() as f:
            merged.update(json.load(f))
        print(f"  + frames_meta_{batch}: {src} -> {len(merged)} frames")
    if missing:
        print(f"  [WARN] no frames_meta for batches {missing} (skipped)")

    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    out = METADATA_DIR / "frames_meta.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f"  [OK] wrote {out} ({len(merged)} frames)")


def merge_model(model: str, batches: list[str]) -> None:
    dims = {p.name[3:].split("_")[0]: p
            for p in INDEXES_DIR.glob(f"{model}_*.index")}
    first = INDEXES_DIR / f"{model}_{batches[0]}.index"
    first_index = faiss.read_index(str(first))
    dim = first_index.d
    merged = faiss.IndexFlatIP(dim)
    merged.merge_from(first_index)

    merged_ids: list[str] = load_id_map(model, batches[0])
    for batch in batches[1:]:
        sub = faiss.read_index(str(INDEXES_DIR / f"{model}_{batch}.index"))
        if sub.d != dim:
            raise SystemExit(f"[ERROR] {model}_{batch}.index dim {sub.d} != {dim}")
        merged.merge_from(sub)
        merged_ids.extend(load_id_map(model, batch))
        print(f"  + {model}_{batch}: ntotal -> {merged.ntotal}")

    out_index = INDEXES_DIR / f"{model}.index"
    faiss.write_index(merged, str(out_index))
    with (INDEXES_DIR / f"id_map_{model}.json").open("w", encoding="utf-8") as f:
        json.dump(merged_ids, f, ensure_ascii=False)

    if merged.ntotal != len(merged_ids):
        raise SystemExit(f"[ERROR] {model}.index ntotal {merged.ntotal} "
                         f"!= id_map len {len(merged_ids)}")
    print(f"  [OK] wrote {out_index} ({merged.ntotal} vectors, dim={dim}) "
          f"+ id_map_{model}.json ({len(merged_ids)} ids)")


def main() -> None:
    INDEXES_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    batches = discover_batches()
    print(f"[INFO] batches: {batches}")

    print("[INFO] merging frames_meta.json")
    merge_metadata(batches)

    models = discover_models(batches)
    print(f"[INFO] models: {models}")
    for model in models:
        present = [b for b in batches if (INDEXES_DIR / f"{model}_{b}.index").exists()
                   and (INDEXES_DIR / f"id_map_{model}_{b}.json").exists()]
        if not present:
            print(f"[WARN] no {model}_*.index batches - skipping {model}")
            continue
        print(f"[INFO] merging {model} index + id_map")
        merge_model(model, present)

    for kind in DICT_FILES:
        print(f"[INFO] merging {kind}")
        merge_dict_file(kind, batches)

    print("[DONE]")


if __name__ == "__main__":
    main()
