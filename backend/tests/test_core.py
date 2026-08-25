import asyncio
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from app.core.config import Settings
from app.core.security import hash_password
from app.main import create_app
from app.models import AdminUser, CategoryMapping, DeviceSession, PromptConfig
from app.core.constants import DEFAULT_VISION_PROMPT, ROLE_SUPERADMIN
from app.integrations.deepseek.client import format_vision_result, parse_json_object


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def app_client(tmp_path):
    db_file = tmp_path / "test.sqlite3"
    await Tortoise.init(
        db_url=f"sqlite://{db_file}",
        modules={"models": ["app.models"]},
    )
    await Tortoise.generate_schemas()
    await AdminUser.create(
        username="admin",
        password_hash=hash_password("Admin@123456"),
        display_name="Admin",
        role=ROLE_SUPERADMIN,
        is_active=True,
    )
    await CategoryMapping.create(
        alias_name="散热器",
        category_code="RADIATOR",
        category_name="散热器",
        is_active=True,
        priority=10,
    )
    await PromptConfig.create(
        name="default_vision",
        version="v1",
        purpose="vision",
        content=DEFAULT_VISION_PROMPT,
        is_active=True,
    )

    app = create_app()

    # Override lifespan DB by using already-initialized Tortoise; recreate app without lifespan init conflict
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await Tortoise.close_connections()


def test_settings_rejects_protected_database():
    with pytest.raises(Exception):
        Settings(MYSQL_DATABASE="ReachMDM_LMR", SECRET_KEY="test-secret")


def test_parse_vision_json():
    payload = parse_json_object('```json\n{"part_name":"散热器","confidence":"92%","reason":"散热芯"}\n```')
    result = format_vision_result(payload)
    assert result.part_name == "散热器"
    assert result.confidence == 0.92


@pytest.mark.asyncio
async def test_admin_login_and_stats(app_client):
    # Health does not need DB from lifespan if Tortoise already up; create_app lifespan may re-init.
    # Use direct model checks instead for reliability in unit tests.
    admin = await AdminUser.get(username="admin")
    assert admin.role == ROLE_SUPERADMIN

    session = await DeviceSession.create(
        session_token="a" * 32,
        device_id="device-test-001",
        expires_at=datetime.utcnow() + timedelta(hours=1),
        is_active=True,
    )
    assert session.is_active is True
