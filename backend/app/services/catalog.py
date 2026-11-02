"""App-owned product / OE / vehicle / radiator-spec catalog (ORM only)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel
from tortoise.functions import Count

from app.core.catalog_fields import RADIATOR_SPEC_FIELDS
from app.core.exceptions import AppError
from app.models import (
    OeOcrResult,
    ProductQuerySnapshot,
    RetrievalResult,
    VisionPartOe,
    VisionPartVehicle,
    VisionRadiatorSpec,
)
from app.schemas import ProductOut
from app.services.category_guard import category_cn, normalize_category_code
from app.services.similarity import SearchCandidateItem

logger = logging.getLogger(__name__)

LABEL_MATCH_LIMIT = 20
RESULT_LIMIT = 50
VEHICLE_MATERIAL_CAP = 200
_OE_REMOVED_CHARS = (" ", "\t", "-", ".", "/", "·", "・")
_VEHICLE_KEY_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


class VehicleOption(BaseModel):
    value: str
    label: str


@dataclass(frozen=True)
class ImageCandidate:
    sku: str
    score: float = 0.0
    category_cn: str | None = None
    category_id: str | None = None


@dataclass(frozen=True)
class CatalogProduct:
    material_code: str
    category_code: str | None = None


@dataclass(frozen=True)
class _MatchRow:
    display_sku: str
    material_code: str | None
    image_sku: str | None


@dataclass(frozen=True)
class CatalogVehicle:
    make_name: str | None = None
    model_name: str | None = None
    year: str | None = None


@dataclass(frozen=True)
class VehicleSelection:
    brand: str | None = None
    model: str | None = None
    year: str | None = None

    def filled(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key in ("brand", "model", "year"):
            text = str(getattr(self, key) or "").strip()
            if text:
                values[key] = text
        return values


def normalize_oe(value: str | None) -> str:
    text = str(value or "").strip().upper()
    for char in _OE_REMOVED_CHARS:
        text = text.replace(char, "")
    return text


def _clean(value: object) -> str:
    return str(value or "").strip()


def normalize_vehicle_key(value: object) -> str:
    """Collapse case / spaces / punctuation for loose vehicle token matching."""
    return _VEHICLE_KEY_RE.sub("", _clean(value).casefold())


def _option_sort_key(opt: VehicleOption) -> tuple:
    text = (opt.label or opt.value or "").strip()
    try:
        return (0, int(text))
    except ValueError:
        return (1, text.casefold())


def sort_options(options: list[VehicleOption]) -> list[VehicleOption]:
    return sorted(options, key=_option_sort_key)


def option_letter(opt: VehicleOption) -> str:
    text = (opt.label or opt.value or "").strip()
    if not text:
        return "#"
    ch = text[0].upper()
    if "A" <= ch <= "Z":
        return ch
    return "#"


def index_options(options: list[VehicleOption]) -> dict:
    sorted_opts = sort_options(options)
    groups: dict[str, list[dict]] = {}
    for opt in sorted_opts:
        letter = option_letter(opt)
        groups.setdefault(letter, []).append(opt.model_dump())
    letters = sorted(groups.keys(), key=lambda x: (x == "#", x))
    return {
        "letters": letters,
        "groups": [{"letter": letter, "items": groups[letter]} for letter in letters],
        "items": [opt.model_dump() for opt in sorted_opts],
    }


def distinct_options(values: list[object]) -> list[VehicleOption]:
    seen: set[str] = set()
    options: list[VehicleOption] = []
    for raw in values:
        text = _clean(raw)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        options.append(VehicleOption(value=text, label=text))
    return sort_options(options)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _clean(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def narrow_image_candidates(
    retrieval: RetrievalResult | None,
    image_candidates: list[ImageCandidate],
    *,
    constrained: bool,
) -> list[ImageCandidate]:
    if not image_candidates or not constrained:
        return image_candidates
    if retrieval and retrieval.accepted and retrieval.matched_sku:
        matched = _clean(retrieval.matched_sku)
        filtered = [item for item in image_candidates if item.sku == matched]
        return filtered or image_candidates
    return image_candidates[:3]


def candidates_from_retrieval(
    retrieval: RetrievalResult | None,
) -> tuple[list[ImageCandidate], bool]:
    if retrieval is None:
        return [], False
    reliable = bool(retrieval.accepted and retrieval.matched_sku)
    candidates: list[ImageCandidate] = []
    if reliable:
        candidates.append(
            ImageCandidate(
                sku=_clean(retrieval.matched_sku),
                score=float(retrieval.score or 0.0),
                category_cn=getattr(retrieval, "selected_category_cn", None),
                category_id=getattr(retrieval, "selected_category_id", None),
            )
        )
        return candidates, True

    raw = retrieval.candidates or []
    for item in raw:
        if isinstance(item, SearchCandidateItem):
            sku = _clean(item.sku)
            if not sku:
                continue
            candidates.append(
                ImageCandidate(
                    sku=sku,
                    score=float(item.score or 0.0),
                    category_cn=item.category_cn,
                    category_id=item.category_id,
                )
            )
            continue
        if isinstance(item, dict):
            sku = _clean(item.get("sku"))
            if not sku:
                continue
            candidates.append(
                ImageCandidate(
                    sku=sku,
                    score=float(item.get("score") or 0.0),
                    category_cn=item.get("category_cn"),
                    category_id=item.get("category_id"),
                )
            )
    return candidates, False


def _index_by_material(products: dict[str, CatalogProduct]) -> dict[str, list[CatalogProduct]]:
    """Map gallery SKU (== material_code) to catalog rows."""
    grouped: dict[str, list[CatalogProduct]] = {}
    for product in products.values():
        code = _clean(product.material_code)
        if not code:
            continue
        grouped.setdefault(code, []).append(product)
    return grouped


def _image_rows(
    image_skus: list[str],
    by_material: dict[str, list[CatalogProduct]],
    *,
    include_unmatched: bool,
) -> list[_MatchRow]:
    rows: list[_MatchRow] = []
    for sku in image_skus:
        matches = by_material.get(sku) or []
        if matches:
            rows.extend(
                _MatchRow(display_sku=sku, material_code=product.material_code, image_sku=sku)
                for product in matches
            )
        elif include_unmatched:
            rows.append(_MatchRow(display_sku=sku, material_code=None, image_sku=sku))
    return rows


def _code_rows(codes: list[str], catalog: dict[str, CatalogProduct]) -> list[_MatchRow]:
    rows: list[_MatchRow] = []
    for code in codes:
        rows.append(_MatchRow(display_sku=code, material_code=code if code in catalog or True else None, image_sku=None))
        # Always keep material_code as the code for OE/category lists.
        rows[-1] = _MatchRow(display_sku=code, material_code=code, image_sku=None)
    return rows


def assemble_matches(
    *,
    image_candidates: list[ImageCandidate],
    reliable_skus: bool,
    products: dict[str, CatalogProduct],
    oe_material_codes: list[str],
    fit_counts: dict[str, int],
    oe_number: str | None,
    vehicle_selected: bool,
    vehicle_resolved: bool,
    category_products: list[CatalogProduct],
    category_name: str | None,
) -> list[ProductOut]:
    """Apply OE as a hard constraint and vehicle fitment as a filter/rerank."""
    if vehicle_selected and not vehicle_resolved:
        return []

    normalized_oe = normalize_oe(oe_number)
    display_oe = _clean(oe_number).upper()
    has_oe = bool(normalized_oe)
    image_skus = _dedupe([item.sku for item in image_candidates]) if reliable_skus else []
    image_by_sku = {item.sku: item for item in image_candidates}
    catalog = dict(products)
    for item in category_products:
        catalog.setdefault(item.material_code, item)
    oe_codes = _dedupe(oe_material_codes)
    oe_set = set(oe_codes)
    label_codes = _dedupe([item.material_code for item in category_products])
    by_material = _index_by_material(catalog)

    if has_oe and reliable_skus:
        intersection = [
            row
            for row in _image_rows(image_skus, by_material, include_unmatched=False)
            if row.material_code in oe_set
        ]
        chosen = intersection or _code_rows(oe_codes, catalog)
        oe_direct = not intersection
    elif has_oe:
        chosen = _code_rows(oe_codes, catalog)
        oe_direct = True
    elif vehicle_selected and reliable_skus:
        chosen = [
            row
            for row in _image_rows(image_skus, by_material, include_unmatched=False)
            if fit_counts.get(row.material_code or "", 0) > 0
        ]
        oe_direct = False
    elif vehicle_selected:
        # Prefer SKUs that fit the vehicle (from vision_part_vehicle), not only OE-label rows.
        fit_codes = [code for code, count in fit_counts.items() if count > 0]
        ordered: list[str] = []
        seen: set[str] = set()
        for code in label_codes + fit_codes:
            if code in seen:
                continue
            if fit_counts.get(code, 0) <= 0:
                continue
            seen.add(code)
            ordered.append(code)
        chosen = _code_rows(ordered, catalog)
        oe_direct = False
    elif reliable_skus:
        chosen = _image_rows(image_skus, by_material, include_unmatched=True)
        oe_direct = False
    else:
        chosen = _code_rows(label_codes, catalog)
        oe_direct = False

    if vehicle_selected and (has_oe or reliable_skus):
        chosen = [row for row in chosen if fit_counts.get(row.material_code or "", 0) > 0]
    if not chosen:
        return []

    if vehicle_selected:
        chosen = [
            row
            for _, row in sorted(
                enumerate(chosen),
                key=lambda pair: (
                    -fit_counts.get(pair[1].material_code or "", 0),
                    pair[0],
                    pair[1].display_sku,
                    pair[1].material_code or "",
                ),
            )
        ]
    chosen = chosen[:RESULT_LIMIT]

    label_set = set(label_codes)
    results: list[ProductOut] = []
    for row in chosen:
        image = image_by_sku.get(row.image_sku) if row.image_sku else None
        product = catalog.get(row.material_code) if row.material_code else None
        code = row.material_code or ""
        reasons: list[str] = []
        if reliable_skus and image is not None and not oe_direct:
            score = f" score={image.score:.3f}" if image.score else ""
            reasons.append(f"图库匹配{score}")
        if has_oe and code in oe_set:
            reasons.append("OE关联" if oe_direct else "OE精确匹配")
        if vehicle_selected and fit_counts.get(code, 0) > 0:
            reasons.append("车型适配")
        if not reliable_skus and code in label_set and not has_oe:
            reasons.append("品类标签匹配")
        category = (
            (image.category_cn if image else None)
            or (category_cn((product.category_code or "").casefold()) if product and product.category_code else None)
            or _clean(category_name)
            or None
        )
        name = code or row.display_sku
        attributes: dict = {}
        if product:
            attributes["material_code"] = product.material_code
            if product.category_code:
                attributes["category_code"] = product.category_code
        results.append(
            ProductOut(
                sku=row.display_sku,
                name=name,
                category_name=category,
                oe_number=display_oe if has_oe and code in oe_set else None,
                brand="Reach",
                fitment=None,
                match_reason=" + ".join(reasons) or "产品目录",
                attributes=attributes,
            )
        )
    return results


def fitment_text(keys: list[str], vehicles: dict[str, CatalogVehicle]) -> str | None:
    parts: list[str] = []
    for key in keys:
        vehicle = vehicles.get(key)
        if vehicle is None:
            continue
        text = " ".join(
            piece
            for piece in (
                _clean(vehicle.make_name),
                _clean(vehicle.model_name),
                _clean(vehicle.year),
            )
            if piece
        )
        if text and text not in parts:
            parts.append(text)
        if len(parts) >= 3:
            break
    return "；".join(parts) or None


def attach_ref_nums(
    products: list[ProductOut],
    refs_by_code: dict[str, list[str]],
    oe_number: str | None = None,
) -> list[ProductOut]:
    searched = _clean(oe_number).upper()
    if normalize_oe(oe_number) and searched:
        return [product.model_copy(update={"ref_nums": [searched]}) for product in products]
    return [
        product.model_copy(
            update={
                "ref_nums": list(
                    refs_by_code.get((product.attributes or {}).get("material_code") or "", [])
                )[:1]
            }
        )
        for product in products
    ]


def apply_fitment(
    products: list[ProductOut],
    samples: dict[str, list[str]],
    vehicles: dict[str, CatalogVehicle],
) -> list[ProductOut]:
    return [
        product.model_copy(
            update={
                "fitment": fitment_text(
                    samples.get((product.attributes or {}).get("material_code") or product.sku, []),
                    vehicles,
                )
            }
        )
        for product in products
    ]


def _vehicle_filter_kwargs(selection: VehicleSelection) -> dict:
    filled = selection.filled()
    kwargs: dict = {"is_active": True}
    if "brand" in filled:
        kwargs["make_name"] = filled["brand"]
    if "model" in filled:
        kwargs["model_name"] = filled["model"]
    if "year" in filled:
        kwargs["year"] = filled["year"]
    return kwargs


class CatalogService:
    async def list_brands(self) -> list[VehicleOption]:
        rows = await VisionPartVehicle.filter(is_active=True).exclude(make_name="").values_list(
            "make_name", flat=True
        )
        return distinct_options(list(rows))

    async def list_models(self, brand: str) -> list[VehicleOption]:
        brand_v = _clean(brand)
        if not brand_v:
            return []
        rows = await VisionPartVehicle.filter(
            is_active=True, make_name=brand_v
        ).exclude(model_name=None).exclude(model_name="").values_list("model_name", flat=True)
        return distinct_options(list(rows))

    async def list_years(self, brand: str, model: str) -> list[VehicleOption]:
        brand_v = _clean(brand)
        model_v = _clean(model)
        if not brand_v or not model_v:
            return []
        rows = await VisionPartVehicle.filter(
            is_active=True, make_name=brand_v, model_name=model_v
        ).exclude(year=None).exclude(year="").values_list("year", flat=True)
        return distinct_options(list(rows))

    async def _vehicle_exists(self, selection: VehicleSelection) -> bool:
        if not selection.filled():
            return False
        return await VisionPartVehicle.filter(**_vehicle_filter_kwargs(selection)).exists()

    async def _resolve_vehicle_selection(self, selection: VehicleSelection) -> VehicleSelection:
        """Map user brand/model/year onto canonical catalog spellings (case/space/punct)."""
        filled = selection.filled()
        if not filled:
            return selection

        brand_raw = filled.get("brand")
        model_raw = filled.get("model")
        year_raw = filled.get("year")

        resolved_brand = brand_raw
        if brand_raw:
            brand_map = {
                normalize_vehicle_key(opt.value): opt.value for opt in await self.list_brands()
            }
            resolved_brand = brand_map.get(normalize_vehicle_key(brand_raw), brand_raw)

        resolved_model = model_raw
        if resolved_brand and model_raw:
            model_map = {
                normalize_vehicle_key(opt.value): opt.value
                for opt in await self.list_models(resolved_brand)
            }
            resolved_model = model_map.get(normalize_vehicle_key(model_raw), model_raw)

        resolved_year = year_raw
        if resolved_brand and resolved_model and year_raw:
            year_map = {
                normalize_vehicle_key(opt.value): opt.value
                for opt in await self.list_years(resolved_brand, resolved_model)
            }
            resolved_year = year_map.get(normalize_vehicle_key(year_raw), year_raw)

        return VehicleSelection(
            brand=resolved_brand,
            model=resolved_model,
            year=resolved_year,
        )

    async def _products_by_vehicle(
        self,
        selection: VehicleSelection,
        *,
        category_code: str | None = None,
    ) -> list[CatalogProduct]:
        """SKUs that fit the vehicle, optionally soft-filtered by OE/spec category."""
        if not selection.filled():
            return []
        rows = await VisionPartVehicle.filter(**_vehicle_filter_kwargs(selection)).values_list(
            "material_code", flat=True
        )
        codes = _dedupe(list(rows))[:VEHICLE_MATERIAL_CAP]
        if not codes:
            return []
        products = await self._products(codes)
        for code in codes:
            products.setdefault(code, CatalogProduct(material_code=code))
        items = [products[code] for code in codes if code in products]
        if not category_code:
            return items[:RESULT_LIMIT]
        kept: list[CatalogProduct] = []
        for item in items:
            code_cat = _clean(item.category_code) or None
            # Keep unknown-category vehicle SKUs so fitment-only rows still surface.
            if code_cat is None or code_cat == category_code:
                kept.append(item)
            if len(kept) >= RESULT_LIMIT:
                break
        return kept

    async def _oe_materials(self, oe_number: str, _selection: VehicleSelection | None = None) -> list[str]:
        normalized = normalize_oe(oe_number)
        if not normalized:
            return []
        rows = await VisionPartOe.filter(is_active=True, oe_normalized=normalized).values_list(
            "material_code", flat=True
        )
        return _dedupe(list(rows))

    async def _products(self, codes: list[str]) -> dict[str, CatalogProduct]:
        codes = _dedupe(codes)
        if not codes:
            return {}
        products: dict[str, CatalogProduct] = {}
        oe_rows = await VisionPartOe.filter(is_active=True, material_code__in=codes).all()
        for row in oe_rows:
            code = _clean(row.material_code)
            if not code:
                continue
            existing = products.get(code)
            if existing is None or not existing.category_code:
                products[code] = CatalogProduct(
                    material_code=code,
                    category_code=_clean(row.category) or None,
                )
        missing = [c for c in codes if c not in products]
        if missing:
            veh = await VisionPartVehicle.filter(is_active=True, material_code__in=missing).values_list(
                "material_code", flat=True
            )
            for code in _dedupe(list(veh)):
                products.setdefault(code, CatalogProduct(material_code=code))
            still = [c for c in missing if c not in products]
            if still:
                specs = await VisionRadiatorSpec.filter(is_active=True, material_code__in=still).values_list(
                    "material_code", flat=True
                )
                for code in _dedupe(list(specs)):
                    products.setdefault(
                        code,
                        CatalogProduct(material_code=code, category_code="RADIATOR"),
                    )
        return products

    async def _products_for_skus(self, skus: list[str]) -> dict[str, CatalogProduct]:
        """Gallery SKU equals material_code."""
        return await self._products(skus)

    async def _products_by_label(self, category_name: str) -> list[CatalogProduct]:
        code = normalize_category_code(category_name)
        if not code:
            # Fallback: treat as material_code search fragment
            needle = _clean(category_name)
            if not needle:
                return []
            rows = await VisionPartOe.filter(is_active=True, material_code__icontains=needle).limit(
                LABEL_MATCH_LIMIT
            )
            return [
                CatalogProduct(material_code=r.material_code, category_code=_clean(r.category) or None)
                for r in rows
            ]
        rows = await VisionPartOe.filter(is_active=True, category=code).limit(LABEL_MATCH_LIMIT * 5)
        seen: set[str] = set()
        products: list[CatalogProduct] = []
        for row in rows:
            code_m = _clean(row.material_code)
            if not code_m or code_m in seen:
                continue
            seen.add(code_m)
            products.append(CatalogProduct(material_code=code_m, category_code=code))
            if len(products) >= LABEL_MATCH_LIMIT:
                break
        return products

    async def _fit_counts(self, codes: list[str], selection: VehicleSelection) -> dict[str, int]:
        codes = _dedupe(codes)
        if not codes or not selection.filled():
            return {}
        kwargs = _vehicle_filter_kwargs(selection)
        rows = (
            await VisionPartVehicle.filter(**kwargs, material_code__in=codes)
            .annotate(fit_count=Count("id"))
            .group_by("material_code")
            .values("material_code", "fit_count")
        )
        counts: dict[str, int] = {}
        for row in rows:
            code = _clean(row.get("material_code"))
            if code:
                counts[code] = int(row.get("fit_count") or 0)
        # Fallback if annotate/group_by unsupported: count manually
        if not counts:
            items = await VisionPartVehicle.filter(**kwargs, material_code__in=codes).all()
            for item in items:
                code = _clean(item.material_code)
                if code:
                    counts[code] = counts.get(code, 0) + 1
        return counts

    async def _fitment_samples(
        self,
        codes: list[str],
        selection: VehicleSelection | None,
    ) -> tuple[dict[str, list[str]], dict[str, CatalogVehicle]]:
        codes = _dedupe(codes)
        if not codes:
            return {}, {}
        qs = VisionPartVehicle.filter(is_active=True, material_code__in=codes)
        if selection and selection.filled():
            qs = qs.filter(**{k: v for k, v in _vehicle_filter_kwargs(selection).items() if k != "is_active"})
            qs = qs.filter(is_active=True)
        items = await qs.limit(500)
        samples: dict[str, list[str]] = {}
        vehicles: dict[str, CatalogVehicle] = {}
        for item in items:
            code = _clean(item.material_code)
            if not code:
                continue
            key = f"{item.id}"
            samples.setdefault(code, []).append(key)
            vehicles[key] = CatalogVehicle(
                make_name=_clean(item.make_name) or None,
                model_name=_clean(item.model_name) or None,
                year=_clean(item.year) or None,
            )
        return samples, vehicles

    async def _ref_nums(
        self,
        codes: list[str],
        _selection: VehicleSelection | None = None,
    ) -> dict[str, list[str]]:
        codes = _dedupe(codes)
        if not codes:
            return {}
        rows = await VisionPartOe.filter(is_active=True, material_code__in=codes).all()
        refs: dict[str, list[str]] = {}
        for row in rows:
            code = _clean(row.material_code)
            oe = _clean(row.oe)
            if not code or not oe:
                continue
            bucket = refs.setdefault(code, [])
            if oe not in bucket:
                bucket.append(oe)
        return refs

    async def product_specs(self, material_code: str) -> dict[str, str]:
        code = _clean(material_code)
        if not code:
            return {}
        row = await VisionRadiatorSpec.get_or_none(material_code=code, is_active=True)
        if row is None:
            return {}
        out: dict[str, str] = {}
        for name in RADIATOR_SPEC_FIELDS:
            value = _clean(getattr(row, name, None))
            if value:
                out[name] = value
        return out

    async def attach_specs(self, products: list[ProductOut]) -> list[ProductOut]:
        codes = _dedupe(
            [
                _clean((p.attributes or {}).get("material_code") or p.sku)
                for p in products
            ]
        )
        if not codes:
            return products
        rows = await VisionRadiatorSpec.filter(is_active=True, material_code__in=codes).all()
        by_code: dict[str, dict[str, str]] = {}
        for row in rows:
            specs: dict[str, str] = {}
            for name in RADIATOR_SPEC_FIELDS:
                value = _clean(getattr(row, name, None))
                if value:
                    specs[name] = value
            if specs:
                by_code[_clean(row.material_code)] = specs
        updated: list[ProductOut] = []
        for product in products:
            attrs = dict(product.attributes or {})
            code = _clean(attrs.get("material_code") or product.sku)
            specs = by_code.get(code)
            if specs:
                attrs["specs"] = specs
            updated.append(product.model_copy(update={"attributes": attrs}))
        return updated

    async def match_products(
        self,
        *,
        image_candidates: list[ImageCandidate],
        reliable_skus: bool,
        category_name: str | None,
        oe_number: str | None,
        vehicle: VehicleSelection,
    ) -> list[ProductOut]:
        vehicle_selected = bool(vehicle.filled())
        if vehicle_selected:
            vehicle = await self._resolve_vehicle_selection(vehicle)
        vehicle_resolved = await self._vehicle_exists(vehicle) if vehicle_selected else False
        if vehicle_selected and not vehicle_resolved:
            return []

        oe_codes = await self._oe_materials(oe_number or "") if normalize_oe(oe_number) else []
        category_products: list[CatalogProduct] = []
        if not reliable_skus and not normalize_oe(oe_number) and _clean(category_name):
            category_products = await self._products_by_label(category_name or "")

        category_code = normalize_category_code(category_name) if _clean(category_name) else None
        vehicle_products: list[CatalogProduct] = []
        if vehicle_selected and vehicle_resolved:
            vehicle_products = await self._products_by_vehicle(
                vehicle, category_code=category_code
            )

        image_skus = _dedupe([item.sku for item in image_candidates]) if reliable_skus else []
        products = await self._products(
            _dedupe(
                oe_codes
                + [item.material_code for item in category_products]
                + [item.material_code for item in vehicle_products]
                + image_skus
            )
        )
        for item in category_products:
            products.setdefault(item.material_code, item)
        for item in vehicle_products:
            existing = products.get(item.material_code)
            if existing is None:
                products[item.material_code] = item
            elif not existing.category_code and item.category_code:
                products[item.material_code] = item
        fit_counts = await self._fit_counts(list(products), vehicle) if vehicle_selected else {}
        matched = assemble_matches(
            image_candidates=image_candidates,
            reliable_skus=reliable_skus,
            products=products,
            oe_material_codes=oe_codes,
            fit_counts=fit_counts,
            oe_number=oe_number,
            vehicle_selected=vehicle_selected,
            vehicle_resolved=vehicle_resolved,
            category_products=category_products,
            category_name=category_name,
        )
        material_codes = [
            str((item.attributes or {}).get("material_code"))
            for item in matched
            if (item.attributes or {}).get("material_code")
        ]
        samples, vehicles = await self._fitment_samples(
            material_codes,
            vehicle if vehicle_selected else None,
        )
        fitted = apply_fitment(matched, samples, vehicles)
        if normalize_oe(oe_number):
            with_refs = attach_ref_nums(fitted, {}, oe_number)
        else:
            refs = await self._ref_nums(material_codes)
            with_refs = attach_ref_nums(fitted, refs)
        return await self.attach_specs(with_refs)

    async def search_for_session(self, session) -> list[dict]:
        retrieval = await RetrievalResult.filter(session_id=session.id).order_by("-id").first()
        latest_ocr = await OeOcrResult.filter(session_id=session.id).order_by("-id").first()
        if session.oe_source == "ocr" and latest_ocr and not latest_ocr.confirmed_oe:
            raise AppError("请先确认铭牌识别出的 OE 号后再查询产品")

        image_candidates, reliable = candidates_from_retrieval(retrieval)
        vehicle = VehicleSelection(
            brand=session.vehicle_brand,
            model=session.vehicle_model,
            year=session.vehicle_year,
        )
        has_oe = bool(normalize_oe(session.oe_number))
        constrained = has_oe or bool(vehicle.filled())
        image_candidates = narrow_image_candidates(
            retrieval,
            image_candidates,
            constrained=constrained,
        )
        category_name = _clean(session.confirmed_category_name) or None
        if not reliable and not has_oe and not vehicle.filled() and not category_name:
            raise AppError("请先确认品类或输入 OE 号")

        products = await self.match_products(
            image_candidates=image_candidates,
            reliable_skus=reliable,
            category_name=category_name,
            oe_number=session.oe_number,
            vehicle=vehicle,
        )
        payload = [item.model_dump() for item in products]
        await ProductQuerySnapshot.create(
            session_id=session.id,
            query_payload={
                "category_name": category_name,
                "category_code": session.confirmed_category_code,
                "brand": session.vehicle_brand,
                "model": session.vehicle_model,
                "year": session.vehicle_year,
                "oe_number": session.oe_number,
                "stage": "local_catalog_products",
                "reliable_skus": reliable,
                "image_candidates": [item.sku for item in image_candidates],
            },
            result_payload=payload,
            result_count=len(payload),
        )
        logger.info(
            "Local catalog search | public_id=%s | count=%s | oe=%s | vehicle=%s",
            session.public_id,
            len(payload),
            session.oe_number,
            vehicle.filled(),
        )
        return payload


catalog_service = CatalogService()
