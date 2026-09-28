from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import List, Optional

from PIL import Image

from app.core.config import settings
from app.core.constants import CATEGORY_CN, PART_PURPOSES
from app.integrations.deepseek.client import DeepSeekVisionClient
from app.models import (
    OeOcrResult,
    ProductQuerySnapshot,
    PromptConfig,
    RecognitionResult,
    RecognitionSession,
    RetrievalResult,
    UploadedImage,
)
from app.schemas import ProductOut
from app.services.mapping import map_category
from app.services.retrieval_runtime import get_similarity_service
from app.services.similarity import SearchCandidateItem, SearchResponse, SimilarityService
from app.utils.minio_client import get_storage

logger = logging.getLogger("app.services.recognition")


async def get_active_prompt(purpose: str) -> Optional[PromptConfig]:
    prompt = await PromptConfig.filter(purpose=purpose, is_active=True).order_by("-id").first()
    if prompt:
        logger.debug("Active prompt | purpose=%s | name=%s | version=%s", purpose, prompt.name, prompt.version)
    else:
        logger.warning("No active prompt found | purpose=%s, fallback to default", purpose)
    return prompt


def _jpeg_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


async def _save_query_foregrounds(
    session: RecognitionSession,
    images: List[UploadedImage],
    search: SearchResponse,
) -> None:
    """Persist the white-background image actually embedded for retrieval."""
    prepared = list(getattr(search, "prepared_images", None) or [])
    if not prepared:
        return
    storage = get_storage()
    for image, prep in zip(images, prepared):
        image.foreground_source = prep.foreground_source or "full_only"
        if prep.foreground is not None:
            key = f"sessions/{session.public_id}/query-foreground/{image.id}.jpg"
            try:
                storage.put_bytes(key, _jpeg_bytes(prep.foreground), "image/jpeg")
                image.foreground_object_key = key
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to store query foreground | public_id=%s | image_id=%s",
                    session.public_id,
                    image.id,
                )
        await image.save(update_fields=["foreground_object_key", "foreground_source"])


async def _load_part_images(session_id: int) -> List[UploadedImage]:
    return await UploadedImage.filter(
        session_id=session_id,
        purpose__in=list(PART_PURPOSES),
        deleted_at=None,
    ).order_by("sort_order")


