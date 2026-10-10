from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query
from tortoise.functions import Avg

from app.api.deps import require_permission
from app.core.constants import CATEGORY_CN
from app.models import (
    AdminUser,
    AppUser,
    AuditLog,
    CategoryMapping,
    ProductQuerySnapshot,
    PromptConfig,
    RecognitionResult,
    RecognitionSession,
    RetrievalResult,
)
from app.schemas import (
    APIResponse,
    AppUserCreateIn,
    AppUserOut,
    AppUserPasswordIn,
    AppUserUpdateIn,
    AuditLogOut,
    CategoryMappingIn,
    CategoryMappingOut,
    PromptConfigIn,
    PromptConfigOut,
    StatsOut,
)
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.security import hash_password
from app.services.eval_metrics import compute_eval_stats
from app.tasks.dispatcher import dispatch_vision_recognition

router = APIRouter(tags=["admin"])


def _recognition_mode(
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


def _category_from_retrieval(retrieval: RetrievalResult | None) -> str | None:
    if not retrieval:
        return None
    if getattr(retrieval, "selected_category_cn", None):
        return retrieval.selected_category_cn
    if getattr(retrieval, "selected_category_id", None):
        return CATEGORY_CN.get(retrieval.selected_category_id, retrieval.selected_category_id)
    candidates = retrieval.candidates or []
    if not candidates:
        return None
    top = candidates[0] if isinstance(candidates[0], dict) else {}
    return (
        top.get("category_cn")
        or CATEGORY_CN.get(str(top.get("category_id") or ""), None)
        or top.get("category_id")
    )


def _serialize_retrieval(r: RetrievalResult) -> dict[str, Any]:
    return {
        "id": r.id,
        "accepted": bool(r.accepted),
        "decision": r.decision,
        "confidence_level": r.confidence_level,
        "matched_sku": r.matched_sku,
        "score": r.score,
        "margin": r.margin,
        "selected_category_id": getattr(r, "selected_category_id", None),
        "selected_category_cn": getattr(r, "selected_category_cn", None),
        "category_confidence": getattr(r, "category_confidence", None),
        "vision_assisted": bool(getattr(r, "vision_assisted", False)),
        "candidates": r.candidates or [],
        "fallback_reason": r.fallback_reason,
        "index_version": r.index_version,
        "embedding_model": r.embedding_model,
        "latency_ms": r.latency_ms,
        "image_count": r.image_count,
        "quality_warnings": r.quality_warnings,
        "success": r.success,
        "error_message": r.error_message,
        "created_at": r.created_at,
    }


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

    # SKU / category match stats among done sessions.
    done_sessions = await RecognitionSession.filter(status="done").all()
    sku_match_sessions = 0
    category_match_sessions = 0
    vision_fallback_sessions = 0
    for session in done_sessions:
        retrieval = await RetrievalResult.filter(session_id=session.id).order_by("-id").first()
        vision = await RecognitionResult.filter(session_id=session.id, success=True).order_by("-id").first()
        mode = _recognition_mode(retrieval, vision)
        if mode == "sku_match":
            sku_match_sessions += 1
        elif mode == "category_match":
            category_match_sessions += 1
        elif mode == "vision_fallback":
            vision_fallback_sessions += 1
    sku_match_rate = (sku_match_sessions / success) if success else None
    category_match_rate = (category_match_sessions / success) if success else None

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
            sku_match_sessions=sku_match_sessions,
            category_match_sessions=category_match_sessions,
            vision_fallback_sessions=vision_fallback_sessions,
            sku_match_rate=round(sku_match_rate, 4) if sku_match_rate is not None else None,
            category_match_rate=round(category_match_rate, 4) if category_match_rate is not None else None,
        )
    )


