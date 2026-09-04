from __future__ import annotations

import io
import json

import httpx
import pytest
from PIL import Image

from app.core.exceptions import AppError
from app.integrations.deepseek.client import format_vision_result, parse_json_object
from app.integrations.mdm.client import MdmAdapter, MdmRequestError
from app.schemas import ProductOut
from app.services.eval_metrics import score_session
from app.utils.images import compress_to_jpeg_bytes, compute_phash, validate_image_meta


def _make_png_bytes(color=(20, 120, 200)) -> bytes:
    image = Image.new("RGB", (320, 240), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_validate_image_rejects_bad_extension():
    with pytest.raises(AppError):
        validate_image_meta("a.gif", "image/gif", 100, 10 * 1024 * 1024)


def test_compress_and_phash():
    raw = _make_png_bytes()
    jpeg, w, h = compress_to_jpeg_bytes(raw, max_side=128)
    assert jpeg[:2] == b"\xff\xd8"
    assert w <= 128 and h <= 128
    assert len(compute_phash(jpeg)) == 40


def test_vision_candidates_enrichment_shape():
    payload = parse_json_object(
        '{"part_name":"冷凝器","confidence":0.77,"reason":"扁管","candidates":[{"name":"冷凝器","confidence":0.77},{"name":"散热器","confidence":0.4}]}'
    )
    result = format_vision_result(payload)
    assert result.part_name == "冷凝器"
    assert len(result.candidates) == 2


@pytest.mark.asyncio
async def test_mdm_mock_search():
    adapter = MdmAdapter()
    adapter.use_mock = True
    products = await adapter.search_products(category_name="散热器", brand="BMW", oe_number="17117533485")
    assert products
    assert products[0].sku
    assert "OE" in (products[0].match_reason or "") or "品类" in (products[0].match_reason or "")


@pytest.mark.asyncio
async def test_mdm_vehicle_options_sorted_by_pinyin():
    adapter = MdmAdapter()
    adapter.use_mock = True
    brands = await adapter.list_brands()
    labels = [b.label for b in brands]
    # 奥迪(aodi) < 宝马(baoma) < 奔驰(benchi) < 丰田(fengtian)
    assert labels == ["奥迪", "宝马", "奔驰", "丰田"]


@pytest.mark.asyncio
async def test_mdm_vehicle_options_indexed():
    adapter = MdmAdapter()
    adapter.use_mock = True
    indexed = adapter.index_options(await adapter.list_brands())
    assert "A" in indexed["letters"]
    assert "B" in indexed["letters"]
    assert "F" in indexed["letters"]
    a_group = next(g for g in indexed["groups"] if g["letter"] == "A")
    assert a_group["items"][0]["label"] == "奥迪"
    assert all("letter" in item for item in indexed["items"])


@pytest.mark.asyncio
async def test_mdm_query_token_cache_paths_and_field_mapping():
    calls = {"token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/oauth/token":
            calls["token"] += 1
            assert b"grant_type=client_credentials" in request.content
            assert b"client_id=vision-client" in request.content
            assert b"client_secret=vision-secret" in request.content
            return httpx.Response(
                200,
                json={
                    "access_token": "cached-token",
                    "token_type": "Bearer",
                    "expires_in": 900,
                    "scope": "vehicle:read product:read cn_vehicle:read",
                },
            )

        assert request.headers["authorization"] == "Bearer cached-token"
        if path == "/api/public/v1/vehicles/options":
            params = request.url.params
            if not params.get("brand"):
                assert dict(params) == {}
                return httpx.Response(
                    200,
                    json={
                        "code": "ok",
                        "message": "success",
                        "data": {
                            "brand": [
                                {"label": "奥迪", "value": "AUDI"},
                                {"label": "宝马", "value": "BMW"},
                            ],
                            "series": [],
                            "model": [],
                            "model_year": [],
                        },
                        "meta": {"request_id": "req-brand", "datasets": {}},
                    },
                )
            if params.get("brand") == "BMW" and not params.get("series"):
                return httpx.Response(
                    200,
                    json={
                        "code": "ok",
                        "message": "success",
                        "data": {
                            "series": [{"label": "3系", "value": "3Series"}],
                            "model": [],
                            "model_year": [],
                        },
                        "meta": {"request_id": "req-series", "datasets": {}},
                    },
                )
            if params.get("series") == "3Series" and not params.get("model"):
                return httpx.Response(
                    200,
                    json={
                        "code": "ok",
                        "message": "success",
                        "data": {
                            "model": [{"label": "320", "value": "320"}],
                            "model_year": [],
                        },
                        "meta": {"request_id": "req-model", "datasets": {}},
                    },
                )
            assert dict(params) == {"brand": "BMW", "series": "3Series", "model": "320"}
            return httpx.Response(
                200,
                json={
                    "code": "ok",
                    "message": "success",
                    "data": {
                        "model_year": [{"label": "2020款", "value": "2020"}],
                    },
                    "meta": {"request_id": "req-year", "datasets": {}},
                },
            )
        if path == "/api/public/v1/products/resolve-by-oe":
            body = json.loads(request.content)
            if body == {"oe_numbers": ["1301100XKZ16A"]}:
                return httpx.Response(
                    200,
                    json={
                        "code": "ok",
                        "message": "success",
                        "data": {"items": [], "unmatched_oe_numbers": ["1301100XKZ16A"]},
                        "meta": {"request_id": "req-oe-miss", "datasets": {}},
                    },
                )
            assert body == {"oe_numbers": ["8K0 121 251"]}
            return httpx.Response(
                200,
                json={
                    "code": "ok",
                    "message": "success",
                    "data": {
                        "items": [
                            {
                                "material_code": "1.40.12345",
                                "part_name": "散热器",
                                "category_name": "散热器",
                                "oe_number": "8K0 121 251",
                                "brand": "Reach",
                                "image_url": None,
                                "stock_status": "正常供货",
                                "price": None,
                                "currency": None,
                                "match_type": "direct",
                            }
                        ],
                        "unmatched_oe_numbers": ["17117547059"],
                    },
                    "meta": {"request_id": "req-oe", "datasets": {}},
                },
            )
        if path == "/api/public/v1/cn-vehicle/products/search":
            assert json.loads(request.content) == {
                "vehicle_type": "passenger",
                "category_name": "散热器",
                "oe_numbers": ["1301100XKZ16A"],
                "page": 1,
                "page_size": 20,
            }
            return httpx.Response(
                200,
                json={
                    "code": "ok",
                    "message": "success",
                    "data": {
                        "items": [
                            {
                                "material_code": "1.40.67890",
                                "part_name": "散热器",
                                "category_name": "散热器",
                                "oe_number": "1301100XKZ16A",
                                "brand": "Reach",
                                "fitment": None,
                                "image_url": None,
                                "stock_status": "正常供货",
                                "price": 299.0,
                                "currency": "CNY",
                                "supplier_count": 2,
                            }
                        ],
                        "aggregations": {
                            "category_counts": [{"value": "散热器", "count": 12}],
                            "supplier_counts": [],
                        },
                    },
                    "meta": {
                        "request_id": "req-cn",
                        "page": 1,
                        "page_size": 20,
                        "total": 12,
                        "datasets": {},
                    },
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    adapter = MdmAdapter(transport=httpx.MockTransport(handler))
    adapter.use_mock = False
    adapter.base_url = "http://mdm.test"
    adapter.client_id = "vision-client"
    adapter.client_secret = "vision-secret"
    adapter.country = ""
    adapter.vehicle_type = "passenger"
    try:
        brands = await adapter.list_brands()
        assert [item.model_dump() for item in brands] == [
            {"value": "AUDI", "label": "奥迪"},
            {"value": "BMW", "label": "宝马"},
        ]
        series = await adapter.list_series("BMW")
        assert series[0].value == "3Series"
        models = await adapter.list_models("BMW", "3Series")
        assert models[0].value == "320"
        years = await adapter.list_years("BMW", "3Series", "320")
        assert years[0].model_dump() == {"value": "2020", "label": "2020款"}

        by_oe = await adapter.search_products(oe_number="8K0 121 251", category_name="散热器")
        assert by_oe[0].sku == "1.40.12345"
        assert by_oe[0].name == "散热器"
        assert by_oe[0].stock_status == "正常供货"
        assert by_oe[0].match_reason == "OE精确匹配"
        assert ProductOut(**by_oe[0].model_dump()).sku == "1.40.12345"

        by_cat = await adapter.search_products(
            category_name="散热器",
            oe_number="1301100XKZ16A",
        )
        assert by_cat[0].sku == "1.40.67890"
        assert by_cat[0].name == "散热器"
        assert by_cat[0].price == 299.0
        assert by_cat[0].stock_status == "正常供货"
        assert by_cat[0].match_reason == "品类匹配"
        assert calls["token"] == 1
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_mdm_query_refreshes_token_once_after_401():
    calls = {"token": 0, "options": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            calls["token"] += 1
            return httpx.Response(
                200,
                json={"access_token": f"token-{calls['token']}", "expires_in": 3600},
            )
        calls["options"] += 1
        if request.headers["authorization"] == "Bearer token-1":
            return httpx.Response(401, json={"detail": "expired"})
        assert request.headers["authorization"] == "Bearer token-2"
        return httpx.Response(
            200,
            json={
                "code": "ok",
                "message": "success",
                "data": {"brand": [{"label": "奥迪", "value": "AUDI"}]},
                "meta": {"request_id": "req-refresh", "datasets": {}},
            },
        )

    adapter = MdmAdapter(transport=httpx.MockTransport(handler))
    adapter.use_mock = False
    adapter.base_url = "http://mdm.test"
    adapter.client_id = "vision-client"
    adapter.client_secret = "vision-secret"
    try:
        brands = await adapter.list_brands()
        assert brands[0].value == "AUDI"
        assert calls == {"token": 2, "options": 2}
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_mdm_query_refreshes_token_near_expiry():
    now = [0.0]
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/oauth/token":
            token_calls += 1
            return httpx.Response(
                200,
                json={"access_token": f"token-{token_calls}", "expires_in": 60},
            )
        return httpx.Response(
            200,
            json={
                "code": "ok",
                "message": "success",
                "data": {"brand": [{"label": "宝马", "value": "BMW"}]},
                "meta": {"request_id": "req-expiry", "datasets": {}},
            },
        )

    adapter = MdmAdapter(transport=httpx.MockTransport(handler), clock=lambda: now[0])
    adapter.use_mock = False
    adapter.base_url = "http://mdm.test"
    adapter.client_id = "vision-client"
    adapter.client_secret = "vision-secret"
    adapter.token_refresh_skew = 30
    try:
        await adapter.list_brands()
        now[0] = 29
        await adapter.list_brands()
        assert token_calls == 1
        now[0] = 31
        await adapter.list_brands()
        assert token_calls == 2
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_mdm_query_retries_only_5xx_with_finite_limit():
    calls = {"token": 0, "options": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        calls["options"] += 1
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    adapter = MdmAdapter(transport=httpx.MockTransport(handler))
    adapter.use_mock = False
    adapter.base_url = "http://mdm.test"
    adapter.client_id = "vision-client"
    adapter.client_secret = "vision-secret"
    adapter.max_retries = 2
    try:
        with pytest.raises(MdmRequestError, match="status 503"):
            await adapter.list_brands()
        assert calls == {"token": 1, "options": 3}
    finally:
        await adapter.aclose()


def test_eval_score_top1_top3_reject():
    scored = score_session(
        confirmed_code="RAD",
        confirmed_name="散热器",
        mapped_code="RAD",
        mapped_name="散热器",
        candidates=[
            {"name": "散热器", "category_code": "RAD", "confidence": 0.9},
            {"name": "冷凝器", "category_code": "COND", "confidence": 0.2},
        ],
        confidence=0.9,
        reject_confidence=0.45,
    )
    assert scored["top1_hit"] is True
    assert scored["top3_hit"] is True
    assert scored["is_reject"] is False

    scored2 = score_session(
        confirmed_code="RAD",
        confirmed_name="散热器",
        mapped_code="COND",
        mapped_name="冷凝器",
        candidates=[
            {"name": "冷凝器", "category_code": "COND", "confidence": 0.5},
            {"name": "水泵", "category_code": "WP", "confidence": 0.3},
            {"name": "散热器", "category_code": "RAD", "confidence": 0.2},
        ],
        confidence=0.3,
        reject_confidence=0.45,
    )
    assert scored2["top1_hit"] is False
    assert scored2["top3_hit"] is True
    assert scored2["is_reject"] is True