def _bytes_to_pil(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


def _candidate_margin(candidates: list[SearchCandidateItem]) -> float | None:
    if not candidates:
        return None
    if len(candidates) >= 2:
        return float(candidates[0].score - candidates[1].score)
    return 1.0


async def _seed_confirmed_category(session: RecognitionSession, category_cn: str | None) -> None:
    if not category_cn:
        return
    session.confirmed_category_name = category_cn
    mapped_code, mapped_name = await map_category(category_cn)
    if mapped_code:
        session.confirmed_category_code = mapped_code
    if mapped_name:
        session.confirmed_category_name = mapped_name
    await session.save()


def _products_from_skus(
    skus: list[SearchCandidateItem],
    *,
    category_cn: str | None,
    source: str,
) -> list[ProductOut]:
    products: list[ProductOut] = []
    for item in skus:
        cn = item.category_cn or category_cn or CATEGORY_CN.get(item.category_id or "", None) or item.category_id
        products.append(
            ProductOut(
                sku=item.sku,
                name=f"{cn or '产品'} {item.sku}",
                category_name=cn,
                match_reason=f"{source} score={item.score:.3f}",
                brand="Reach",
                attributes={},
            )
        )
    return products


async def _write_category_snapshot(
    session: RecognitionSession,
    *,
    category_id: str,
    category_cn: str | None,
    skus: list[SearchCandidateItem],
    index_version: str | None,
    vision_assisted: bool,
    category_confidence: float | None,
) -> None:
    products = _products_from_skus(
        skus,
        category_cn=category_cn,
        source="360图库品类候选" if not vision_assisted else "360图库+Vision品类候选",
    )
    await ProductQuerySnapshot.create(
        session_id=session.id,
        query_payload={
            "source": "category_retrieval",
            "stage": "candidate_products",
            "category_id": category_id,
            "category_cn": category_cn,
            "vision_assisted": vision_assisted,
            "category_confidence": category_confidence,
            "candidate_skus": [p.sku for p in products],
            "attribute_filters": {},
            "index_version": index_version,
        },
        result_payload=[p.model_dump() for p in products],
        result_count=len(products),
    )
    await _seed_confirmed_category(session, category_cn or CATEGORY_CN.get(category_id))


async def _finalize_category_match(
    session: RecognitionSession,
    *,
    search: SearchResponse,
    category_id: str,
    category_cn: str | None,
    skus: list[SearchCandidateItem],
    vision_assisted: bool,
    category_confidence: float | None,
    image_count: int,
) -> RetrievalResult:
    top = search.candidates[0] if search.candidates else None
    record = await RetrievalResult.create(
        session_id=session.id,
        index_version=search.index_version,
        embedding_model=search.embedding_model,
        decision="category_match",
        confidence_level=search.confidence_level,
        accepted=False,
        matched_sku=None,
        score=float(top.score) if top else None,
        margin=_candidate_margin(search.candidates),
        selected_category_id=category_id,
        selected_category_cn=category_cn,
        category_confidence=category_confidence,
        vision_assisted=vision_assisted,
        candidates=[c.to_dict() for c in search.candidates],
        quality_warnings=search.quality_warnings,
        fallback_reason=None,
        latency_ms=search.latency_ms,
        image_count=image_count,
        success=True,
        error_message=None,
    )
    await _write_category_snapshot(
        session,
        category_id=category_id,
        category_cn=category_cn,
        skus=skus,
        index_version=search.index_version,
        vision_assisted=vision_assisted,
        category_confidence=category_confidence,
    )
    logger.info(
        "Category match | public_id=%s | category=%s | skus=%s | vision_assisted=%s",
        session.public_id,
        category_id,
        [s.sku for s in skus],
        vision_assisted,
    )
    return record


async def _try_sku_retrieval(
    session: RecognitionSession, images: List[UploadedImage]
) -> tuple[RetrievalResult | None, SearchResponse | None, SimilarityService | None]:
    """Run multi-image SKU retrieval.

    Returns (persisted_result_or_none, search_response_or_none, service).
    High-confidence SKU matches are persisted with accepted=True.
    Non-accepted paths return search for further category handling (may not yet persist).
    """
    service = get_similarity_service()
    if service is None:
        record = await RetrievalResult.create(
            session_id=session.id,
            accepted=False,
            decision="unavailable",
            confidence_level="none",
            fallback_reason="retrieval_unavailable",
            success=False,
            error_message="Similarity service not ready",
            image_count=len(images),
        )
        return record, None, None

    storage = get_storage()
    pil_images: List[Image.Image] = []
    for image in images:
        data = storage.get_bytes(image.object_key)
        pil_images.append(_bytes_to_pil(data))

    try:
        result: SearchResponse = service.search(
            images=pil_images,
            top_k=max(5, settings.SEARCH_CATEGORY_TOP_N),
        )
        await _save_query_foregrounds(session, images, result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("SKU retrieval failed | public_id=%s | error=%s", session.public_id, exc)
        record = await RetrievalResult.create(
            session_id=session.id,
            index_version=getattr(service, "index_version", None),
            embedding_model=getattr(service.embedder, "model_id", None),
            accepted=False,
            decision="error",
            confidence_level="none",
            fallback_reason="retrieval_error",
            success=False,
            error_message=str(exc)[:500],
            image_count=len(images),
        )
        return record, None, service

    accepted = service.is_high_confidence_match(result)
    top = result.candidates[0] if result.candidates else None
    margin = _candidate_margin(result.candidates)

    if accepted and top:
        category_cn = top.category_cn or CATEGORY_CN.get(top.category_id or "", None) or top.category_id
        record = await RetrievalResult.create(
            session_id=session.id,
            index_version=result.index_version,
            embedding_model=result.embedding_model,
            decision=result.decision,
            confidence_level=result.confidence_level,
            accepted=True,
            matched_sku=top.sku,
            score=float(top.score),
            margin=margin,
            selected_category_id=top.category_id,
            selected_category_cn=category_cn,
            category_confidence=float(top.score),
            vision_assisted=False,
            candidates=[c.to_dict() for c in result.candidates],
            quality_warnings=result.quality_warnings,
            fallback_reason=None,
            latency_ms=result.latency_ms,
            image_count=len(images),
            success=True,
            error_message=None,
        )
        product = ProductOut(
            sku=top.sku,
            name=f"{category_cn or '产品'} {top.sku}",
            category_name=category_cn,
            match_reason=f"360图库直匹配 score={top.score:.3f}",
            brand="Reach",
            attributes={},
        )
        await ProductQuerySnapshot.create(
            session_id=session.id,
            query_payload={
                "source": "sku_retrieval",
                "stage": "sku_confirmed",
                "matched_sku": top.sku,
                "score": top.score,
                "index_version": result.index_version,
                "attribute_filters": {},
            },
            result_payload=[product.model_dump()],
            result_count=1,
        )
        await _seed_confirmed_category(session, category_cn)
        logger.info(
            "SKU match accepted | public_id=%s | sku=%s | score=%s | margin=%s",
            session.public_id,
            top.sku,
            top.score,
            margin,
        )
        return record, result, service

    return None, result, service


async def _persist_constrained_vision_result(
    session: RecognitionSession,
    *,
    client: DeepSeekVisionClient,
    vision_result,
    usage: dict,
    latency_ms: int,
    raw: dict,
    allowed: list[dict],
    known: dict[str, list],
    accepted_for_match: bool,
) -> RecognitionResult:
    """Always persist constrained Vision so misclassifications can be audited."""
    selected_id = raw.get("category_id") if isinstance(raw, dict) else None
    mapped_code, mapped_name = await map_category(vision_result.part_name)
    if not mapped_name and selected_id:
        mapped_name = CATEGORY_CN.get(str(selected_id), None)
    retrieval_summary = {
        cid: [
            {"sku": c.sku, "score": c.score, "category_cn": c.category_cn}
            for c in items[:5]
        ]
        for cid, items in known.items()
    }
    enriched_candidates = []
    for candidate in vision_result.candidates:
        code, name = await map_category(candidate.name)
        enriched_candidates.append(
            {
                "name": candidate.name,
                "confidence": candidate.confidence,
                "category_code": code,
                "category_name": name or candidate.name,
            }
        )
    return await RecognitionResult.create(
        session_id=session.id,
        model_name=f"{client.model}|constrained_category",
        prompt_version="constrained_v1",
        raw_response={
            "purpose": "constrained_category",
            "payload": raw,
            "allowed_categories": allowed,
            "retrieval_candidates_by_category": retrieval_summary,
            "selected_category_id": selected_id,
            "in_allowlist": bool(raw.get("in_allowlist")) if isinstance(raw, dict) else False,
            "accepted_for_category_match": accepted_for_match,
            "usage": usage,
            "latency_ms": latency_ms,
            "vision_part_name": vision_result.part_name,
            "vision_confidence": vision_result.confidence,
            "vision_reason": vision_result.reason,
            "is_auto_part": vision_result.is_auto_part,
        },
        part_name=vision_result.part_name,
        confidence=vision_result.confidence,
        reason=vision_result.reason
        or ("constrained_category_accepted" if accepted_for_match else "constrained_category_rejected"),
        candidates=enriched_candidates,
        mapped_category_code=mapped_code if vision_result.is_auto_part else None,
        mapped_category_name=mapped_name if vision_result.is_auto_part else None,
        is_auto_part=bool(vision_result.is_auto_part),
        latency_ms=latency_ms,
        token_usage=usage,
        success=True,
        error_message=None if accepted_for_match else "constrained_category_not_accepted",
    )


async def _try_category_match(
    session: RecognitionSession,
    images: List[UploadedImage],
    search: SearchResponse,
    service: SimilarityService,
) -> RetrievalResult | None:
    """Attempt category-level match (optionally Vision-assisted). Returns record or None → vision fallback."""
    if not service.is_category_eligible(search, min_score=settings.SEARCH_CATEGORY_MIN_SCORE):
        return None

    groups = SimilarityService.group_candidates_by_category(search.candidates)
    known = {k: v for k, v in groups.items() if k != "_unknown"}
    if not known:
        return None

    vision_assisted = False
    category_confidence: float | None = None
    selected_id: str | None = None

    if len(known) == 1:
        selected_id = next(iter(known.keys()))
        category_confidence = float(known[selected_id][0].score)
    else:
        # Multi-category → constrained Vision (always persist for audit).
        storage = get_storage()
        image_bytes_list: List[bytes] = [storage.get_bytes(img.object_key) for img in images]
        allowed = [
            {
                "category_id": cid,
                "category_cn": CATEGORY_CN.get(cid) or (items[0].category_cn if items else cid),
            }
            for cid, items in known.items()
        ]
        client = DeepSeekVisionClient()
        try:
            vision_result, usage, latency_ms, raw = client.classify_parts_constrained(
                image_bytes_list, allowed
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Constrained vision failed | public_id=%s | error=%s", session.public_id, exc
            )
            await RecognitionResult.create(
                session_id=session.id,
                model_name=f"{client.model}|constrained_category",
                prompt_version="constrained_v1",
                raw_response={
                    "purpose": "constrained_category",
                    "allowed_categories": allowed,
                    "error": str(exc)[:500],
                },
                success=False,
                error_message=str(exc)[:500],
            )
            return None

        selected_id = raw.get("category_id") if isinstance(raw, dict) else None
        accepted_for_match = bool(
            vision_result.is_auto_part
            and selected_id
            and selected_id in known
            and vision_result.confidence >= settings.SEARCH_VISION_CATEGORY_MIN_CONFIDENCE
        )
        await _persist_constrained_vision_result(
            session,
            client=client,
            vision_result=vision_result,
            usage=usage,
            latency_ms=latency_ms,
            raw=raw if isinstance(raw, dict) else {},
            allowed=allowed,
            known=known,
            accepted_for_match=accepted_for_match,
        )
        if not accepted_for_match:
            logger.info(
                "Constrained vision rejected | public_id=%s | id=%s | conf=%s | reason=%s",
                session.public_id,
                selected_id,
                vision_result.confidence,
                vision_result.reason,
            )
            return None
        vision_assisted = True
        category_confidence = float(vision_result.confidence)

    assert selected_id is not None
    category_cn = CATEGORY_CN.get(selected_id) or (
        known[selected_id][0].category_cn if known[selected_id] else selected_id
    )
    skus = SimilarityService.filter_same_category_skus(
        search.candidates,
        selected_id,
        top_n=settings.SEARCH_CATEGORY_TOP_N,
        relative_floor=settings.SEARCH_CATEGORY_RELATIVE_FLOOR,
        min_score=settings.SEARCH_CATEGORY_MIN_SCORE,
    )
    if not skus:
        return None

    return await _finalize_category_match(
        session,
        search=search,
        category_id=selected_id,
        category_cn=category_cn,
        skus=skus,
        vision_assisted=vision_assisted,
        category_confidence=category_confidence,
        image_count=len(images),
    )


async def _persist_vision_fallback_retrieval(
    session: RecognitionSession,
    search: SearchResponse | None,
    images: List[UploadedImage],
    *,
    fallback_reason: str,
) -> RetrievalResult | None:
    if search is None:
        return None
    top = search.candidates[0] if search.candidates else None
    return await RetrievalResult.create(
        session_id=session.id,
        index_version=search.index_version,
        embedding_model=search.embedding_model,
        decision="vision_fallback",
        confidence_level=search.confidence_level,
        accepted=False,
        matched_sku=None,
        score=float(top.score) if top else None,
        margin=_candidate_margin(search.candidates),
        candidates=[c.to_dict() for c in search.candidates],
        quality_warnings=search.quality_warnings,
        fallback_reason=fallback_reason,
        latency_ms=search.latency_ms,
        image_count=len(images),
        success=True,
        error_message=None,
    )


async def _run_deepseek_vision(session: RecognitionSession, images: List[UploadedImage]) -> None:
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
            raw_response={
                "purpose": "full_vision",
                "payload": raw,
                "usage": usage,
                "latency_ms": latency_ms,
            },
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
        raise


async def run_vision_recognition(session_id: int) -> None:
    """Primary pipeline: SKU → category match (optional constrained Vision) → DeepSeek fallback."""
    session = await RecognitionSession.get(id=session_id)
    session.status = "processing"
    await session.save()
    logger.info("Vision recognition start | session_id=%s | public_id=%s", session_id, session.public_id)

    images = await _load_part_images(session_id)
    if not images:
        session.status = "failed"
        session.error_message = "没有可用于识别的零件图片"
        await session.save()
        logger.error("Vision recognition aborted: no images | public_id=%s", session.public_id)
        return

    retrieval, search, service = await _try_sku_retrieval(session, images)
    if retrieval and retrieval.accepted:
        session.status = "done"
        session.error_message = None
        session.completed_at = datetime.utcnow()
        await session.save()
        return

    # Already persisted unavailable/error → go straight to vision.
    if retrieval and retrieval.decision in {"unavailable", "error"}:
        await _run_deepseek_vision(session, images)
        return

    if search is not None and service is not None:
        category_record = await _try_category_match(session, images, search, service)
        if category_record is not None:
            session.status = "done"
            session.error_message = None
            session.completed_at = datetime.utcnow()
            await session.save()
            return

        fallback_reason = "low_similarity"
        if search.reject_reason:
            fallback_reason = search.reject_reason
        elif search.confidence_level in {"medium", "low", "none"}:
            # Medium multi-category Vision failed or single-category empty after filter.
            if service.is_category_eligible(search, min_score=settings.SEARCH_CATEGORY_MIN_SCORE):
                fallback_reason = "category_ambiguous"
            else:
                fallback_reason = f"confidence_{search.confidence_level}"
        await _persist_vision_fallback_retrieval(
            session, search, images, fallback_reason=fallback_reason
        )

    await _run_deepseek_vision(session, images)


async def run_vision_fallback_only(session_id: int) -> None:
    """Force DeepSeek vision path (user rejected SKU / category match)."""
    session = await RecognitionSession.get(id=session_id)
    session.status = "processing"
    await session.save()
    images = await _load_part_images(session_id)
    if not images:
        session.status = "failed"
        session.error_message = "没有可用于识别的零件图片"
        await session.save()
        return
    await _run_deepseek_vision(session, images)


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
    return record
