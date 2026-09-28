"""Embedding protocol and factory for DINOv2."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import torch
from PIL import Image


class EmbedderProtocol(Protocol):
    model_id: str
    vector_size: int

    @property
    def ready(self) -> bool: ...

    def load(self, local_files_only: bool = False) -> None: ...

    def embed_image(self, image: Image.Image) -> np.ndarray:
        """Return L2-normalized 1-D float32 vector."""
        ...

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        """Return (N, D) L2-normalized float32 matrix."""
        ...


def tensor_to_numpy_normalized(feats: torch.Tensor) -> np.ndarray:
    if feats.ndim == 1:
        feats = feats.unsqueeze(0)
    feats = feats / feats.norm(dim=-1, keepdim=True).clamp_min(1e-12)
    return feats.detach().cpu().numpy().astype(np.float32)


def create_embedder(backend: str, model_id: str | None = None, device: str | None = None):
    backend = backend.lower().strip()
    if backend in {"dinov2", "dino"}:
        from app.ml.dinov2_embedder import DINOv2Embedder

        return DINOv2Embedder(model_id=model_id or "facebook/dinov2-base", device=device)
    raise ValueError(f"Unknown embedding backend: {backend}")
