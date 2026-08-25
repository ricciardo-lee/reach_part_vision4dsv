from __future__ import annotations

from typing import Any, Optional

from app.core.exceptions import AppError
from app.models import RecognitionResult, RecognitionSession

NON_PART_KEYWORDS = (
    "非汽配",
    "非零件",
    "不是零件",
    "不是汽配",
    "非汽车零件",
    "非车用",
    "整车",
    "人物",
    "人脸",
    "风景",
    "建筑",
    "手机",
    "电脑",
    "食品",
    "动物",
    "文档",
    "截图",
    "无关",
)

NON_PART_PART_NAMES = {
    "非汽配",
    "非汽车零件",
    "非零件",
    "无法识别",
    "未知物体",
    "其他物体",
}


def parse_is_auto_part(payload: Any, *, part_name: str = "", confidence: Optional[float] = None) -> bool:
    """Return True when the vision result is an auto part."""
    if isinstance(payload, dict) and "is_auto_part" in payload:
        raw = payload.get("is_auto_part")
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"true", "1", "yes", "y", "是", "汽配", "零件"}:
                return True
            if normalized in {"false", "0", "no", "n", "否", "非汽配", "非零件"}:
                return False
        return bool(raw)

    name = (part_name or "").strip()
    if not name:
        return False
    if name in NON_PART_PART_NAMES:
        return False
    if any(keyword in name for keyword in NON_PART_KEYWORDS):
        return False
    if name in {"未知零件", "未知"} and (confidence or 0) < 0.35:
        return False
    return True


async def latest_success_result(session_id: int) -> Optional[RecognitionResult]:
    return await RecognitionResult.filter(session_id=session_id, success=True).order_by("-id").first()


async def session_is_auto_part(session: RecognitionSession) -> bool:
    result = await latest_success_result(session.id)
    if not result:
        return True
    if result.is_auto_part is not None:
        return bool(result.is_auto_part)
    return parse_is_auto_part(
        result.raw_response or {},
        part_name=result.part_name or "",
        confidence=result.confidence,
    )


async def ensure_auto_part(session: RecognitionSession) -> None:
    if not await session_is_auto_part(session):
        result = await latest_success_result(session.id)
        reason = (result.reason if result else None) or "图片内容不是汽配零件，请重新拍摄零件照片"
        raise AppError(reason, code="not_auto_part", status_code=400)
