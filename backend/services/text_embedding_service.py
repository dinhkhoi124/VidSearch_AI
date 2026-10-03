"""Sentence-embedding service for semantic OCR/ASR text search.

Separate from `embedding_service` (which is the CLIP/SigLIP image-text backbone for
visual search). Here we encode *plain text* into a monolingual/multilingual sentence
space so OCR transcripts and ASR captions can be matched by meaning, not just by
exact substring.

Backbone: `settings.text_embed_model` (default intfloat/multilingual-e5-base, 768-d).
E5 models require an instruction prefix - "query: " for the search query and
"passage: " for the indexed documents - so the two encode helpers add it for you.

Loaded lazily via sentence-transformers. If the library/weights are unavailable the
service returns None and callers fall back to exact substring search (so the API keeps
working without the model, e.g. before the index is built).

Device is shared with the visual encoder via env EMBED_DEVICE = auto | cuda | cpu.
"""
from __future__ import annotations

import threading
from typing import List, Optional

import numpy as np

from config import get_settings

settings = get_settings()

# Lazy singleton: the SentenceTransformer model, or None once we know it's unavailable.
_model: Optional[object] = None
_tried = False
_lock = threading.Lock()


def _resolve_device() -> str:
    pref = (settings.embed_device or "auto").lower()
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False
    if pref == "cpu":
        return "cpu"
    if pref == "cuda":
        return "cuda" if has_cuda else "cpu"
    return "cuda" if has_cuda else "cpu"  # auto


def _get():
    """Return the SentenceTransformer, or None if it cannot be loaded (-> exact only)."""
    global _model, _tried
    if _tried:
        return _model
    with _lock:
        if _tried:
            return _model
        _tried = True
        name = (settings.text_embed_model or "").strip()
        if name.lower() in ("", "none", "off", "disabled", "false", "0"):
            # Explicitly disabled (e.g. GPU short on VRAM) -> use fuzzy/exact fallback.
            print("[text-embed] disabled via TEXT_EMBED_MODEL; OCR/ASR use fallback")
            _model = None
            return _model
        try:
            from sentence_transformers import SentenceTransformer

            device = _resolve_device()
            _model = SentenceTransformer(name, device=device)
            print(f"[text-embed] loaded {name} on {device}")
        except Exception as e:  # noqa: BLE001 - any failure -> graceful fallback
            print(f"[text-embed] unavailable ({e!r}); OCR/ASR fall back to exact match")
            _model = None
        return _model


def is_available() -> bool:
    return _get() is not None


def _encode(texts: List[str], prefix: str) -> Optional[np.ndarray]:
    model = _get()
    if model is None:
        return None
    prefixed = [f"{prefix}{t}" for t in texts]
    emb = model.encode(
        prefixed,
        normalize_embeddings=True,      # L2-normed -> inner product == cosine
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return np.asarray(emb, dtype=np.float32)


def encode_query(text: str) -> Optional[np.ndarray]:
    """Encode a search query -> unit vector (dim,), or None if model unavailable."""
    out = _encode([text], prefix="query: ")
    return None if out is None else out[0]


def encode_passages(texts: List[str]) -> Optional[np.ndarray]:
    """Encode indexed documents -> (N, dim) unit vectors, or None if unavailable."""
    return _encode(texts, prefix="passage: ")
