from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from app.integrations.deepseek.client import DeepSeekVisionClient
from app.models import OeOcrResult, PromptConfig, RecognitionResult, RecognitionSession, UploadedImage
from app.services.mapping import map_category
from app.utils.minio_client import get_storage

logger = logging.getLogger("app.services.recognition")


async def get_active_prompt(purpose: str) -> Optional[PromptConfig]:
    prompt = await PromptConfig.filter(purpose=purpose, is_active=True).order_by("-id").first()
    if prompt:
        logger.debug("Active prompt | purpose=%s | name=%s | version=%s", purpose, prompt.name, prompt.version)
    else:
        logger.warning("No active prompt found | purpose=%s, fallback to default", purpose)
    return prompt


async def run_vision_recognition(session_id: int) -> None:
    session = await RecognitionSession.get(id=session_id)
    session.status = "processing"
    await session.save()
    logger.info("Vision recognition start | session_id=%s | public_id=%s", session_id, session.public_id)

    images = await UploadedImage.filter(
        session_id=session_id,
        purpose__in=["part", "part_overall", "part_connector", "part_label", "part_other"],
        deleted_at=None,
    ).order_by("sort_order")
    if not images:
        session.status = "failed"
        session.error_message = "没有可用于识别的零件图片"
        await session.save()
        logger.error("Vision recognition aborted: no images | public_id=%s", session.public_id)
        return

    storage = get_storage()
    image_bytes_list: List[bytes] = []
    for image in images:
        data = storage.get_bytes(image.object_key)
        image_bytes_list.append(data)
        logger.debug(
            "Loaded image for vision | public_id=%s | image_id=%s | bytes=%s",
            session.public_id,
            image.id,
            len(data),
        )

    prompt = await get_active_prompt("vision")
    client = DeepSeekVisionClient()
    try:
        result, usage, latency_ms, raw = client.classify_parts(
            image_bytes_list,
            prompt=prompt.content if prompt else None,
        )
        mapped_code, mapped_name = await map_category(result.part_name)
        enriched = []
        for candidate in result.candidates:
            code, name = await map_category(candidate.name)
            enriched.append(
                {
                    "name": candidate.name,
                    "confidence": candidate.confidence,
                    "category_code": code,
                    "category_name": name or candidate.name,
                }
            )

        await RecognitionResult.create(
            session_id=session.id,
            model_name=client.model,
            prompt_version=prompt.version if prompt else "default",
            raw_response=raw,
            part_name=result.part_name,
            confidence=result.confidence,
            reason=result.reason,
            candidates=enriched if result.is_auto_part else [],
            mapped_category_code=mapped_code if result.is_auto_part else None,
            mapped_category_name=mapped_name if result.is_auto_part else None,
            is_auto_part=result.is_auto_part,
            latency_ms=latency_ms,
            token_usage=usage,
            success=True,
        )
        session.status = "done"
        session.error_message = None if result.is_auto_part else (result.reason or "未识别到汽配零件")
        session.completed_at = datetime.utcnow()
        await session.save()
        logger.info(
            "Vision recognition success | public_id=%s | is_auto_part=%s | part=%s | mapped=%s/%s | confidence=%s | latency_ms=%s | usage=%s",
            session.public_id,
            result.is_auto_part,
            result.part_name,
            mapped_code,
            mapped_name,
            result.confidence,
            latency_ms,
            usage,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Vision recognition failed | public_id=%s | error=%s", session.public_id, exc)
        await RecognitionResult.create(
            session_id=session.id,
            model_name=client.model,
            prompt_version=prompt.version if prompt else "default",
            success=False,
            error_message=str(exc),
        )
        session.status = "failed"
        session.error_message = str(exc)
        await session.save()
        # Re-raise so Celery can retry transient failures (max_retries applies).
        raise


async def run_oe_ocr(session_id: int, image_id: int) -> OeOcrResult:
    session = await RecognitionSession.get(id=session_id)
    image = await UploadedImage.get(id=image_id, session_id=session_id)
    storage = get_storage()
    raw_bytes = storage.get_bytes(image.object_key)
    prompt = await get_active_prompt("oe_ocr")
    client = DeepSeekVisionClient()
    logger.info("OE OCR calling model | public_id=%s | image_id=%s", session.public_id, image.id)
    parsed, usage, latency_ms, raw = client.extract_oe_numbers(
        raw_bytes,
        prompt=prompt.content if prompt else None,
    )
    record = await OeOcrResult.create(
        session_id=session.id,
        image_id=image.id,
        oe_numbers=parsed.oe_numbers,
        confidence=parsed.confidence,
        reason=parsed.reason,
        raw_response={"payload": raw, "usage": usage, "latency_ms": latency_ms},
        success=True,
    )
    logger.info(
        "OE OCR success | public_id=%s | oe_numbers=%s | confidence=%s | latency_ms=%s",
        session.public_id,
        parsed.oe_numbers,
        parsed.confidence,
        latency_ms,
    )
    return record
