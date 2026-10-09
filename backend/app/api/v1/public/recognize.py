from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.config import settings
from app.core.constants import (
    CATEGORY_CN,
    OE_LABEL_PURPOSE,
    PART_IMAGE_PURPOSE,
    PART_PURPOSES,
)
from app.core.exceptions import AppError
from app.api.deps import get_device_session, get_recognition_session
from app.models import (
    AuditLog,
    DeviceSession,
    OeOcrResult,
    RecognitionResult,
    RecognitionSession,
    RetrievalResult,
    UploadedImage,
)
from app.schemas import (
    APIResponse,
    ConfirmCategoryIn,
    ConsentIn,
    FeedbackIn,
    ImageFocusPointsIn,
    ImageOut,
    OeConfirmIn,
    RecognitionResultOut,
    RecognitionSessionOut,
    RetrievalCandidateOut,
    RetrievalMatchOut,
    VehicleFilterIn,
)
from app.services.bootstrap import image_expiry, new_public_id
from app.services.catalog import catalog_service
from app.services.part_guard import ensure_auto_part, session_is_auto_part
from app.services.recognition import run_oe_ocr
from app.utils.images import compress_to_jpeg_bytes, compute_phash, validate_image_meta
from app.utils.minio_client import get_storage

logger = logging.getLogger("app.api.recognize")

router = APIRouter(prefix="/recognize", tags=["public-recognize"])


