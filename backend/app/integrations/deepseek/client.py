from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.constants import DEFAULT_OE_OCR_PROMPT, DEFAULT_VISION_PROMPT
from app.services.part_guard import parse_is_auto_part
from app.core.exceptions import AppError
from app.utils.images import compress_to_jpeg_bytes, to_data_url

logger = logging.getLogger(__name__)


class VisionCandidate(BaseModel):
    name: str
    confidence: float = 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> float:
        return _normalize_confidence(value)


class VisionResult(BaseModel):
    is_auto_part: bool = True
    part_name: str = "未知零件"
    confidence: float = 0.0
    reason: str = ""
    candidates: List[VisionCandidate] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> float:
        return _normalize_confidence(value)


class OeOcrParsed(BaseModel):
    oe_numbers: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> float:
        return _normalize_confidence(value)


def _normalize_confidence(raw: Any) -> float:
    if isinstance(raw, str):
        match = re.search(r"\d+(?:\.\d+)?", raw)
        if not match:
            return 0.0
        value = float(match.group())
        if "%" in raw:
            value /= 100
    else:
        try:
            value = float(raw or 0.0)
        except (TypeError, ValueError):
            value = 0.0
    return round(max(0.0, min(1.0, value)), 2)


def parse_json_object(raw_text: str) -> dict:
    text = (raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"模型返回内容无法解析为 JSON：{raw_text}")
        return json.loads(match.group(0))


def format_vision_result(payload: dict) -> VisionResult:
    part_name = str(payload.get("part_name") or payload.get("零件名称") or "").strip() or "未知零件"
    reason = str(payload.get("reason") or payload.get("判断依据") or "").strip()
    confidence = _normalize_confidence(payload.get("confidence", payload.get("置信度", 0.0)))
    is_auto_part = parse_is_auto_part(payload, part_name=part_name, confidence=confidence)
    candidates_raw = payload.get("candidates") or []
    candidates: List[VisionCandidate] = []
    if is_auto_part and isinstance(candidates_raw, list):
        for item in candidates_raw:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("part_name") or "").strip()
                if name:
                    candidates.append(
                        VisionCandidate(name=name, confidence=item.get("confidence", 0.0))
                    )
    if is_auto_part and not candidates:
        candidates = [VisionCandidate(name=part_name, confidence=confidence)]
    return VisionResult(
        is_auto_part=is_auto_part,
        part_name=part_name,
        confidence=confidence,
        reason=reason,
        candidates=candidates,
    )


class DeepSeekVisionClient:
    def __init__(self) -> None:
        if not settings.DEEPSEEK_API_KEY:
            logger.warning("DEEPSEEK_API_KEY is empty; vision calls will fail until configured")
        self.client = OpenAI(
            api_key=settings.DEEPSEEK_API_KEY or "missing",
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=settings.DEEPSEEK_TIMEOUT_SECONDS,
            max_retries=settings.DEEPSEEK_MAX_RETRIES,
        )
        self.model = settings.DEEPSEEK_MODEL

    def _chat_json(self, prompt: str, image_bytes_list: List[bytes]) -> tuple[dict, dict, int]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for raw in image_bytes_list:
            jpeg_bytes, _, _ = compress_to_jpeg_bytes(raw)
            content.append({"type": "image_url", "image_url": {"url": to_data_url(jpeg_bytes)}})

        logger.info(
            "DeepSeek request | model=%s | images=%s | base_url=%s | prompt_chars=%s",
            self.model,
            len(image_bytes_list),
            settings.DEEPSEEK_BASE_URL,
            len(prompt or ""),
        )
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("DeepSeek vision request failed | model=%s", self.model)
            raise AppError(f"视觉识别服务暂时不可用: {exc}", code="vision_unavailable", status_code=502) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_content = (response.choices[0].message.content or "").strip()
        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                "completion_tokens": getattr(response.usage, "completion_tokens", None),
                "total_tokens": getattr(response.usage, "total_tokens", None),
            }
        logger.info(
            "DeepSeek response | model=%s | latency_ms=%s | usage=%s | content_preview=%s",
            self.model,
            latency_ms,
            usage,
            (raw_content[:200] + "...") if len(raw_content) > 200 else raw_content,
        )
        return parse_json_object(raw_content), usage, latency_ms

    def classify_parts(self, image_bytes_list: List[bytes], prompt: Optional[str] = None) -> tuple[VisionResult, dict, int, dict]:
        if not image_bytes_list:
            raise AppError("缺少识别图片", code="invalid_image")
        payload, usage, latency_ms = self._chat_json(prompt or DEFAULT_VISION_PROMPT, image_bytes_list)
        result = format_vision_result(payload)
        logger.info(
            "Classify parts result | is_auto_part=%s | part_name=%s | confidence=%s | candidates=%s",
            result.is_auto_part,
            result.part_name,
            result.confidence,
            [c.model_dump() for c in result.candidates],
        )
        return result, usage, latency_ms, payload

    def extract_oe_numbers(self, image_bytes: bytes, prompt: Optional[str] = None) -> tuple[OeOcrParsed, dict, int, dict]:
        payload, usage, latency_ms = self._chat_json(prompt or DEFAULT_OE_OCR_PROMPT, [image_bytes])
        oe_numbers = payload.get("oe_numbers") or payload.get("oe") or []
        if isinstance(oe_numbers, str):
            oe_numbers = [oe_numbers]
        cleaned = []
        for item in oe_numbers:
            text = str(item).strip().upper()
            if text and text not in cleaned:
                cleaned.append(text)
        parsed = OeOcrParsed(
            oe_numbers=cleaned[:5],
            confidence=payload.get("confidence", 0.0),
            reason=str(payload.get("reason") or ""),
        )
        logger.info(
            "Extract OE result | oe_numbers=%s | confidence=%s",
            parsed.oe_numbers,
            parsed.confidence,
        )
        return parsed, usage, latency_ms, payload