@router.get("/sessions", response_model=APIResponse)
async def list_sessions(
    status: Optional[str] = None,
    feedback_correct: Optional[bool] = None,
    recognition_mode: Annotated[
        Optional[str],
        Query(description="sku_match | category_match | vision_fallback"),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    admin: AdminUser = Depends(require_permission("session:read")),
) -> APIResponse:
    query = RecognitionSession.all().order_by("-id")
    if status:
        query = query.filter(status=status)
    if feedback_correct is not None:
        query = query.filter(feedback_correct=feedback_correct)

    # Mode filter requires per-session retrieval/vision; filter after fetch when set.
    if recognition_mode in {"sku_match", "category_match", "vision_fallback"}:
        candidates = await query.all()
        filtered: list[RecognitionSession] = []
        for item in candidates:
            retrieval = await RetrievalResult.filter(session_id=item.id).order_by("-id").first()
            vision = await RecognitionResult.filter(session_id=item.id, success=True).order_by("-id").first()
            if _recognition_mode(retrieval, vision) == recognition_mode:
                filtered.append(item)
        total = len(filtered)
        items = filtered[(page - 1) * page_size : page * page_size]
    else:
        total = await query.count()
        items = await query.offset((page - 1) * page_size).limit(page_size)

    user_labels = await _app_user_labels({item.app_user_id for item in items if item.app_user_id})
    data = []
    for item in items:
        latest = await RecognitionResult.filter(session_id=item.id).order_by("-id").first()
        retrieval = await RetrievalResult.filter(session_id=item.id).order_by("-id").first()
        mode = _recognition_mode(retrieval, latest if latest and latest.success else None)
        if mode == "sku_match" and retrieval:
            part_name = item.confirmed_category_name or _category_from_retrieval(retrieval)
            confidence = retrieval.score
        elif mode == "category_match" and retrieval:
            part_name = (
                item.confirmed_category_name
                or retrieval.selected_category_cn
                or _category_from_retrieval(retrieval)
            )
            confidence = retrieval.category_confidence or retrieval.score
        else:
            part_name = latest.part_name if latest else None
            confidence = latest.confidence if latest else None
        owner = user_labels.get(item.app_user_id) or {}
        data.append(
            {
                "public_id": item.public_id,
                "username": owner.get("username"),
                "display_name": owner.get("display_name"),
                "status": item.status,
                "task_id": item.task_id,
                "confirmed_category_name": item.confirmed_category_name,
                "oe_number": item.oe_number,
                "part_name": part_name,
                "confidence": confidence,
                "recognition_mode": mode,
                "matched_sku": retrieval.matched_sku if retrieval and retrieval.accepted else None,
                "selected_category_id": getattr(retrieval, "selected_category_id", None) if retrieval else None,
                "selected_category_cn": getattr(retrieval, "selected_category_cn", None) if retrieval else None,
                "vision_assisted": bool(getattr(retrieval, "vision_assisted", False)) if retrieval else False,
                "retrieval_score": retrieval.score if retrieval else None,
                "retrieval_margin": retrieval.margin if retrieval else None,
                "retrieval_accepted": bool(retrieval.accepted) if retrieval else False,
                "fallback_reason": retrieval.fallback_reason if retrieval else None,
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
    retrievals = await RetrievalResult.filter(session_id=session.id).order_by("-id")
    latest_vision = next((r for r in results if r.success), None)
    latest_retrieval = retrievals[0] if retrievals else None
    mode = _recognition_mode(latest_retrieval, latest_vision)
    snapshot = await ProductQuerySnapshot.filter(session_id=session.id).order_by("-id").first()
    owner = (await _app_user_labels({session.app_user_id} if session.app_user_id else set())).get(
        session.app_user_id
    ) or {}
    return APIResponse(
        data={
            "recognition_mode": mode,
            "session": {
                "public_id": session.public_id,
                "username": owner.get("username"),
                "display_name": owner.get("display_name"),
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
            "retrieval_results": [_serialize_retrieval(r) for r in retrievals],
            "product_snapshot": (
                {
                    "query_payload": snapshot.query_payload,
                    "result_payload": snapshot.result_payload,
                    "result_count": snapshot.result_count,
                    "created_at": snapshot.created_at,
                }
                if snapshot
                else None
            ),
            "results": [
                {
                    "id": r.id,
                    "model_name": r.model_name,
                    "prompt_version": r.prompt_version,
                    "part_name": r.part_name,
                    "confidence": r.confidence,
                    "reason": r.reason,
                    "candidates": r.candidates,
                    "mapped_category_code": r.mapped_category_code,
                    "mapped_category_name": r.mapped_category_name,
                    "is_auto_part": r.is_auto_part,
                    "raw_response": r.raw_response,
                    "token_usage": r.token_usage,
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


def _app_user_out(user: AppUser) -> dict:
    return AppUserOut.model_validate(user).model_dump()


async def _app_user_labels(user_ids: set[int]) -> dict[int, dict[str, str]]:
    if not user_ids:
        return {}
    users = await AppUser.filter(id__in=list(user_ids))
    return {user.id: {"username": user.username, "display_name": user.display_name} for user in users}


def _clean_username(username: str) -> str:
    value = username.strip()
    if not value or len(value) > 64:
        raise AppError("用户名长度需为 1–64 个字符")
    return value


@router.get("/app-users", response_model=APIResponse)
async def list_app_users(admin: AdminUser = Depends(require_permission("user:read"))) -> APIResponse:
    users = await AppUser.all().order_by("id")
    return APIResponse(data=[_app_user_out(user) for user in users])


@router.post("/app-users", response_model=APIResponse)
async def create_app_user(
    payload: AppUserCreateIn,
    admin: AdminUser = Depends(require_permission("user:write")),
) -> APIResponse:
    username = _clean_username(payload.username)
    if await AppUser.get_or_none(username=username):
        raise AppError("用户名已存在")
    user = await AppUser.create(
        username=username,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or "").strip(),
        is_active=True,
    )
    await AuditLog.create(
        actor_type="admin",
        actor_id=str(admin.id),
        action="app_user.create",
        resource_type="app_user",
        resource_id=str(user.id),
        detail={"username": user.username},
    )
    return APIResponse(data=_app_user_out(user))


@router.patch("/app-users/{user_id}", response_model=APIResponse)
async def update_app_user(
    user_id: int,
    payload: AppUserUpdateIn,
    admin: AdminUser = Depends(require_permission("user:write")),
) -> APIResponse:
    user = await AppUser.get_or_none(id=user_id)
    if not user:
        raise NotFoundError("识别用户不存在")
    changes: dict = {}
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
        changes["display_name"] = user.display_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = user.is_active
    if changes:
        await user.save()
        await AuditLog.create(
            actor_type="admin",
            actor_id=str(admin.id),
            action="app_user.update",
            resource_type="app_user",
            resource_id=str(user.id),
            detail=changes,
        )
    return APIResponse(data=_app_user_out(user))


@router.post("/app-users/{user_id}/password", response_model=APIResponse)
async def reset_app_user_password(
    user_id: int,
    payload: AppUserPasswordIn,
    admin: AdminUser = Depends(require_permission("user:write")),
) -> APIResponse:
    user = await AppUser.get_or_none(id=user_id)
    if not user:
        raise NotFoundError("识别用户不存在")
    user.password_hash = hash_password(payload.password)
    await user.save()
    await AuditLog.create(
        actor_type="admin",
        actor_id=str(admin.id),
        action="app_user.reset_password",
        resource_type="app_user",
        resource_id=str(user.id),
        detail={"username": user.username},
    )
    return APIResponse(data=_app_user_out(user))
