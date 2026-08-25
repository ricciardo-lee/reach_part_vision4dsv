from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from tortoise.functions import Avg

from app.api.deps import require_permission
from app.models import (
    AdminUser,
    AuditLog,
    CategoryMapping,
    PromptConfig,
    RecognitionResult,
    RecognitionSession,
)
from app.schemas import (
    APIResponse,
    AuditLogOut,
    CategoryMappingIn,
    CategoryMappingOut,
    PromptConfigIn,
    PromptConfigOut,
    StatsOut,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.services.eval_metrics import compute_eval_stats
from app.tasks.dispatcher import dispatch_vision_recognition

router = APIRouter(tags=["admin"])


@router.get("/stats", response_model=APIResponse)
async def stats(admin: AdminUser = Depends(require_permission("stats:read"))) -> APIResponse:
    total = await RecognitionSession.all().count()
    success = await RecognitionSession.filter(status="done").count()
    failed = await RecognitionSession.filter(status="failed").count()
    avg_conf = await RecognitionResult.filter(success=True).annotate(v=Avg("confidence")).values("v")
    avg_value = avg_conf[0]["v"] if avg_conf else None
    feedback_total = await RecognitionSession.exclude(feedback_correct=None).count()
    feedback_correct = await RecognitionSession.filter(feedback_correct=True).count()
    rate = (feedback_correct / feedback_total) if feedback_total else None
    eval_stats = await compute_eval_stats(reject_confidence=settings.EVAL_REJECT_CONFIDENCE)
    return APIResponse(
        data=StatsOut(
            total_sessions=total,
            success_sessions=success,
            failed_sessions=failed,
            avg_confidence=round(float(avg_value), 4) if avg_value is not None else None,
            feedback_correct_rate=round(rate, 4) if rate is not None else None,
            top1_hit_rate=eval_stats.top1_hit_rate,
            top3_hit_rate=eval_stats.top3_hit_rate,
            reject_rate=eval_stats.reject_rate,
            labeled_sessions=eval_stats.labeled_sessions,
        )
    )


@router.get("/sessions", response_model=APIResponse)
async def list_sessions(
    status: Optional[str] = None,
    feedback_correct: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: AdminUser = Depends(require_permission("session:read")),
) -> APIResponse:
    query = RecognitionSession.all().order_by("-id")
    if status:
        query = query.filter(status=status)
    if feedback_correct is not None:
        query = query.filter(feedback_correct=feedback_correct)
    total = await query.count()
    items = await query.offset((page - 1) * page_size).limit(page_size)
    data = []
    for item in items:
        latest = await RecognitionResult.filter(session_id=item.id).order_by("-id").first()
        data.append(
            {
                "public_id": item.public_id,
                "status": item.status,
                "task_id": item.task_id,
                "confirmed_category_name": item.confirmed_category_name,
                "oe_number": item.oe_number,
                "part_name": latest.part_name if latest else None,
                "confidence": latest.confidence if latest else None,
                "created_at": item.created_at,
                "error_message": item.error_message,
                "feedback_correct": item.feedback_correct,
            }
        )
    return APIResponse(data={"total": total, "items": data})


@router.get("/sessions/{public_id}", response_model=APIResponse)
async def session_detail(
    public_id: str,
    admin: AdminUser = Depends(require_permission("session:read")),
) -> APIResponse:
    session = await RecognitionSession.get_or_none(public_id=public_id)
    if not session:
        raise NotFoundError()
    results = await RecognitionResult.filter(session_id=session.id).order_by("-id")
    return APIResponse(
        data={
            "session": {
                "public_id": session.public_id,
                "status": session.status,
                "confirmed_category_code": session.confirmed_category_code,
                "confirmed_category_name": session.confirmed_category_name,
                "vehicle_brand": session.vehicle_brand,
                "vehicle_series": session.vehicle_series,
                "vehicle_model": session.vehicle_model,
                "vehicle_year": session.vehicle_year,
                "oe_number": session.oe_number,
                "oe_source": session.oe_source,
                "optimization_consent": session.optimization_consent,
                "feedback_correct": session.feedback_correct,
                "feedback_note": session.feedback_note,
                "task_id": session.task_id,
                "error_message": session.error_message,
                "created_at": session.created_at,
            },
            "results": [
                {
                    "id": r.id,
                    "part_name": r.part_name,
                    "confidence": r.confidence,
                    "reason": r.reason,
                    "candidates": r.candidates,
                    "mapped_category_code": r.mapped_category_code,
                    "mapped_category_name": r.mapped_category_name,
                    "success": r.success,
                    "latency_ms": r.latency_ms,
                    "error_message": r.error_message,
                    "created_at": r.created_at,
                }
                for r in results
            ],
        }
    )


@router.post("/sessions/{public_id}/retry", response_model=APIResponse)
async def retry_session(
    public_id: str,
    admin: AdminUser = Depends(require_permission("session:retry")),
) -> APIResponse:
    session = await RecognitionSession.get_or_none(public_id=public_id)
    if not session:
        raise NotFoundError()
    session.status = "processing"
    session.error_message = None
    await session.save()
    mode = await dispatch_vision_recognition(session.id, session.public_id)
    session = await RecognitionSession.get(id=session.id)
    await AuditLog.create(
        actor_type="admin",
        actor_id=str(admin.id),
        action="session.retry",
        resource_type="recognition_session",
        resource_id=public_id,
        detail={"mode": mode, "task_id": session.task_id},
    )
    return APIResponse(
        message="识别任务已重新提交" if mode == "celery" else "已重新识别",
        data={"mode": mode, "task_id": session.task_id, "status": session.status},
    )


@router.get("/mappings", response_model=APIResponse)
async def list_mappings(admin: AdminUser = Depends(require_permission("mapping:read"))) -> APIResponse:
    items = await CategoryMapping.all().order_by("-priority", "alias_name")
    return APIResponse(data=[CategoryMappingOut.model_validate(i).model_dump() for i in items])


@router.post("/mappings", response_model=APIResponse)
async def create_mapping(
    payload: CategoryMappingIn,
    admin: AdminUser = Depends(require_permission("mapping:write")),
) -> APIResponse:
    item = await CategoryMapping.create(**payload.model_dump())
    await AuditLog.create(
        actor_type="admin",
        actor_id=str(admin.id),
        action="mapping.create",
        resource_type="category_mapping",
        resource_id=str(item.id),
        detail=payload.model_dump(),
    )
    return APIResponse(data=CategoryMappingOut.model_validate(item).model_dump())


@router.put("/mappings/{mapping_id}", response_model=APIResponse)
async def update_mapping(
    mapping_id: int,
    payload: CategoryMappingIn,
    admin: AdminUser = Depends(require_permission("mapping:write")),
) -> APIResponse:
    item = await CategoryMapping.get_or_none(id=mapping_id)
    if not item:
        raise NotFoundError()
    await item.update_from_dict(payload.model_dump()).save()
    await AuditLog.create(
        actor_type="admin",
        actor_id=str(admin.id),
        action="mapping.update",
        resource_type="category_mapping",
        resource_id=str(item.id),
        detail=payload.model_dump(),
    )
    return APIResponse(data=CategoryMappingOut.model_validate(item).model_dump())


@router.delete("/mappings/{mapping_id}", response_model=APIResponse)
async def delete_mapping(
    mapping_id: int,
    admin: AdminUser = Depends(require_permission("mapping:write")),
) -> APIResponse:
    item = await CategoryMapping.get_or_none(id=mapping_id)
    if not item:
        raise NotFoundError()
    await item.delete()
    return APIResponse(message="已删除")


@router.get("/prompts", response_model=APIResponse)
async def list_prompts(admin: AdminUser = Depends(require_permission("prompt:read"))) -> APIResponse:
    items = await PromptConfig.all().order_by("-id")
    return APIResponse(data=[PromptConfigOut.model_validate(i).model_dump() for i in items])


@router.post("/prompts", response_model=APIResponse)
async def create_prompt(
    payload: PromptConfigIn,
    admin: AdminUser = Depends(require_permission("prompt:write")),
) -> APIResponse:
    item = await PromptConfig.create(**payload.model_dump())
    await AuditLog.create(
        actor_type="admin",
        actor_id=str(admin.id),
        action="prompt.create",
        resource_type="prompt_config",
        resource_id=str(item.id),
        detail={"name": payload.name, "version": payload.version},
    )
    return APIResponse(data=PromptConfigOut.model_validate(item).model_dump())


@router.put("/prompts/{prompt_id}", response_model=APIResponse)
async def update_prompt(
    prompt_id: int,
    payload: PromptConfigIn,
    admin: AdminUser = Depends(require_permission("prompt:write")),
) -> APIResponse:
    item = await PromptConfig.get_or_none(id=prompt_id)
    if not item:
        raise NotFoundError()
    await item.update_from_dict(payload.model_dump()).save()
    return APIResponse(data=PromptConfigOut.model_validate(item).model_dump())


@router.get("/audit-logs", response_model=APIResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: AdminUser = Depends(require_permission("audit:read")),
) -> APIResponse:
    query = AuditLog.all().order_by("-id")
    total = await query.count()
    items = await query.offset((page - 1) * page_size).limit(page_size)
    return APIResponse(
        data={
            "total": total,
            "items": [AuditLogOut.model_validate(i).model_dump() for i in items],
        }
    )


@router.get("/users", response_model=APIResponse)
async def list_users(admin: AdminUser = Depends(require_permission("user:read"))) -> APIResponse:
    users = await AdminUser.all().order_by("id")
    return APIResponse(
        data=[
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "role": u.role,
                "is_active": u.is_active,
                "last_login_at": u.last_login_at,
            }
            for u in users
        ]
    )
