"""Step 07 - Build semantic text indexes for hybrid OCR/ASR search.

New for the hybrid (semantic + exact) OCR/ASR search. Embeds the OCR and ASR text
with a sentence model (E5) and writes FAISS indexes the backend loads at query time:

    data/indexes/ocr_text.index      IndexFlatIP over OCR-frame embeddings
    data/indexes/ocr_text_ids.json   ["<frame_id>", ...]            (row-aligned)
    data/indexes/asr_text.index      IndexFlatIP over ASR-segment embeddings
    data/indexes/asr_text_meta.json  [{video_name,seg_idx,start_ms,end_ms,text}, ...]

Inputs : data/ocr/ocr_data.json (from step 04), data/asr/asr_data.json (from step 05).
The embedding model MUST match the backend's settings.text_embed_model, and E5 needs
a "passage: " prefix on indexed documents (the backend adds "query: " at search time).

Run after steps 04/05:
    python 07_build_text_indexes.py
"""
import json
from typing import List, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

import config


def _load_json(path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _encode_passages(model: SentenceTransformer, texts: List[str]) -> np.ndarray:
    """E5 passage embeddings -> (N, dim) float32, L2-normalised (cosine via IP)."""
    emb = model.encode(
        [f"passage: {t}" for t in texts],
        batch_size=config.TEXT_EMBED_BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    return np.asarray(emb, dtype=np.float32)


def _write_index(matrix: np.ndarray, index_path) -> None:
    faiss.normalize_L2(matrix)  # belt-and-braces: ensure unit norm
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)
    faiss.write_index(index, str(index_path))
    print(f"[INFO] Wrote {index_path} ({index.ntotal} vectors, dim={matrix.shape[1]})")


def build_ocr(model: SentenceTransformer) -> None:
    ocr = _load_json(config.OCR_FILE)
    ids, texts = [], []
    for frame_id, text in ocr.items():
        if text and text.strip():
            ids.append(frame_id)
            texts.append(text.strip())
    if not texts:
        print(f"[WARN] No OCR text in {config.OCR_FILE}; skipping OCR index.")
        return
    print(f"[INFO] OCR: embedding {len(texts)} frames")
    _write_index(_encode_passages(model, texts), config.OCR_TEXT_INDEX_FILE)
    with config.OCR_TEXT_IDS_FILE.open("w", encoding="utf-8") as f:
        json.dump(ids, f, ensure_ascii=False)
    print(f"[INFO] Wrote {config.OCR_TEXT_IDS_FILE} ({len(ids)} ids)")


def build_asr(model: SentenceTransformer) -> None:
    asr = _load_json(config.ASR_FILE)
    meta: List[dict] = []
    texts: List[str] = []
    for video_name, segs in asr.items():
        for i, seg in enumerate(segs):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            meta.append(
                {
                    "video_name": video_name,
                    "seg_idx": i,
                    "start_ms": seg.get("start_ms", 0),
                    "end_ms": seg.get("end_ms", 0),
                    "text": text,
                }
            )
            texts.append(text)
    if not texts:
        print(f"[WARN] No ASR text in {config.ASR_FILE}; skipping ASR index.")
        return
    print(f"[INFO] ASR: embedding {len(texts)} segments")
    _write_index(_encode_passages(model, texts), config.ASR_TEXT_INDEX_FILE)
    with config.ASR_TEXT_META_FILE.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"[INFO] Wrote {config.ASR_TEXT_META_FILE} ({len(meta)} segments)")


def build_captions(model: SentenceTransformer) -> None:
    """Caption index (kaggle step 9, Qwen2.5-VL). File thiếu -> bỏ qua êm."""
    if not config.CAPTION_FILE.exists():
        print(f"[INFO] No {config.CAPTION_FILE}; skipping caption index.")
        return
    captions = _load_json(config.CAPTION_FILE)
    ids, texts = [], []
    for frame_id, text in captions.items():
        if text and text.strip():
            ids.append(frame_id)
            texts.append(text.strip())
    if not texts:
        print(f"[WARN] No caption text in {config.CAPTION_FILE}; skipping.")
        return
    print(f"[INFO] Captions: embedding {len(texts)} frames")
    _write_index(_encode_passages(model, texts), config.CAPTION_TEXT_INDEX_FILE)
    with config.CAPTION_TEXT_IDS_FILE.open("w", encoding="utf-8") as f:
        json.dump(ids, f, ensure_ascii=False)
    print(f"[INFO] Wrote {config.CAPTION_TEXT_IDS_FILE} ({len(ids)} ids)")


def main() -> None:
    config.ensure_dirs()
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] Loading text model '{config.TEXT_EMBED_MODEL}' on {device}")
    model = SentenceTransformer(config.TEXT_EMBED_MODEL, device=device)

    build_ocr(model)
    build_asr(model)
    build_captions(model)


if __name__ == "__main__":
    main()
