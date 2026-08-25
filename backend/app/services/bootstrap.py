from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.core.constants import ROLE_SUPERADMIN
from app.core.security import hash_password
from app.models import AdminUser, CategoryMapping, PromptConfig
from app.core.constants import DEFAULT_OE_OCR_PROMPT, DEFAULT_VISION_PROMPT


async def ensure_schema_patches() -> None:
    """Apply lightweight schema patches for existing deployments (no aerich migration yet)."""
    from tortoise import Tortoise

    conn = Tortoise.get_connection("default")
    _, rows = await conn.execute_query(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'recognition_results' "
        "AND COLUMN_NAME = 'is_auto_part'"
    )
    row = rows[0] if rows else {}
    count = row.get("c", 0) if isinstance(row, dict) else (row[0] if row else 0)
    if not count:
        await conn.execute_script(
            "ALTER TABLE recognition_results ADD COLUMN is_auto_part TINYINT(1) NULL"
        )


async def ensure_bootstrap_data() -> None:
    await ensure_schema_patches()
    admin = await AdminUser.get_or_none(username=settings.ADMIN_USERNAME)
    if not admin:
        await AdminUser.create(
            username=settings.ADMIN_USERNAME,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            display_name=settings.ADMIN_DISPLAY_NAME,
            role=ROLE_SUPERADMIN,
            is_active=True,
        )

    vision = await PromptConfig.get_or_none(name="default_vision")
    if not vision:
        await PromptConfig.create(
            name="default_vision",
            version="v2",
            purpose="vision",
            content=DEFAULT_VISION_PROMPT,
            is_active=True,
            note="初始视觉识别 Prompt（含 is_auto_part）",
        )
    elif "is_auto_part" not in (vision.content or ""):
        vision.version = "v2"
        vision.content = DEFAULT_VISION_PROMPT
        vision.is_active = True
        vision.note = "自动升级：增加 is_auto_part 非汽配识别"
        await vision.save()
        await PromptConfig.filter(purpose="vision").exclude(id=vision.id).update(is_active=False)

    oe = await PromptConfig.get_or_none(name="default_oe_ocr")
    if not oe:
        await PromptConfig.create(
            name="default_oe_ocr",
            version="v1",
            purpose="oe_ocr",
            content=DEFAULT_OE_OCR_PROMPT,
            is_active=True,
            note="初始 OE 铭牌识别 Prompt",
        )

    defaults = [
        ("散热器", "RADIATOR", "散热器"),
        ("水箱", "RADIATOR", "散热器"),
        ("冷凝器", "CONDENSER", "冷凝器"),
        ("中冷器", "INTERCOOLER", "中冷器"),
        ("压缩机", "COMPRESSOR", "空调压缩机"),
        ("空调压缩机", "COMPRESSOR", "空调压缩机"),
        ("蒸发器", "EVAPORATOR", "蒸发器"),
        ("机油冷却器", "OIL_COOLER", "机油冷却器"),
        ("风扇", "FAN", "冷却风扇"),
        ("冷却风扇", "FAN", "冷却风扇"),
    ]
    for alias, code, name in defaults:
        exists = await CategoryMapping.get_or_none(alias_name=alias)
        if not exists:
            await CategoryMapping.create(
                alias_name=alias,
                category_code=code,
                category_name=name,
                is_active=True,
                priority=10,
            )


def new_public_id() -> str:
    return str(uuid.uuid4())


def new_token() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


def image_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=settings.IMAGE_RETENTION_DAYS)
