from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.core.constants import ROLE_SUPERADMIN
from app.core.security import hash_password
from app.models import AdminUser, CategoryMapping, PromptConfig
from app.core.constants import DEFAULT_OE_OCR_PROMPT, DEFAULT_VISION_PROMPT


def _count_from_rows(rows) -> int:
    row = rows[0] if rows else {}
    value = row.get("c", 0) if isinstance(row, dict) else (row[0] if row else 0)
    return int(value or 0)


async def _column_names(conn, table: str) -> set[str]:
    _, rows = await conn.execute_query(
        "SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS "
        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}'"
    )
    names: set[str] = set()
    for row in rows:
        names.add(row.get("c") if isinstance(row, dict) else row[0])
    return names


async def _id_data_type(conn, table: str) -> str:
    _, rows = await conn.execute_query(
        "SELECT DATA_TYPE AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '"
        + table
        + "' AND COLUMN_NAME = 'id'"
    )
    if not rows:
        return ""
    row = rows[0]
    value = row.get("c") if isinstance(row, dict) else row[0]
    return str(value or "").lower()


async def _copy_integer_pk_rows(conn, legacy: str, current: str, columns: list[str]) -> None:
    """Move rows from this app's old table when a shared DB reused the name."""
    if await _id_data_type(conn, legacy) not in {"int", "bigint", "integer", "mediumint", "smallint"}:
        return
    current_cols = await _column_names(conn, current)
    legacy_cols = await _column_names(conn, legacy)
    if not current_cols or not legacy_cols:
        return
    _, current_rows = await conn.execute_query(f"SELECT COUNT(*) AS c FROM {current}")
    if _count_from_rows(current_rows):
        return
    _, legacy_rows = await conn.execute_query(f"SELECT COUNT(*) AS c FROM {legacy}")
    if not _count_from_rows(legacy_rows):
        return
    shared = [column for column in columns if column in legacy_cols and column in current_cols]
    if "id" not in shared:
        return
    col_sql = ", ".join(shared)
    await conn.execute_script(f"INSERT INTO {current} ({col_sql}) SELECT {col_sql} FROM {legacy}")


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

    # retrieval_results is created via generate_schemas=True on fresh DBs;
    # ensure table exists for older deployments that already have schemas.
    _, table_rows = await conn.execute_query(
        "SELECT COUNT(*) AS c FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'retrieval_results'"
    )
    table_row = table_rows[0] if table_rows else {}
    table_count = (
        table_row.get("c", 0) if isinstance(table_row, dict) else (table_row[0] if table_row else 0)
    )
    if not table_count:
        await conn.execute_script(
            """
            CREATE TABLE IF NOT EXISTS retrieval_results (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              session_id INT NOT NULL,
              index_version VARCHAR(128) NULL,
              embedding_model VARCHAR(128) NULL,
              decision VARCHAR(32) NULL,
              confidence_level VARCHAR(16) NULL,
              accepted TINYINT(1) NOT NULL DEFAULT 0,
              matched_sku VARCHAR(64) NULL,
              score DOUBLE NULL,
              margin DOUBLE NULL,
              selected_category_id VARCHAR(64) NULL,
              selected_category_cn VARCHAR(128) NULL,
              category_confidence DOUBLE NULL,
              vision_assisted TINYINT(1) NOT NULL DEFAULT 0,
              candidates JSON NULL,
              quality_warnings JSON NULL,
              fallback_reason VARCHAR(128) NULL,
              latency_ms DOUBLE NULL,
              image_count INT NOT NULL DEFAULT 0,
              success TINYINT(1) NOT NULL DEFAULT 0,
              error_message VARCHAR(512) NULL,
              created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
              updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
              KEY idx_retrieval_session (session_id),
              CONSTRAINT fk_retrieval_session FOREIGN KEY (session_id)
                REFERENCES recognition_sessions (id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

    # Category-match columns on retrieval_results (older deployments).
    for column, ddl in (
        ("selected_category_id", "ALTER TABLE retrieval_results ADD COLUMN selected_category_id VARCHAR(64) NULL"),
        ("selected_category_cn", "ALTER TABLE retrieval_results ADD COLUMN selected_category_cn VARCHAR(128) NULL"),
        ("category_confidence", "ALTER TABLE retrieval_results ADD COLUMN category_confidence DOUBLE NULL"),
        ("vision_assisted", "ALTER TABLE retrieval_results ADD COLUMN vision_assisted TINYINT(1) NOT NULL DEFAULT 0"),
    ):
        _, col_rows = await conn.execute_query(
            "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'retrieval_results' "
            f"AND COLUMN_NAME = '{column}'"
        )
        col_row = col_rows[0] if col_rows else {}
        col_count = (
            col_row.get("c", 0) if isinstance(col_row, dict) else (col_row[0] if col_row else 0)
        )
        if not col_count:
            await conn.execute_script(ddl)

    _, focus_rows = await conn.execute_query(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'uploaded_images' "
        "AND COLUMN_NAME = 'focus_point'"
    )
    focus_row = focus_rows[0] if focus_rows else {}
    focus_count = (
        focus_row.get("c", 0) if isinstance(focus_row, dict) else (focus_row[0] if focus_row else 0)
    )
    if not focus_count:
        await conn.execute_script("ALTER TABLE uploaded_images ADD COLUMN focus_point JSON NULL")

    for column, ddl in (
        (
            "foreground_object_key",
            "ALTER TABLE uploaded_images ADD COLUMN foreground_object_key VARCHAR(255) NULL",
        ),
        (
            "foreground_source",
            "ALTER TABLE uploaded_images ADD COLUMN foreground_source VARCHAR(32) NULL",
        ),
    ):
        _, fg_rows = await conn.execute_query(
            "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'uploaded_images' "
            f"AND COLUMN_NAME = '{column}'"
        )
        fg_row = fg_rows[0] if fg_rows else {}
        fg_count = fg_row.get("c", 0) if isinstance(fg_row, dict) else (fg_row[0] if fg_row else 0)
        if not fg_count:
            await conn.execute_script(ddl)

    # Undo a column added onto another service's admin_users before the tables were split.
    foreign_admin_cols = await _column_names(conn, "admin_users")
    if (
        foreign_admin_cols
        and await _id_data_type(conn, "admin_users") in {"varchar", "char"}
        and "display_name" in foreign_admin_cols
        and "role" not in foreign_admin_cols
    ):
        await conn.execute_script("ALTER TABLE admin_users DROP COLUMN display_name")

    await _copy_integer_pk_rows(
        conn,
        legacy="admin_users",
        current="vision_admin_users",
        columns=[
            "id",
            "username",
            "password_hash",
            "display_name",
            "role",
            "is_active",
            "last_login_at",
            "created_at",
            "updated_at",
        ],
    )
    _, app_user_tables = await conn.execute_query(
        "SELECT COUNT(*) AS c FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vision_app_users'"
    )
    app_user_table = app_user_tables[0] if app_user_tables else {}
    app_user_table_count = (
        app_user_table.get("c", 0)
        if isinstance(app_user_table, dict)
        else (app_user_table[0] if app_user_table else 0)
    )
    if not app_user_table_count:
        await conn.execute_script(
            """
            CREATE TABLE IF NOT EXISTS vision_app_users (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              username VARCHAR(64) NOT NULL,
              password_hash VARCHAR(255) NOT NULL,
              display_name VARCHAR(128) NOT NULL DEFAULT '',
              is_active TINYINT(1) NOT NULL DEFAULT 1,
              last_login_at DATETIME(6) NULL,
              created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
              updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
              UNIQUE KEY uid_vision_app_users_username (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

    _, app_user_cols = await conn.execute_query(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'recognition_sessions' "
        "AND COLUMN_NAME = 'app_user_id'"
    )
    app_user_col = app_user_cols[0] if app_user_cols else {}
    app_user_col_count = (
        app_user_col.get("c", 0) if isinstance(app_user_col, dict) else (app_user_col[0] if app_user_col else 0)
    )
    if not app_user_col_count:
        await conn.execute_script(
            "ALTER TABLE recognition_sessions ADD COLUMN app_user_id INT NULL, "
            "ADD KEY idx_recognition_sessions_app_user_id (app_user_id), "
            "ADD CONSTRAINT fk_recognition_sessions_app_user "
            "FOREIGN KEY (app_user_id) REFERENCES vision_app_users (id)"
        )

    await _copy_integer_pk_rows(
        conn,
        legacy="audit_logs",
        current="vision_audit_logs",
        columns=[
            "id",
            "actor_type",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "detail",
            "ip_address",
            "created_at",
            "updated_at",
        ],
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
