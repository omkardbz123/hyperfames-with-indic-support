"""SigLIP 2 image/text embeddings (google/siglip2-base-patch16-224, Apache-2.0), CPU.

Shared by tools/index_footage.py and tools/search_footage.py. Embeddings are L2-normalised
float16; similarity is a dot product. The model downloads once into cache/huggingface (~1.5 GB).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.model_cache_env()

MODEL = "google/siglip2-base-patch16-224"
_cache: dict = {}


def load():
    if "m" not in _cache:
        import torch
        from transformers import AutoModel, AutoProcessor
        torch.set_num_threads(max(1, torch.get_num_threads()))
        _cache["m"] = AutoModel.from_pretrained(MODEL).eval()
        _cache["p"] = AutoProcessor.from_pretrained(MODEL)
    return _cache["m"], _cache["p"]


def _norm(x) -> np.ndarray:
    x = getattr(x, "pooler_output", x)
    x = x.float().numpy()
    return (x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)).astype(np.float16)


def embed_images(images: list, batch: int = 16) -> np.ndarray:
    """images: list of HxWx3 uint8 RGB arrays or PIL images."""
    import torch
    from PIL import Image
    m, p = load()
    out = []
    for i in range(0, len(images), batch):
        ims = [im if isinstance(im, Image.Image) else Image.fromarray(im) for im in images[i:i + batch]]
        with torch.no_grad():
            out.append(_norm(m.get_image_features(**p(images=ims, return_tensors="pt"))))
    return np.concatenate(out) if out else np.zeros((0, 768), np.float16)


def embed_text(texts: list[str]) -> np.ndarray:
    import torch
    m, p = load()
    # SigLIP was trained with max_length padding (64 tokens); other padding hurts retrieval
    inp = p(text=[t.lower() for t in texts], padding="max_length", max_length=64, truncation=True,
            return_tensors="pt")
    with torch.no_grad():
        return _norm(m.get_text_features(**inp))


def logit(sim: np.ndarray) -> np.ndarray:
    """SigLIP's calibrated match probability for a cosine similarity."""
    m, _ = load()
    s, b = float(m.logit_scale.exp()), float(m.logit_bias)
    return 1 / (1 + np.exp(-(sim.astype(np.float32) * s + b)))
