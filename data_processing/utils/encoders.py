"""Pluggable image/text encoders for the retrieval pipeline.

One small interface, four backbones - pick via ``config.MODEL_KEY``:

    enc = get_encoder()                      # uses config.MODEL_KEY
    img_vecs = enc.encode_image([pil, ...])  # -> (N, dim) float32, L2-normalised
    txt_vecs = enc.encode_text(["a cat"])    # same space as images (cosine-ready)

Image and text embeddings live in the SAME space for every encoder, so cosine /
inner-product search works directly. The backend must encode text queries with
the matching encoder - these classes are import-safe to reuse there too.

Heavy deps (torch, transformers, timm) are imported lazily inside each encoder so
importing this module is cheap and only the selected model's deps are required.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
from PIL import Image

import config


def _l2(x: np.ndarray) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)


class BaseEncoder:
    dim: int = 0

    def encode_image(self, images: List[Image.Image]) -> np.ndarray:  # (N, dim)
        raise NotImplementedError

    def encode_text(self, texts: List[str]) -> np.ndarray:            # (N, dim)
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# OpenAI CLIP (English) - openai/clip-vit-large-patch14-336
# --------------------------------------------------------------------------- #
class ClipEncoder(BaseEncoder):
    def __init__(self, hf_name: str, dim: int, device: str):
        import torch
        from transformers import AutoProcessor, CLIPModel

        self.torch = torch
        self.device = device
        self.dim = dim
        self.processor = AutoProcessor.from_pretrained(hf_name)
        self.model = CLIPModel.from_pretrained(hf_name).to(device).eval()

    def encode_image(self, images):
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            emb = self.model.get_image_features(**inputs)
        return _l2(emb.cpu().numpy().astype(np.float32))

    def encode_text(self, texts):
        inputs = self.processor(
            text=texts, return_tensors="pt", padding=True, truncation=True
        ).to(self.device)
        with self.torch.no_grad():
            emb = self.model.get_text_features(**inputs)
        return _l2(emb.cpu().numpy().astype(np.float32))


# --------------------------------------------------------------------------- #
# SigLIP 2 (multilingual) - google/siglip2-so400m-patch14-384
# --------------------------------------------------------------------------- #
class SiglipEncoder(BaseEncoder):
    def __init__(self, hf_name: str, dim: int, device: str):
        import torch
        from transformers import AutoModel, AutoProcessor

        self.torch = torch
        self.device = device
        self.dim = dim
        self.processor = AutoProcessor.from_pretrained(hf_name)
        self.model = AutoModel.from_pretrained(hf_name).to(device).eval()

    def encode_image(self, images):
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            emb = self.model.get_image_features(**inputs)
        return _l2(emb.cpu().numpy().astype(np.float32))

    def encode_text(self, texts):
        # SigLIP was trained with fixed-length padding.
        inputs = self.processor(
            text=texts, return_tensors="pt", padding="max_length", truncation=True
        ).to(self.device)
        with self.torch.no_grad():
            emb = self.model.get_text_features(**inputs)
        return _l2(emb.cpu().numpy().astype(np.float32))


# --------------------------------------------------------------------------- #
# Jina-CLIP v2 (multilingual incl. Vietnamese) - jinaai/jina-clip-v2
# --------------------------------------------------------------------------- #
class JinaClipEncoder(BaseEncoder):
    def __init__(self, hf_name: str, dim: int, device: str):
        from transformers import AutoModel

        self.device = device
        self.dim = dim
        # Jina ships custom code; trust_remote_code is required.
        self.model = AutoModel.from_pretrained(hf_name, trust_remote_code=True).to(device).eval()

    def encode_image(self, images):
        emb = self.model.encode_image(images, normalize_embeddings=True)
        return _l2(np.asarray(emb, dtype=np.float32))

    def encode_text(self, texts):
        # 'retrieval.query' is the task head meant for search queries.
        emb = self.model.encode_text(texts, task="retrieval.query", normalize_embeddings=True)
        return _l2(np.asarray(emb, dtype=np.float32))


# --------------------------------------------------------------------------- #
# BEiT-3 large retrieval - microsoft/unilm (needs extra setup, see README)
# --------------------------------------------------------------------------- #
class Beit3Encoder(BaseEncoder):
    MAX_TEXT_LEN = 64

    def __init__(self, hf_name: str, dim: int, device: str):
        import os
        import sys

        import torch
        from torchvision import transforms

        if not os.path.isdir(config.BEIT3_REPO_DIR):
            raise FileNotFoundError(
                f"BEiT-3 code not found at {config.BEIT3_REPO_DIR}. "
                "Clone https://github.com/microsoft/unilm and set BEIT3_REPO_DIR "
                "to its beit3/ folder (see README)."
            )
        sys.path.insert(0, config.BEIT3_REPO_DIR)
        import modeling_finetune  # noqa: F401 - registers the timm models
        import timm
        from transformers import XLMRobertaTokenizer

        self.torch = torch
        self.device = device
        self.dim = dim

        self.model = timm.create_model(hf_name)
        ckpt = torch.load(config.BEIT3_CKPT, map_location="cpu")
        self.model.load_state_dict(ckpt.get("model", ckpt), strict=False)
        self.model.to(device).eval()

        self.tokenizer = XLMRobertaTokenizer(config.BEIT3_SPM)
        # BEiT-3 uses inception-style (0.5, 0.5, 0.5) normalisation at 384².
        self.transform = transforms.Compose([
            transforms.Resize((384, 384), interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
        ])

    def encode_image(self, images):
        batch = self.torch.stack([self.transform(im.convert("RGB")) for im in images]).to(self.device)
        with self.torch.no_grad():
            vision_cls, _ = self.model(image=batch, only_infer=True)
        return _l2(vision_cls.cpu().numpy().astype(np.float32))

    def encode_text(self, texts):
        enc = self.tokenizer(
            texts, max_length=self.MAX_TEXT_LEN, padding="max_length",
            truncation=True, return_tensors="pt",
        )
        tokens = enc.input_ids.to(self.device)
        padding_mask = (1 - enc.attention_mask).to(self.device)  # 1 = padded
        with self.torch.no_grad():
            _, language_cls = self.model(
                text_description=tokens, padding_mask=padding_mask, only_infer=True
            )
        return _l2(language_cls.cpu().numpy().astype(np.float32))


_KINDS = {
    "clip": ClipEncoder,
    "siglip": SiglipEncoder,
    "jina": JinaClipEncoder,
    "beit3": Beit3Encoder,
}


def get_encoder(model_key: Optional[str] = None, device: Optional[str] = None) -> BaseEncoder:
    """Instantiate the encoder selected by ``model_key`` (default config.MODEL_KEY)."""
    import torch

    key = model_key or config.MODEL_KEY
    spec = config.MODEL_REGISTRY.get(key)
    if spec is None:
        raise ValueError(f"Unknown model key {key!r}; choose from {list(config.MODEL_REGISTRY)}")

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[INFO] Loading encoder '{key}' ({spec['kind']}: {spec['hf_name']}) on {device}")
    return _KINDS[spec["kind"]](spec["hf_name"], spec["dim"], device)
