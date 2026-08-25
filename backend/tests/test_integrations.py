from __future__ import annotations

import io

import httpx
import pytest
from PIL import Image

from app.core.exceptions import AppError
from app.integrations.deepseek.client import format_vision_result, parse_json_object
from app.integrations.mdm.client import MdmAdapter
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
async def test_mdm_real_option_list_and_search(monkeypatch):
    adapter = MdmAdapter()
    adapter.use_mock = False
    adapter.token = "dev-token"
    adapter.base_url = "http://mdm.test"
    adapter.country = ""
    adapter.vehicle_type = "passenger"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/manage/cars/option_list"):
            brand = request.url.params.get("brand")
            series = request.url.params.get("series")
            model = request.url.params.get("model")
            data = {}
            if not brand:
                data = {"brand": [{"label": "宝马", "value": "BMW"}]}
            elif brand and not series:
                data = {"series": [{"label": "3系", "value": "3Series"}]}
            elif series and not model:
                data = {"model": [{"label": "320", "value": "320"}]}
            else:
                data = {"model_year": [{"label": "2020款", "value": "2020"}]}
            assert request.headers.get("token") == "dev-token"
            return httpx.Response(200, json={"code": 200, "data": data})
        if path.endswith("/api/manage/products/check_product_exist"):
            body = request.read()
            assert b"17117533485" in body
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": [{"Materiel_Number": "RP-001", "part_name": "散热器"}],
                },
            )
        if path.endswith("/api/manage/cn_vehicle/search"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": [{"reach_number": "RP-CN-1", "category_name": "冷凝器"}],
                },
            )
        return httpx.Response(404, json={"msg": "not found"})

    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    brands = await adapter.list_brands()
    assert brands[0].value == "BMW"
    series = await adapter.list_series("BMW")
    assert series[0].value == "3Series"
    models = await adapter.list_models("BMW", "3Series")
    assert models[0].value == "320"
    years = await adapter.list_years("BMW", "3Series", "320")
    assert years[0].value == "2020"

    by_oe = await adapter.search_products(oe_number="17117533485", category_name="散热器")
    assert by_oe[0].sku == "RP-001"
    assert by_oe[0].match_reason == "OE精确匹配"

    by_cat = await adapter.search_products(category_name="冷凝器")
    assert by_cat[0].sku == "RP-CN-1"
    assert by_cat[0].match_reason == "品类匹配"


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
