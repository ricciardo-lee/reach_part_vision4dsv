"""DINOv2 frozen image embedder."""

from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

from app.ml.device import select_device
from app.ml.embedding import tensor_to_numpy_normalized

logger = logging.getLogger(__name__)


class DINOv2Embedder:
    def __init__(self, model_id: str = "facebook/dinov2-base", device: str | None = None) -> None:
        self.model_id = model_id
        self.device = torch.device(device) if device else select_device()
        self._processor = None
        self._model = None
        self._ready = False
        self.vector_size = 768

    @property
    def ready(self) -> bool:
        return self._ready

    def load(self, local_files_only: bool = False) -> None:
        logger.info("Loading DINOv2 model: %s", self.model_id)
        try:
            self._processor = AutoImageProcessor.from_pretrained(
                self.model_id, local_files_only=local_files_only
            )
            self._model = AutoModel.from_pretrained(self.model_id, local_files_only=local_files_only)
        except Exception:
            if local_files_only:
                raise
            logger.warning("Online DINOv2 load failed, retrying from cache")
            self._processor = AutoImageProcessor.from_pretrained(self.model_id, local_files_only=True)
            self._model = AutoModel.from_pretrained(self.model_id, local_files_only=True)
        self._model.to(self.device)
        self._model.eval()
        self._ready = True
        probe = Image.new("RGB", (224, 224), color=(128, 128, 128))
        self.vector_size = int(self.embed_image(probe).shape[0])
        logger.info("DINOv2 loaded on %s, dim=%d", self.device, self.vector_size)

    def embed_image(self, image: Image.Image) -> np.ndarray:
        if not self._ready or self._processor is None or self._model is None:
            raise RuntimeError("DINOv2 model is not loaded")
        inputs = self._processor(images=image.convert("RGB"), return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with torch.no_grad():
            outputs = self._model(pixel_values=pixel_values)
            feats = outputs.last_hidden_state[:, 0]
        return tensor_to_numpy_normalized(feats).reshape(-1)

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        if not images:
            return np.zeros((0, self.vector_size), dtype=np.float32)
        if not self._ready or self._processor is None or self._model is None:
            raise RuntimeError("DINOv2 model is not loaded")
        rgb = [img.convert("RGB") for img in images]
        inputs = self._processor(images=rgb, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with torch.no_grad():
            outputs = self._model(pixel_values=pixel_values)
            feats = outputs.last_hidden_state[:, 0]
        return tensor_to_numpy_normalized(feats)