def _blank_to_none(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _progress_hint(
    status: str,
    *,
    is_auto_part: bool = True,
    recognition_mode: str | None = None,
) -> str:
    if status == "done" and not is_auto_part:
        return "未识别到汽配零件，请重新拍摄"
    if status == "done" and recognition_mode == "sku_match":
        return "已匹配到公司产品"
    if status == "done" and recognition_mode == "category_match":
        return "已确认品类，请从候选产品中选择"
    if status == "processing":
        return "识别中（优先图库匹配）…"
    mapping = {
        "created": "等待上传",
        "uploading": "图片已上传，准备识别",
        "processing": "识别中，请稍候",
        "done": "识别完成",
        "failed": "识别失败，可重试",
    }
    return mapping.get(status, status)


def _session_recognition_mode(
    retrieval: RetrievalResult | None,
    vision: RecognitionResult | None,
) -> str | None:
    if retrieval and retrieval.accepted:
        return "sku_match"
    if retrieval and retrieval.decision == "category_match":
        return "category_match"
    if vision or (retrieval and not retrieval.accepted):
        return "vision_fallback"
    return None


async def serialize_session(session: RecognitionSession) -> RecognitionSessionOut:
    images = await UploadedImage.filter(session_id=session.id, deleted_at=None).order_by("sort_order")
    storage = get_storage()
    image_out: List[ImageOut] = []
    for image in images:
        preview = None
        try:
            preview = storage.presigned_get_url(image.object_key)
        except Exception:  # noqa: BLE001
            preview = None
        focus = None
        raw_focus = getattr(image, "focus_point", None)
        if isinstance(raw_focus, dict) and "x" in raw_focus and "y" in raw_focus:
            focus = {"x": float(raw_focus["x"]), "y": float(raw_focus["y"]), "source": raw_focus.get("source")}
        foreground_preview = None
        foreground_key = getattr(image, "foreground_object_key", None)
        if foreground_key:
            try:
                foreground_preview = storage.presigned_get_url(foreground_key)
            except Exception:  # noqa: BLE001
                foreground_preview = None
        image_out.append(
            ImageOut(
                id=image.id,
                object_key=image.object_key,
                purpose=image.purpose,
                sort_order=image.sort_order,
                preview_url=preview,
                width=image.width,
                height=image.height,
                focus_point=focus,
                foreground_preview_url=foreground_preview,
                foreground_source=getattr(image, "foreground_source", None),
            )
        )

    latest = await RecognitionResult.filter(session_id=session.id, success=True).order_by("-id").first()
    retrieval = await RetrievalResult.filter(session_id=session.id).order_by("-id").first()
    is_auto_part = await session_is_auto_part(session)
    recognition_mode = _session_recognition_mode(retrieval, latest)

    result_out = None
    if latest:
        result_out = RecognitionResultOut(
            is_auto_part=is_auto_part,
            part_name=latest.part_name,
            confidence=latest.confidence,
            reason=latest.reason,
            candidates=(latest.candidates or []) if is_auto_part else [],
            mapped_category_code=latest.mapped_category_code,
            mapped_category_name=latest.mapped_category_name,
        )

    retrieval_out = None
    if retrieval:
        candidates_raw = retrieval.candidates or []
        retrieval_out = RetrievalMatchOut(
            accepted=bool(retrieval.accepted),
            decision=retrieval.decision,
            confidence_level=retrieval.confidence_level,
            matched_sku=retrieval.matched_sku,
            score=retrieval.score,
            margin=retrieval.margin,
            selected_category_id=getattr(retrieval, "selected_category_id", None),
            selected_category_cn=getattr(retrieval, "selected_category_cn", None),
            category_confidence=getattr(retrieval, "category_confidence", None),
            vision_assisted=bool(getattr(retrieval, "vision_assisted", False)),
            index_version=retrieval.index_version,
            embedding_model=retrieval.embedding_model,
            fallback_reason=retrieval.fallback_reason,
            candidates=[
                RetrievalCandidateOut(
                    sku=str(c.get("sku") or ""),
                    category_id=c.get("category_id"),
                    category_cn=c.get("category_cn")
                    or CATEGORY_CN.get(str(c.get("category_id") or ""), None),
                    score=float(c.get("score") or 0.0),
                    matched_views=list(c.get("matched_views") or []),
                    reason=str(c.get("reason") or "vector_match"),
                )
                for c in candidates_raw
                if c.get("sku")
            ],
        )

    return RecognitionSessionOut(
        public_id=session.public_id,
        status=session.status,
        progress_hint=_progress_hint(
            session.status,
            is_auto_part=is_auto_part,
            recognition_mode=recognition_mode,
        ),
        is_auto_part=is_auto_part,
        recognition_mode=recognition_mode,
        images=image_out,
        result=result_out,
        retrieval=retrieval_out,
        confirmed_category_code=session.confirmed_category_code,
        confirmed_category_name=session.confirmed_category_name,
        vehicle_brand=session.vehicle_brand,
        vehicle_series=session.vehicle_series,
        vehicle_model=session.vehicle_model,
        vehicle_year=session.vehicle_year,
        oe_number=session.oe_number,
        oe_source=session.oe_source,
        optimization_consent=session.optimization_consent,
        error_message=session.error_message,
    )


@router.post("", response_model=APIResponse)
async def create_session(device_session: DeviceSession = Depends(get_device_session)) -> APIResponse:
    session = await RecognitionSession.create(
        public_id=new_public_id(),
        device_session_id=device_session.id,
        status="created",
    )
    logger.info(
        "Created recognition session | public_id=%s | device_session_id=%s",
        session.public_id,
        device_session.id,
    )
    return APIResponse(data=await serialize_session(session))


@router.get("/{public_id}", response_model=APIResponse)
async def get_session(session: RecognitionSession = Depends(get_recognition_session)) -> APIResponse:
    logger.debug("Get session | public_id=%s | status=%s", session.public_id, session.status)
    return APIResponse(data=await serialize_session(session))


@router.post("/{public_id}/images", response_model=APIResponse)
async def upload_images(
    session: RecognitionSession = Depends(get_recognition_session),
    files: List[UploadFile] = File(...),
    purpose: str = Form(PART_IMAGE_PURPOSE),
    sort_order: int = Form(0),
) -> APIResponse:
    # Normalize legacy angle purposes to unified "part" for new uploads.
    if purpose in PART_PURPOSES:
        purpose = PART_IMAGE_PURPOSE
    if purpose not in {PART_IMAGE_PURPOSE, OE_LABEL_PURPOSE}:
        raise AppError("purpose 仅支持 part / oe_label（兼容旧角度字段会自动转为 part）")

    if not files:
        raise AppError("请至少上传 1 张图片")

    existing = await UploadedImage.filter(session_id=session.id, purpose=purpose, deleted_at=None).count()
    if purpose == OE_LABEL_PURPOSE:
        max_count = 1
        if existing + len(files) > max_count:
            raise AppError(f"该用途最多上传 {max_count} 张图片")
    else:
        # All part images share one quota (1–8), independent of oe_label.
        part_total = await UploadedImage.filter(
            session_id=session.id,
            purpose__in=list(PART_PURPOSES),
            deleted_at=None,
        ).count()
        if part_total + len(files) > settings.MAX_IMAGES_PER_SESSION:
            raise AppError(f"零件图合计最多上传 {settings.MAX_IMAGES_PER_SESSION} 张")
        if len(files) > settings.MAX_IMAGES_PER_SESSION:
            raise AppError(f"单次最多上传 {settings.MAX_IMAGES_PER_SESSION} 张图片")

    logger.info(
        "Upload images start | public_id=%s | purpose=%s | count=%s | existing=%s",
        session.public_id,
        purpose,
        len(files),
        existing,
    )
    storage = get_storage()
    storage.ensure_bucket()
    saved = []
    for index, upload in enumerate(files):
        raw = await upload.read()
        validate_image_meta(upload.filename or "image.jpg", upload.content_type or "", len(raw), settings.max_upload_bytes)
        jpeg_bytes, width, height = compress_to_jpeg_bytes(raw)
        phash = compute_phash(jpeg_bytes)
        object_key = f"sessions/{session.public_id}/{purpose}/{uuid.uuid4().hex}.jpg"
        storage.put_bytes(object_key, jpeg_bytes, "image/jpeg")
        order = sort_order + index if purpose == PART_IMAGE_PURPOSE else sort_order
        if purpose == PART_IMAGE_PURPOSE and sort_order == 0:
            order = existing + index
        image = await UploadedImage.create(
            session_id=session.id,
            object_key=object_key,
            content_type="image/jpeg",
            file_size=len(jpeg_bytes),
            width=width,
            height=height,
            phash=phash,
            purpose=purpose,
            sort_order=order,
            expires_at=image_expiry(),
        )
        saved.append(image)
        logger.info(
            "Saved image | public_id=%s | image_id=%s | key=%s | size=%s | %sx%s",
            session.public_id,
            image.id,
            object_key,
            len(jpeg_bytes),
            width,
            height,
        )

    session.status = "uploading"
    await session.save()
    logger.info("Upload images done | public_id=%s | saved=%s", session.public_id, len(saved))
    return APIResponse(data=await serialize_session(session), message=f"已上传 {len(saved)} 张图片")


@router.put("/{public_id}/image-focus-points", response_model=APIResponse)
async def save_image_focus_points(
    payload: ImageFocusPointsIn,
    session: RecognitionSession = Depends(get_recognition_session),
) -> APIResponse:
    ids = [item.image_id for item in payload.items]
    images = await UploadedImage.filter(id__in=ids, session_id=session.id, deleted_at=None)
    by_id = {img.id: img for img in images}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise AppError(f"图片不属于当前会话: {missing}", code="invalid_request")
    for item in payload.items:
        image = by_id[item.image_id]
        if image.purpose not in PART_PURPOSES:
            raise AppError("仅零件图可设置焦点", code="invalid_request")
        image.focus_point = {
            "x": float(item.x),
            "y": float(item.y),
            "source": (item.source or "user_tap")[:32],
        }
        await image.save()
    logger.info(
        "Saved image focus points | public_id=%s | count=%s",
        session.public_id,
        len(payload.items),
    )
    return APIResponse(data=await serialize_session(session), message="已保存焦点")


@router.post("/{public_id}/start", response_model=APIResponse)
async def start_recognition(session: RecognitionSession = Depends(get_recognition_session)) -> APIResponse:
    image_count = await UploadedImage.filter(
        session_id=session.id,
        purpose__in=list(PART_PURPOSES),
        deleted_at=None,
    ).count()
    if image_count == 0:
        raise AppError("请先上传零件图片")

    session.status = "processing"
    session.error_message = None
    await session.save()
    logger.info("Start recognition | public_id=%s | images=%s", session.public_id, image_count)

    from app.tasks.dispatcher import dispatch_vision_recognition

    mode = await dispatch_vision_recognition(session.id, session.public_id)
    session = await RecognitionSession.get(id=session.id)
    logger.info(
        "Recognition dispatch finished | public_id=%s | mode=%s | status=%s",
        session.public_id,
        mode,
        session.status,
    )

    return APIResponse(
        data=await serialize_session(session),
        message="识别完成" if session.status == "done" else "识别任务已启动",
    )


@router.post("/{public_id}/confirm-category", response_model=APIResponse)
async def confirm_category(
    payload: ConfirmCategoryIn,
    session: RecognitionSession = Depends(get_recognition_session),
) -> APIResponse:
    await ensure_auto_part(session)
    session.confirmed_category_code = payload.category_code
    session.confirmed_category_name = payload.category_name
    session.optimization_consent = payload.optimization_consent
    from datetime import datetime

    if payload.optimization_consent:
        session.optimization_consent_at = datetime.utcnow()
    else:
        session.optimization_consent_at = None
    await session.save()
    logger.info(
        "Confirm category | public_id=%s | code=%s | name=%s | consent=%s",
        session.public_id,
        payload.category_code,
        payload.category_name,
        payload.optimization_consent,
    )
    await AuditLog.create(
        actor_type="device",
        actor_id=str(session.device_session_id),
        action="session.confirm_category",
        resource_type="recognition_session",
        resource_id=session.public_id,
        detail=payload.model_dump(),
    )
    return APIResponse(data=await serialize_session(session))


@router.post("/{public_id}/consent", response_model=APIResponse)
async def set_consent(
    payload: ConsentIn,
    session: RecognitionSession = Depends(get_recognition_session),
) -> APIResponse:
    from datetime import datetime

    session.optimization_consent = payload.optimization_consent
    session.optimization_consent_at = datetime.utcnow() if payload.optimization_consent else None
    await session.save()
    await AuditLog.create(
        actor_type="device",
        actor_id=str(session.device_session_id),
        action="session.consent_set" if payload.optimization_consent else "session.consent_revoke",
        resource_type="recognition_session",
        resource_id=session.public_id,
        detail={"optimization_consent": payload.optimization_consent},
    )
    return APIResponse(data=await serialize_session(session), message="授权已更新")


@router.post("/{public_id}/consent/revoke", response_model=APIResponse)
async def revoke_consent(session: RecognitionSession = Depends(get_recognition_session)) -> APIResponse:
    session.optimization_consent = False
    session.optimization_consent_at = None
    await session.save()
    await AuditLog.create(
        actor_type="device",
        actor_id=str(session.device_session_id),
        action="session.consent_revoke",
        resource_type="recognition_session",
        resource_id=session.public_id,
        detail={"optimization_consent": False},
    )
    return APIResponse(data=await serialize_session(session), message="已撤回优化授权")


@router.post("/{public_id}/vehicle", response_model=APIResponse)
async def set_vehicle_filter(
    payload: VehicleFilterIn,
    session: RecognitionSession = Depends(get_recognition_session),
) -> APIResponse:
    await ensure_auto_part(session)
    session.vehicle_brand = _blank_to_none(payload.brand)
    session.vehicle_series = _blank_to_none(payload.series)
    session.vehicle_model = _blank_to_none(payload.model)
    session.vehicle_year = _blank_to_none(payload.year)
    oe_number = _blank_to_none(payload.oe_number)
    if oe_number:
        session.oe_number = oe_number.upper()
        session.oe_source = payload.oe_source or "manual"
    else:
        session.oe_number = None
        session.oe_source = None
    await session.save()
    logger.info(
        "Set vehicle filter | public_id=%s | brand=%s | series=%s | model=%s | year=%s | oe=%s",
        session.public_id,
        payload.brand,
        payload.series,
        payload.model,
        payload.year,
        session.oe_number,
    )
    return APIResponse(data=await serialize_session(session))


@router.post("/{public_id}/oe-ocr", response_model=APIResponse)
async def oe_ocr_from_latest_label(session: RecognitionSession = Depends(get_recognition_session)) -> APIResponse:
    await ensure_auto_part(session)
    image = await UploadedImage.filter(
        session_id=session.id, purpose=OE_LABEL_PURPOSE, deleted_at=None
    ).order_by("-id").first()
    if not image:
        raise AppError("请先上传铭牌/包装图片")
    logger.info("OE OCR start | public_id=%s | image_id=%s", session.public_id, image.id)
    record = await run_oe_ocr(session.id, image.id)
    logger.info(
        "OE OCR done | public_id=%s | candidates=%s | confidence=%s",
        session.public_id,
        record.oe_numbers,
        record.confidence,
    )
    return APIResponse(
        data={
            "oe_numbers": record.oe_numbers or [],
            "confidence": record.confidence,
            "reason": record.reason,
            "ocr_id": record.id,
        },
        message="请确认 OE 号后再查询",
    )


@router.post("/{public_id}/oe-confirm", response_model=APIResponse)
async def confirm_oe(
    payload: OeConfirmIn,
    session: RecognitionSession = Depends(get_recognition_session),
) -> APIResponse:
    await ensure_auto_part(session)
    session.oe_number = payload.oe_number.strip().upper()
    session.oe_source = "ocr"
    await session.save()
    latest = await OeOcrResult.filter(session_id=session.id).order_by("-id").first()
    if latest:
        latest.confirmed_oe = session.oe_number
        await latest.save()
    logger.info("Confirm OE | public_id=%s | oe=%s", session.public_id, session.oe_number)
    return APIResponse(data=await serialize_session(session))


@router.get("/{public_id}/products", response_model=APIResponse)
async def search_products(session: RecognitionSession = Depends(get_recognition_session)) -> APIResponse:
    await ensure_auto_part(session)
    logger.info("Search products | public_id=%s", session.public_id)
    payload = await catalog_service.search_for_session(session)
    logger.info("Search products done | public_id=%s | count=%s", session.public_id, len(payload))
    return APIResponse(data=payload)


@router.post("/{public_id}/feedback", response_model=APIResponse)
async def submit_feedback(
    payload: FeedbackIn,
    session: RecognitionSession = Depends(get_recognition_session),
) -> APIResponse:
    session.feedback_correct = payload.correct
    session.feedback_note = payload.note
    await session.save()
    logger.info(
        "Feedback | public_id=%s | correct=%s | note=%s",
        session.public_id,
        payload.correct,
        payload.note,
    )
    await AuditLog.create(
        actor_type="device",
        actor_id=str(session.device_session_id),
        action="session.feedback",
        resource_type="recognition_session",
        resource_id=session.public_id,
        detail=payload.model_dump(),
    )
    return APIResponse(message="感谢反馈")
