"""Catalog tools exposed to DeepSeek function calling for WhatsApp chat.

All tool names, descriptions, and returned field names are English.
SKU == material_code; never expose price / stock / availability.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.catalog import (
    CatalogProduct,
    VehicleSelection,
    _clean,
    catalog_service,
)

logger = logging.getLogger(__name__)

RESULT_CAP = 8
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_products_by_oe",
            "description": (
                "Search Reach catalog products by OE / OEM / part / reference number. "
                "Use when the customer provides a part number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "oe_number": {
                        "type": "string",
                        "description": "OE, OEM, or reference part number",
                    }
                },
                "required": ["oe_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products_by_keyword",
            "description": (
                "Search products by part category keyword only. "
                "Supported: compressor, condenser, radiator."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "compressor | condenser | radiator",
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products_by_vehicle",
            "description": (
                "Search products that fit a vehicle. Provide brand (make) and optionally "
                "model and year. Vehicle alone is enough to return fitting SKUs. "
                "Optionally filter by category keyword (compressor / condenser / radiator). "
                "Brand/model matching tolerates case, spaces, and punctuation "
                "(e.g. 370z ≈ 370Z); true synonyms still need the catalog spelling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string", "description": "Vehicle make / brand, e.g. Toyota"},
                    "model": {"type": "string", "description": "Vehicle model name"},
                    "year": {"type": "string", "description": "Model year, e.g. 2018"},
                    "category_keyword": {
                        "type": "string",
                        "description": "Optional part category: compressor, condenser, or radiator",
                    },
                },
                "required": ["brand"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products_by_specs",
            "description": (
                "Narrow SKUs by technical specifications after confirming the category. "
                "Currently only radiator has a full schema. "
                "specs keys include core_material, inlet_location, outlet_location, "
                "core_height_mm, refrigerant_type, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "compressor | condenser | radiator",
                    },
                    "specs": {
                        "type": "object",
                        "description": "Technical parameter key/value pairs",
                        "additionalProperties": {"type": "string"},
                    },
                    "brand": {"type": "string", "description": "Optional vehicle brand filter"},
                    "oe": {"type": "string", "description": "Optional OE / part number filter"},
                },
                "required": ["category", "specs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_vehicle_options",
            "description": (
                "List cascading vehicle options. "
                "No args: brands. With brand: models. With brand+model: years."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "model": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_detail",
            "description": (
                "Get detail for one product by material_code (SKU). "
                "Includes fitment samples, OE numbers, and technical specs when present. "
                "Does not include price, stock, or availability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "material_code / SKU",
                    }
                },
                "required": ["code"],
            },
        },
    },
]


def _unsupported_category_payload(raw: str | None = None) -> dict[str, Any]:
    from app.core.constants import SUPPORTED_CATEGORY_CODES
    from app.services.category_guard import supported_category_list_en

    return {
        "unsupported_category": True,
        "requested": raw,
        "supported": supported_category_list_en(),
        "supported_codes": list(SUPPORTED_CATEGORY_CODES),
        "count": 0,
        "products": [],
    }


def _product_card(product: CatalogProduct, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    card = {
        "material_code": product.material_code,
        "sku": product.material_code,
        "name": product.material_code,
        "category": product.category_code,
    }
    if extra:
        card.update(extra)
    for key in ("price", "stock", "stock_status", "availability", "available"):
        card.pop(key, None)
    return card


def serialize_product_out(
    item: Any,
    *,
    catalog: dict[str, CatalogProduct] | None = None,
) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        data = item.model_dump()
    else:
        data = dict(item)
    attributes = data.get("attributes") or {}
    material_code = _clean(attributes.get("material_code") or data.get("sku") or "")
    product = (catalog or {}).get(material_code) if material_code else None
    name = material_code or _clean(data.get("name")) or "-"
    category = data.get("category_name") or (product.category_code if product else None)
    if category and CJK_RE.search(str(category)):
        from app.services.category_guard import category_en, normalize_category_id

        cid = normalize_category_id(category)
        category = category_en(cid) if cid else None
    attrs = dict(attributes) if isinstance(attributes, dict) else {}
    for key in ("price", "stock", "stock_status", "availability", "available"):
        attrs.pop(key, None)
    return {
        "sku": data.get("sku") or material_code,
        "name": name,
        "category": category,
        "oe_number": data.get("oe_number"),
        "ref_nums": data.get("ref_nums") or [],
        "brand": data.get("brand"),
        "fitment": data.get("fitment"),
        "material_code": material_code or None,
        "attributes": attrs,
    }


async def _catalog_for_products(products: list[Any]) -> dict[str, CatalogProduct]:
    codes: list[str] = []
    for item in products:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        code = _clean((data.get("attributes") or {}).get("material_code") or data.get("sku") or "")
        if code:
            codes.append(code)
    return await catalog_service._products(codes)


async def search_products_by_oe(oe_number: str) -> dict[str, Any]:
    oe = _clean(oe_number)
    if not oe:
        return {"count": 0, "products": [], "error": "oe_number is required"}
    products = await catalog_service.match_products(
        image_candidates=[],
        reliable_skus=False,
        category_name=None,
        oe_number=oe,
        vehicle=VehicleSelection(),
    )
    capped = products[:RESULT_CAP]
    catalog = await _catalog_for_products(capped)
    cards = [serialize_product_out(p, catalog=catalog) for p in capped]
    return {"count": len(cards), "products": cards, "oe_number": oe}


async def search_products_by_keyword(keyword: str) -> dict[str, Any]:
    from app.services.category_guard import is_supported_category, normalize_category_id

    key = _clean(keyword)
    if not key:
        return {"count": 0, "products": [], "error": "keyword is required"}
    if not is_supported_category(key):
        lowered = key.casefold()
        blocked = ("fan", "风扇", "intercooler", "中冷", "evaporator", "蒸发", "oil cooler", "机油冷却")
        if any(b in lowered for b in blocked) or normalize_category_id(key) is None:
            return _unsupported_category_payload(key)
    products = await catalog_service._products_by_label(key)
    cards = [_product_card(p) for p in products[:RESULT_CAP]]
    return {"count": len(cards), "products": cards, "keyword": key}


async def search_products_by_vehicle(
    brand: str,
    model: str | None = None,
    year: str | None = None,
    category_keyword: str | None = None,
    series: str | None = None,  # ignored legacy arg
) -> dict[str, Any]:
    from app.services.category_guard import is_supported_category, normalize_category_id

    _ = series
    vehicle = VehicleSelection(
        brand=_clean(brand) or None,
        model=_clean(model) or None,
        year=_clean(year) or None,
    )
    if not vehicle.filled():
        return {"count": 0, "products": [], "error": "brand is required"}

    category = _clean(category_keyword)
    if category and not is_supported_category(category):
        return _unsupported_category_payload(category)

    products = await catalog_service.match_products(
        image_candidates=[],
        reliable_skus=False,
        category_name=category or None,
        oe_number=None,
        vehicle=vehicle,
    )
    cards = [serialize_product_out(p) for p in products[:RESULT_CAP]]
    return {
        "count": len(cards),
        "products": cards,
        "vehicle": vehicle.filled(),
        "category_keyword": category or None,
    }


async def search_products_by_specs(
    category: str,
    specs: dict[str, Any] | None = None,
    brand: str | None = None,
    oe: str | None = None,
) -> dict[str, Any]:
    from app.services.category_guard import is_supported_category, normalize_category_code
    from app.services.catalog_admin import search_by_specs

    if not is_supported_category(category):
        return _unsupported_category_payload(category)
    code = normalize_category_code(category) or ""
    if code != "RADIATOR":
        return {
            "count": 0,
            "products": [],
            "category": code,
            "spec_schema_pending": True,
            "message": "Technical-spec schema pending for this category",
        }
    cards = await search_by_specs(
        code,
        specs or {},
        brand=_clean(brand) or None,
        oe=_clean(oe) or None,
        limit=RESULT_CAP,
    )
    return {
        "count": len(cards),
        "products": cards,
        "category": code,
        "specs": specs or {},
    }


async def list_vehicle_options(
    brand: str | None = None,
    model: str | None = None,
    series: str | None = None,  # ignored
) -> dict[str, Any]:
    _ = series
    brand_v = _clean(brand)
    model_v = _clean(model)
    if not brand_v:
        options = await catalog_service.list_brands()
        return {"level": "brand", "options": [o.value for o in options[:100]]}
    if not model_v:
        options = await catalog_service.list_models(brand_v)
        return {"level": "model", "brand": brand_v, "options": [o.value for o in options[:100]]}
    options = await catalog_service.list_years(brand_v, model_v)
    return {
        "level": "year",
        "brand": brand_v,
        "model": model_v,
        "options": [o.value for o in options[:100]],
    }


async def get_product_detail(code: str) -> dict[str, Any]:
    raw = _clean(code)
    if not raw:
        return {"found": False, "error": "code is required"}

    products = await catalog_service._products([raw])
    product = products.get(raw)
    if product is None:
        return {"found": False, "code": raw}

    samples, vehicles = await catalog_service._fitment_samples([product.material_code], None)
    refs = await catalog_service._ref_nums([product.material_code])
    specs = await catalog_service.product_specs(product.material_code)
    from app.services.catalog import fitment_text

    fitment = fitment_text(samples.get(product.material_code, []), vehicles)
    return {
        "found": True,
        "product": _product_card(
            product,
            extra={
                "fitment": fitment,
                "ref_nums": refs.get(product.material_code, [])[:5],
                "attributes": specs,
            },
        ),
    }


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> Any:
    args = arguments or {}
    if name == "search_products_by_oe":
        return await search_products_by_oe(str(args.get("oe_number") or ""))
    if name == "search_products_by_keyword":
        return await search_products_by_keyword(str(args.get("keyword") or ""))
    if name == "search_products_by_vehicle":
        return await search_products_by_vehicle(
            brand=str(args.get("brand") or ""),
            model=str(args.get("model") or "") or None,
            year=str(args.get("year") or "") or None,
            category_keyword=str(args.get("category_keyword") or "") or None,
            series=str(args.get("series") or "") or None,
        )
    if name == "search_products_by_specs":
        specs = args.get("specs") or {}
        if not isinstance(specs, dict):
            specs = {}
        return await search_products_by_specs(
            category=str(args.get("category") or ""),
            specs=specs,
            brand=str(args.get("brand") or "") or None,
            oe=str(args.get("oe") or "") or None,
        )
    if name == "list_vehicle_options":
        return await list_vehicle_options(
            brand=str(args.get("brand") or "") or None,
            model=str(args.get("model") or "") or None,
            series=str(args.get("series") or "") or None,
        )
    if name == "get_product_detail":
        return await get_product_detail(str(args.get("code") or ""))
    return {"error": f"unknown_tool:{name}"}
