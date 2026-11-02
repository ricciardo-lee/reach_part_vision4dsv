"""Excel import/export for app-owned OE / vehicle / radiator-spec tables."""

from __future__ import annotations

import io
import logging
from typing import Any

from openpyxl import Workbook, load_workbook

from app.core.catalog_fields import (
    OE_HEADERS,
    RADIATOR_SPEC_FIELDS,
    RADIATOR_SPEC_HEADERS,
    VEHICLE_HEADERS,
)
from app.core.constants import SUPPORTED_CATEGORY_IDS
from app.core.exceptions import AppError
from app.models import CatalogImportLog, VisionPartOe, VisionPartVehicle, VisionRadiatorSpec
from app.services.catalog import normalize_oe
from app.services.category_guard import normalize_category_code

logger = logging.getLogger(__name__)

SPEC_KINDS = set(SUPPORTED_CATEGORY_IDS)

HEADER_ALIASES = {
    "物料编码": "material_code",
    "料号": "material_code",
    "sku": "material_code",
    "品类": "category",
    "品类编码": "category",
    "category_code": "category",
    "oe": "oe",
    "oe号": "oe",
    "零件号": "oe",
    "oe_number": "oe",
    "make": "make_name",
    "make_name": "make_name",
    "品牌": "make_name",
    "model": "model_name",
    "model_name": "model_name",
    "车型": "model_name",
    "year": "year",
    "年款": "year",
    "model_year": "year",
}


