from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.config import settings
from app.core.exceptions import AppError
from app.api.deps import get_device_session, get_recognition_session
from app.integrations.mdm.client import mdm_adapter
from app.models import (
    AuditLog,
    DeviceSession,
    OeOcrResult,
    ProductQuerySnapshot,
    RecognitionResult,
    RecognitionSession,
    UploadedImage,
)
from app.schemas import (
    APIResponse,
    ConfirmCategoryIn,
    ConsentIn,
    FeedbackIn,
    ImageOut,
    OeConfirmIn,
    ProductOut,
    RecognitionResultOut,
    RecognitionSessionOut,
    VehicleFilterIn,
)
from app.services.bootstrap import image_expiry, new_public_id
from app.services.part_guard import ensure_auto_part, session_is_auto_part
from app.services.recognition import run_oe_ocr, run_vision_recognition
from app.utils.images import compress_to_jpeg_bytes, compute_phash, validate_image_meta
from app.utils.minio_client import get_storage

logger = logging.getLogger("app.api.recognize")

router = APIRouter(prefix="/recognize", tags=["public-recognize"])

PART_PURPOSES = {"part", "part_overall", "part_connector", "part_label", "part_other"}


def _progress_hint(status: str, *, is_auto_part: bool = True) -> str:
    if status == "done" and not is_auto_part:
        return "未识别到汽配零件，请重新拍摄"
    mapping = {
        "created": "等待上传",
        "uploading": "图片已上传，准备识别",
        "processing": "识别中，请稍候",
        "done": "识别完成",
        "failed": "识别失败，可重试",
    }
    return mapping.get(status, status)


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
        image_out.append(
            ImageOut(
                id=image.id,
                object_key=image.object_key,
                purpose=image.purpose,
                sort_order=image.sort_order,
                preview_url=preview,
            )
        )

    latest = await RecognitionResult.filter(session_id=session.id, success=True).order_by("-id").first()
    is_auto_part = await session_is_auto_part(session)
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

    return RecognitionSessionOut(
        public_id=session.public_id,
        status=session.status,
        progress_hint=_progress_hint(session.status, is_auto_part=is_auto_part),
        is_auto_part=is_auto_part,
        images=image_out,
        result=result_out,
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
    purpose: str = Form("part"),
    sort_order: int = Form(0),
) -> APIResponse:
    if purpose not in PART_PURPOSES and purpose != "oe_label":
        raise AppError("purpose 仅支持 part / part_overall / part_connector / part_label / part_other / oe_label")

    existing = await UploadedImage.filter(session_id=session.id, purpose=purpose, deleted_at=None).count()
    if purpose == "oe_label":
        max_count = 1
    elif purpose in PART_PURPOSES - {"part"}:
        max_count = 1  # one image per angle slot
    else:
        max_count = settings.MAX_IMAGES_PER_SESSION
    if existing + len(files) > max_count:
        raise AppError(f"该用途最多上传 {max_count} 张图片")

    # Cap total part images across all part* purposes
    if purpose in PART_PURPOSES:
        part_total = await UploadedImage.filter(
            session_id=session.id,
            purpose__in=list(PART_PURPOSES),
            deleted_at=None,
        ).count()
        if part_total + len(files) > settings.MAX_IMAGES_PER_SESSION:
            raise AppError(f"零件图合计最多上传 {settings.MAX_IMAGES_PER_SESSION} 张")

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
        order = sort_order if purpose != "part" else existing + index
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
    session.vehicle_brand = payload.brand
    session.vehicle_series = payload.series
    session.vehicle_model = payload.model
    session.vehicle_year = payload.year
    if payload.oe_number:
        session.oe_number = payload.oe_number.strip().upper()
        session.oe_source = payload.oe_source or "manual"
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
    image = await UploadedImage.filter(session_id=session.id, purpose="oe_label", deleted_at=None).order_by("-id").first()
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
    if not session.confirmed_category_name and not session.oe_number:
        raise AppError("请先确认品类或输入 OE 号")

    latest_ocr = await OeOcrResult.filter(session_id=session.id).order_by("-id").first()
    if session.oe_source == "ocr" and latest_ocr and not latest_ocr.confirmed_oe:
        raise AppError("请先确认铭牌识别出的 OE 号后再查询产品")

    query = {
        "category_name": session.confirmed_category_name,
        "category_code": session.confirmed_category_code,
        "brand": session.vehicle_brand,
        "series": session.vehicle_series,
        "model": session.vehicle_model,
        "year": session.vehicle_year,
        "oe_number": session.oe_number,
    }
    logger.info("Search products | public_id=%s | query=%s", session.public_id, query)
    products = await mdm_adapter.search_products(**query)
    payload = [ProductOut(**p.model_dump()).model_dump() for p in products]
    await ProductQuerySnapshot.create(
        session_id=session.id,
        query_payload=query,
        result_payload=payload,
        result_count=len(payload),
    )
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
