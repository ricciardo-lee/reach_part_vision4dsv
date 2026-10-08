"""BiRefNet foreground mask for query photos. No box or click prompt."""

from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from app.ml.device import select_device

logger = logging.getLogger(__name__)


def probability_to_mask(prob: np.ndarray, size: tuple[int, int], threshold: float = 0.5) -> np.ndarray:
    """Resize a probability map to the original image and threshold it."""
    arr = np.asarray(prob, dtype=np.float32)
    if arr.ndim == 3:
        arr = arr.squeeze()
    if arr.ndim != 2:
        raise ValueError("probability map must be 2D")
    mask_img = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))
    mask_img = mask_img.resize(size, Image.Resampling.BILINEAR)
    return np.asarray(mask_img, dtype=np.float32) >= (threshold * 255.0)


class BiRefNetSegmenter:
    def __init__(self, model_id: str = "ZhengPeng7/BiRefNet", device: str | None = None, input_size: int = 1024) -> None:
        self.model_id = model_id
        self.input_size = int(input_size)
        if device and device != "auto":
            self.device = torch.device(device)
        else:
            self.device = select_device()
        # Moving these weights onto MPS aborts inside the Metal blit shader
        # (SIGABRT). That kills the Celery worker before Python can catch it.
        if self.device.type == "mps":
            logger.warning("BiRefNet runs on CPU; MPS weight copy aborts this Mac's Metal driver")
            self.device = torch.device("cpu")
        self._model = None
        self._ready = False
        self._transform = transforms.Compose(
            [
                transforms.Resize((self.input_size, self.input_size)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

    @property
    def ready(self) -> bool:
        return self._ready

    def load(self, local_files_only: bool = False) -> None:
        from transformers import AutoModelForImageSegmentation

        logger.info("Loading BiRefNet %s on %s", self.model_id, self.device)
        try:
            model = AutoModelForImageSegmentation.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                dtype=torch.float32,
                local_files_only=local_files_only,
            )
        except Exception:
            if local_files_only:
                raise
            logger.warning("Online BiRefNet load failed, retrying from cache")
            model = AutoModelForImageSegmentation.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                dtype=torch.float32,
                local_files_only=True,
            )
        # The published checkpoint is float16. CPU kernels reject a float32
        # image against float16 biases, so keep the whole network in float32.
        self._model = model.to(self.device).float().eval()
        self._ready = True
        logger.info("BiRefNet loaded on %s", self.device)

    def to_cpu(self) -> None:
        if self._model is None:
            return
        self.device = torch.device("cpu")
        self._model.to(self.device).float().eval()

    def predict_mask(self, image: Image.Image, x: float | None = None, y: float | None = None) -> np.ndarray | None:
        """Return a boolean HxW foreground mask. x/y are ignored."""
        del x, y
        if not self.ready or self._model is None:
            return None
        rgb = image.convert("RGB")
        width, height = rgb.size
        if width < 2 or height < 2:
            return None
        batch = self._transform(rgb).unsqueeze(0).to(self.device)
        with torch.no_grad():
            output = self._model(batch)
        prob = self._last_probability(output)
        if prob is None:
            return None
        return probability_to_mask(prob, (width, height))

    def predict_masks(self, images: list[Image.Image]) -> list[np.ndarray | None]:
        """Batch version of predict_mask. One forward pass for the whole list."""
        results: list[np.ndarray | None] = [None] * len(images)
        if not images or not self.ready or self._model is None:
            return results
        tensors: list[torch.Tensor] = []
        sizes: list[tuple[int, int]] = []
        valid_index: list[int] = []
        for index, image in enumerate(images):
            rgb = image.convert("RGB")
            width, height = rgb.size
            if width < 2 or height < 2:
                continue
            tensors.append(self._transform(rgb))
            sizes.append((width, height))
            valid_index.append(index)
        if not tensors:
            return results
        batch = torch.stack(tensors, dim=0).to(self.device)
        with torch.inference_mode():
            output = self._model(batch)
        probs = self._batch_probabilities(output)
        if probs is None:
            return results
        for prob, (width, height), index in zip(probs, sizes, valid_index, strict=True):
            results[index] = probability_to_mask(prob, (width, height))
        return results

    @staticmethod
    def _last_probability(output) -> np.ndarray | None:
        value = output[-1] if isinstance(output, (list, tuple)) else output
        if hasattr(value, "logits"):
            value = value.logits
        if not hasattr(value, "sigmoid"):
            return None
        pred = value.sigmoid().detach().float().cpu()
        if pred.ndim == 4:
            pred = pred[0, 0]
        elif pred.ndim == 3:
            pred = pred[0]
        arr = pred.numpy()
        if arr.ndim != 2:
            return None
        return arr

    @staticmethod
    def _batch_probabilities(output) -> list[np.ndarray] | None:
        value = output[-1] if isinstance(output, (list, tuple)) else output
        if hasattr(value, "logits"):
            value = value.logits
        if not hasattr(value, "sigmoid"):
            return None
        pred = value.sigmoid().detach().float().cpu()
        if pred.ndim == 4:
            pred = pred[:, 0]
        elif pred.ndim != 3:
            return None
        return [pred[i].numpy() for i in range(pred.shape[0])]