def _norm_header(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in HEADER_ALIASES:
        return HEADER_ALIASES[text]
    key = text.casefold()
    if key in HEADER_ALIASES:
        return HEADER_ALIASES[key]
    if key == "oe":
        return "oe"
    return key.replace(" ", "_")


def _cell_str(value: object) -> str:
    """Normalize Excel cell values; keep long part numbers as text-like strings."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        # Excel often stores long OE/SKU as float; only ~15 digits are precise.
        # Prefer fixed form for safe integers; keep scientific form for huge
        # magnitudes so we do not expand imprecise floats into 200+ digit strings.
        if value.is_integer() and abs(value) < 1e15:
            return format(value, ".0f")
        return format(value, ".15g").strip()
    return str(value).strip()


def export_template(kind: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    if kind == "oe":
        ws.title = "oe"
        ws.append(list(OE_HEADERS))
        ws.append(["RADIATOR", "EXAMPLE-001", "17117533485"])
    elif kind == "vehicles":
        ws.title = "vehicles"
        ws.append(list(VEHICLE_HEADERS))
        ws.append(["EXAMPLE-001", "Toyota", "Camry", "2018"])
    elif kind in ("spec_radiator", "radiator"):
        ws.title = "spec_radiator"
        ws.append(list(RADIATOR_SPEC_HEADERS))
        sample = ["EXAMPLE-001"] + [""] * len(RADIATOR_SPEC_FIELDS)
        sample[1] = "Aluminum"  # core_material
        ws.append(sample)
    elif kind in ("spec_compressor", "compressor", "spec_condenser", "condenser"):
        cat = kind.replace("spec_", "")
        ws.title = f"spec_{cat}"
        ws.append(["material_code"])
        ws.append(["EXAMPLE-001"])
    else:
        raise AppError("Unknown template kind", code="bad_kind", status_code=400)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_excel(file_bytes: bytes, kind: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    try:
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"Invalid Excel: {exc}", code="bad_excel", status_code=400) from exc
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], [{"row": 1, "error": "empty_sheet"}]
    headers = [_norm_header(h) for h in header_row]

    if kind == "oe":
        required = {"category", "material_code", "oe"}
    elif kind == "vehicles":
        required = {"material_code", "make_name"}
    elif kind in ("spec_radiator", "radiator"):
        required = {"material_code"}
    else:
        required = {"material_code"}

    missing = required - set(headers)
    if missing:
        return [], [{"row": 1, "error": f"missing_headers:{','.join(sorted(missing))}"}]

    known_spec = set(RADIATOR_SPEC_FIELDS) | {"material_code"}
    rows: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows_iter, start=2):
        if raw is None or all(v is None or str(v).strip() == "" for v in raw):
            continue
        item = {headers[i]: _cell_str(raw[i]) if i < len(raw) else "" for i in range(len(headers))}
        if kind == "oe":
            code = normalize_category_code(item.get("category"))
            if not code:
                errors.append({"row": idx, "error": "unsupported_category", "value": item.get("category")})
                continue
            item["category"] = code
            if not item.get("material_code") or not item.get("oe"):
                errors.append({"row": idx, "error": "oe_fields_required"})
                continue
            # Excel numeric cells lose precision past ~15 digits; ask for text-formatted OE.
            if len(item["oe"]) > 64 and item["oe"].isdigit():
                errors.append(
                    {
                        "row": idx,
                        "error": "oe_excel_numeric_suspected",
                        "hint": "Format the OE column as Text in Excel before export",
                        "value": item["oe"][:80],
                    }
                )
                continue
            if len(item["oe"]) > 512:
                errors.append({"row": idx, "error": "oe_too_long", "length": len(item["oe"])})
                continue
            item["oe_normalized"] = normalize_oe(item["oe"])
            if len(item["oe_normalized"]) > 512:
                errors.append({"row": idx, "error": "oe_normalized_too_long"})
                continue
        elif kind == "vehicles":
            if not item.get("material_code") or not item.get("make_name"):
                errors.append({"row": idx, "error": "vehicle_fields_required"})
                continue
        elif kind in ("spec_radiator", "radiator"):
            if not item.get("material_code"):
                errors.append({"row": idx, "error": "material_code_required"})
                continue
            unknown = [k for k in item if k and k not in known_spec]
            if unknown:
                errors.append({"row": idx, "error": "unknown_columns", "columns": unknown})
                for k in unknown:
                    item.pop(k, None)
        rows.append(item)
    return rows, errors


async def upsert_oe(rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        existing = await VisionPartOe.get_or_none(
            material_code=row["material_code"],
            oe=row["oe"],
        )
        payload = {
            "category": row["category"],
            "oe_normalized": row.get("oe_normalized") or normalize_oe(row["oe"]),
            "is_active": True,
        }
        if existing:
            await existing.update_from_dict(payload).save()
        else:
            await VisionPartOe.create(
                material_code=row["material_code"],
                oe=row["oe"],
                **payload,
            )
        count += 1
    return count


async def upsert_vehicles(rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        material_code = row["material_code"]
        make_name = row["make_name"]
        model_name = row.get("model_name") or None
        year = row.get("year") or None
        existing = await VisionPartVehicle.get_or_none(
            material_code=material_code,
            make_name=make_name,
            model_name=model_name,
            year=year,
        )
        if existing:
            if not existing.is_active:
                existing.is_active = True
                await existing.save()
        else:
            await VisionPartVehicle.create(
                material_code=material_code,
                make_name=make_name,
                model_name=model_name,
                year=year,
                is_active=True,
            )
        count += 1
    return count


async def upsert_radiator_specs(rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        code = row["material_code"]
        payload = {name: (row.get(name) or None) for name in RADIATOR_SPEC_FIELDS}
        payload["is_active"] = True
        existing = await VisionRadiatorSpec.get_or_none(material_code=code)
        if existing:
            await existing.update_from_dict(payload).save()
        else:
            await VisionRadiatorSpec.create(material_code=code, **payload)
        count += 1
    return count


async def import_excel(
    *,
    kind: str,
    file_bytes: bytes,
    filename: str,
    operator: str,
) -> CatalogImportLog:
    if kind in ("spec_compressor", "compressor", "spec_condenser", "condenser"):
        await CatalogImportLog.create(
            kind=kind if kind.startswith("spec_") else f"spec_{kind}",
            filename=filename,
            total_rows=0,
            success_count=0,
            failure_count=1,
            errors=[{"error": "spec_schema_pending"}],
            operator=operator,
        )
        raise AppError(
            "Technical-spec schema is pending; import is not available yet",
            code="spec_schema_pending",
            status_code=501,
        )

    parse_kind = kind
    if kind == "radiator":
        parse_kind = "spec_radiator"
    rows, parse_errors = parse_excel(file_bytes, parse_kind)
    success = 0
    if kind == "oe":
        success = await upsert_oe(rows)
    elif kind == "vehicles":
        success = await upsert_vehicles(rows)
    elif kind in ("spec_radiator", "radiator"):
        success = await upsert_radiator_specs(rows)
    else:
        raise AppError("Unknown import kind", code="bad_kind", status_code=400)

    return await CatalogImportLog.create(
        kind=parse_kind if kind in ("spec_radiator", "radiator") else kind,
        filename=filename,
        total_rows=len(rows) + len(parse_errors),
        success_count=success,
        failure_count=len(parse_errors),
        errors=parse_errors or None,
        operator=operator,
    )


async def export_data(kind: str, *, keyword: str | None = None, limit: int = 5000) -> bytes:
    wb = Workbook()
    ws = wb.active
    keyword = (keyword or "").strip()
    if kind == "oe":
        ws.title = "oe"
        ws.append(list(OE_HEADERS))
        qs = VisionPartOe.filter(is_active=True)
        if keyword:
            qs = qs.filter(oe__icontains=keyword)
        items = await qs.order_by("material_code").limit(limit)
        for item in items:
            ws.append([item.category, item.material_code, item.oe])
    elif kind == "vehicles":
        ws.title = "vehicles"
        ws.append(list(VEHICLE_HEADERS))
        qs = VisionPartVehicle.filter(is_active=True)
        if keyword:
            qs = qs.filter(make_name__icontains=keyword)
        items = await qs.order_by("material_code").limit(limit)
        for item in items:
            ws.append([item.material_code, item.make_name, item.model_name or "", item.year or ""])
    elif kind in ("spec_radiator", "radiator"):
        ws.title = "spec_radiator"
        ws.append(list(RADIATOR_SPEC_HEADERS))
        qs = VisionRadiatorSpec.filter(is_active=True)
        if keyword:
            qs = qs.filter(material_code__icontains=keyword)
        items = await qs.order_by("material_code").limit(limit)
        for item in items:
            ws.append(
                [item.material_code]
                + [getattr(item, name) or "" for name in RADIATOR_SPEC_FIELDS]
            )
    else:
        raise AppError("Unknown export kind", code="bad_kind", status_code=400)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def search_by_specs(
    category: str,
    specs: dict[str, Any],
    *,
    brand: str | None = None,
    oe: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Filter radiator specs; return product cards as dicts."""
    code = normalize_category_code(category)
    if code != "RADIATOR":
        return []
    qs = VisionRadiatorSpec.filter(is_active=True)
    for key, value in (specs or {}).items():
        field = str(key).strip()
        needle = str(value or "").strip()
        if not field or not needle:
            continue
        if field not in RADIATOR_SPEC_FIELDS:
            # try unit suffix alignment
            if f"{field}_mm" in RADIATOR_SPEC_FIELDS:
                field = f"{field}_mm"
            elif f"{field}_in" in RADIATOR_SPEC_FIELDS:
                field = f"{field}_in"
            else:
                continue
        qs = qs.filter(**{f"{field}__icontains": needle})
    items = await qs.order_by("material_code").limit(200)
    codes = [i.material_code for i in items]
    if oe:
        oe_norm = normalize_oe(oe)
        oe_rows = await VisionPartOe.filter(
            is_active=True, oe_normalized=oe_norm, material_code__in=codes
        ).values_list("material_code", flat=True)
        allowed = set(oe_rows)
        items = [i for i in items if i.material_code in allowed]
        codes = [i.material_code for i in items]
    if brand:
        veh = await VisionPartVehicle.filter(
            is_active=True, make_name=brand, material_code__in=codes
        ).values_list("material_code", flat=True)
        allowed = set(veh)
        items = [i for i in items if i.material_code in allowed]

    cards: list[dict[str, Any]] = []
    for item in items[:limit]:
        attrs = {
            name: getattr(item, name)
            for name in RADIATOR_SPEC_FIELDS
            if getattr(item, name, None)
        }
        cards.append(
            {
                "material_code": item.material_code,
                "sku": item.material_code,
                "name": item.material_code,
                "category": "RADIATOR",
                "attributes": attrs,
            }
        )
    return cards
