"""Read-only USA product, OE, and vehicle catalog.

DolphinScheduler refreshes the underlying tables. This module only issues
SELECT queries and never inserts, updates, or deletes catalog rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel
from tortoise import Tortoise

from app.core.config import settings
from app.core.exceptions import AppError
from app.models import OeOcrResult, ProductQuerySnapshot, RetrievalResult
from app.schemas import ProductOut
from app.services.similarity import SearchCandidateItem, SimilarityService

logger = logging.getLogger(__name__)

LABEL_MATCH_LIMIT = 20
RESULT_LIMIT = 50
REF_NUM_LIMIT = 1
_OE_REMOVED_CHARS = (" ", "\t", "-", ".", "/", "·", "・")


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
    short_num: str | None = None
    standard_label_cn: str | None = None
    standard_label_en: str | None = None
    price: int | None = None


@dataclass(frozen=True)
class _MatchRow:
    display_sku: str
    material_code: str | None
    image_sku: str | None


@dataclass(frozen=True)
class CatalogVehicle:
    reach_car_id: str
    brand: str | None = None
    series: str | None = None
    model: str | None = None
    model_year: str | None = None


@dataclass(frozen=True)
class VehicleSelection:
    brand: str | None = None
    series: str | None = None
    model: str | None = None
    year: str | None = None

    def filled(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key in ("brand", "series", "model", "year"):
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


def _cell(row: object, key: str, index: int) -> object:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _product_from_row(row: object) -> CatalogProduct | None:
    code = _clean(_cell(row, "material_code", 0))
    if not code:
        return None
    raw_price = _cell(row, "price", 4)
    try:
        price = int(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        price = None
    return CatalogProduct(
        material_code=code,
        short_num=_clean(_cell(row, "short_num", 1)) or None,
        standard_label_cn=_clean(_cell(row, "standard_label_cn", 2)) or None,
        standard_label_en=_clean(_cell(row, "standard_label_en", 3)) or None,
        price=price,
    )


def _option_sort_key(opt: VehicleOption) -> tuple:
    text = (opt.label or opt.value or "").strip()
    try:
        from pypinyin import lazy_pinyin

        phonetic = "".join(lazy_pinyin(text)).casefold()
    except Exception:  # noqa: BLE001
        phonetic = text.casefold()
    return (phonetic, opt.value.casefold(), opt.label)


def sort_options(options: list[VehicleOption]) -> list[VehicleOption]:
    return sorted(options, key=_option_sort_key)


def option_letter(opt: VehicleOption) -> str:
    text = (opt.label or opt.value or "").strip()
    try:
        from pypinyin import lazy_pinyin

        phonetic = "".join(lazy_pinyin(text)).strip()
    except Exception:  # noqa: BLE001
        phonetic = text
    if not phonetic:
        return "#"
    char = phonetic[0].upper()
    if "A" <= char <= "Z":
        return char
    return "#"


def index_options(options: list[VehicleOption]) -> dict:
    groups_map: dict[str, list[dict]] = {}
    flat: list[dict] = []
    for opt in sort_options(list(options)):
        letter = option_letter(opt)
        item = {"value": opt.value, "label": opt.label, "letter": letter}
        flat.append(item)
        groups_map.setdefault(letter, []).append(item)
    letters = [char for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if char in groups_map]
    if "#" in groups_map:
        letters.append("#")
    groups = [{"letter": letter, "items": groups_map[letter]} for letter in letters]
    return {"letters": letters, "groups": groups, "items": flat}


def distinct_options(values: list[object]) -> list[VehicleOption]:
    seen: dict[str, VehicleOption] = {}
    for raw in values:
        text = _clean(raw)
        if text and text not in seen:
            seen[text] = VehicleOption(value=text, label=text)
    return sort_options(list(seen.values()))


def year_options(rows: list[tuple[str, str, str]]) -> list[VehicleOption]:
    years: set[str] = set()
    for model_year, year_from, year_till in rows:
        current = _clean(model_year)
        if current:
            years.add(current)
            continue
        start = _clean(year_from)
        end = _clean(year_till)
        if start.isdigit() and end.isdigit():
            left, right = int(start), int(end)
            if 0 <= right - left <= 40:
                years.update(str(year) for year in range(left, right + 1))
    ordered = sorted(years, key=lambda item: (not item.isdigit(), int(item) if item.isdigit() else item))

    def label_for(year: str) -> str:
        return f"{year}款" if year.isdigit() else year

    return [VehicleOption(value=year, label=label_for(year)) for year in ordered]


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _normalized_ref_sql(column: str = "ref_num") -> str:
    expression = f"TRIM(IFNULL({column}, ''))"
    for char in _OE_REMOVED_CHARS:
        expression = f"REPLACE({expression}, '{char}', '')"
    return f"UPPER({expression})"


def vehicle_predicates(selection: VehicleSelection, alias: str = "v") -> tuple[str, list]:
    filled = selection.filled()
    clauses = [
        f"{alias}.reach_car_id IS NOT NULL",
        f"TRIM({alias}.reach_car_id) <> ''",
    ]
    params: list = []
    for column in ("brand", "series", "model"):
        if column in filled:
            clauses.append(f"TRIM({alias}.{column}) = %s")
            params.append(filled[column])
    year = filled.get("year")
    if year:
        if year.isdigit():
            clauses.append(
                "("
                f"TRIM(IFNULL({alias}.model_year, '')) = %s OR ("
                f"{alias}.year_from REGEXP '^[0-9]+$' AND {alias}.year_till REGEXP '^[0-9]+$' "
                f"AND CAST({alias}.year_from AS SIGNED) <= %s "
                f"AND CAST({alias}.year_till AS SIGNED) >= %s)"
                ")"
            )
            number = int(year)
            params.extend([year, number, number])
        else:
            clauses.append(f"TRIM(IFNULL({alias}.model_year, '')) = %s")
            params.append(year)
    return " AND ".join(clauses), params


def _chunks(values: list[str], size: int = 400) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def narrow_image_candidates(
    retrieval: RetrievalResult | None,
    candidates: list[ImageCandidate],
    *,
    constrained: bool,
) -> list[ImageCandidate]:
    """Keep the historical product order when the user supplied no OE or vehicle."""
    if constrained or retrieval is None:
        return candidates
    if retrieval.accepted and retrieval.matched_sku:
        matched = next((item for item in candidates if item.sku == retrieval.matched_sku), None)
        if matched:
            return [matched]
        return [
            ImageCandidate(
                sku=retrieval.matched_sku,
                score=float(retrieval.score or 0),
                category_cn=retrieval.selected_category_cn,
                category_id=retrieval.selected_category_id,
            )
        ]
    if retrieval.decision == "category_match" and retrieval.selected_category_id:
        ranked = SimilarityService.filter_same_category_skus(
            [
                SearchCandidateItem(
                    sku=item.sku,
                    category_id=item.category_id,
                    category_cn=item.category_cn,
                    score=item.score,
                )
                for item in candidates
            ],
            retrieval.selected_category_id,
            top_n=settings.SEARCH_CATEGORY_TOP_N,
            relative_floor=settings.SEARCH_CATEGORY_RELATIVE_FLOOR,
            min_score=settings.SEARCH_CATEGORY_MIN_SCORE,
        )
        return [
            ImageCandidate(
                sku=item.sku,
                score=float(item.score),
                category_cn=item.category_cn,
                category_id=item.category_id,
            )
            for item in ranked
        ]
    return candidates


def candidates_from_retrieval(retrieval: RetrievalResult | None) -> tuple[list[ImageCandidate], bool]:
    if retrieval is None:
        return [], False
    best: dict[str, ImageCandidate] = {}
    for item in retrieval.candidates or []:
        if not isinstance(item, dict):
            continue
        sku = _clean(item.get("sku"))
        if not sku:
            continue
        try:
            score = float(item.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        current = ImageCandidate(
            sku=sku,
            score=score,
            category_cn=_clean(item.get("category_cn")) or None,
            category_id=_clean(item.get("category_id")) or None,
        )
        previous = best.get(sku)
        if previous is None or current.score > previous.score:
            best[sku] = current
    ordered = sorted(best.values(), key=lambda item: (-item.score, item.sku))
    reliable = bool(retrieval.accepted and retrieval.matched_sku) or retrieval.decision == "category_match"
    if retrieval.accepted and retrieval.matched_sku and retrieval.matched_sku not in best:
        ordered.insert(
            0,
            ImageCandidate(
                sku=retrieval.matched_sku,
                score=float(retrieval.score or 0),
                category_cn=retrieval.selected_category_cn,
                category_id=retrieval.selected_category_id,
            ),
        )
    if not reliable:
        return [], False
    return ordered, True


def _index_by_short_num(products: dict[str, CatalogProduct]) -> dict[str, list[CatalogProduct]]:
    """Map gallery SKUs to catalog rows. Retrieval SKU equals short_num, not material_code."""
    grouped: dict[str, list[CatalogProduct]] = {}
    for product in products.values():
        short = _clean(product.short_num)
        if not short:
            continue
        grouped.setdefault(short, []).append(product)
    for items in grouped.values():
        items.sort(key=lambda item: item.material_code)
    return grouped


def _image_rows(
    image_skus: list[str],
    by_short: dict[str, list[CatalogProduct]],
    *,
    include_unmatched: bool,
) -> list[_MatchRow]:
    rows: list[_MatchRow] = []
    for sku in image_skus:
        matches = by_short.get(sku) or []
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
        product = catalog.get(code)
        short = _clean(product.short_num) if product else ""
        rows.append(_MatchRow(display_sku=short or code, material_code=code, image_sku=None))
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
    by_short = _index_by_short_num(catalog)

    if has_oe and reliable_skus:
        intersection = [
            row
            for row in _image_rows(image_skus, by_short, include_unmatched=False)
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
            for row in _image_rows(image_skus, by_short, include_unmatched=False)
            if fit_counts.get(row.material_code or "", 0) > 0
        ]
        oe_direct = False
    elif vehicle_selected:
        chosen = [
            row
            for row in _code_rows(label_codes, catalog)
            if fit_counts.get(row.material_code or "", 0) > 0
        ]
        oe_direct = False
    elif reliable_skus:
        chosen = _image_rows(image_skus, by_short, include_unmatched=True)
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
            or _clean(category_name)
            or None
        )
        name = ""
        if product:
            name = _clean(product.standard_label_cn) or _clean(product.standard_label_en)
        if not name:
            name = f"{category or '产品'} {row.display_sku}"
        attributes = {}
        if product:
            attributes["material_code"] = product.material_code
            short = _clean(product.short_num)
            if short:
                attributes["short_num"] = short
        price = float(product.price) if product and product.price is not None else None
        results.append(
            ProductOut(
                sku=row.display_sku,
                name=name,
                category_name=category,
                oe_number=display_oe if has_oe and code in oe_set else None,
                brand="Reach",
                fitment=None,
                price=price,
                match_reason=" + ".join(reasons) or "产品目录",
                attributes=attributes,
            )
        )
    return results


def fitment_text(car_ids: list[str], vehicles: dict[str, CatalogVehicle]) -> str | None:
    parts: list[str] = []
    for car_id in car_ids:
        vehicle = vehicles.get(car_id)
        if vehicle is None:
            continue
        text = " / ".join(
            piece
            for piece in (
                _clean(vehicle.brand),
                _clean(vehicle.series),
                _clean(vehicle.model),
                _clean(vehicle.model_year),
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
    """Show the searched part number, otherwise only the first adapted ref_num."""
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


class CatalogService:
    async def _fetch(self, sql: str, params: list | None = None) -> list:
        try:
            connection = Tortoise.get_connection("default")
            dialect = getattr(getattr(connection, "capabilities", None), "dialect", "")
            if dialect == "sqlite":
                sql = sql.replace("%s", "?")
            _, rows = await connection.execute_query(sql, params or [])
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Catalog query failed")
            raise AppError(
                "产品目录暂不可用",
                code="product_catalog_unavailable",
                status_code=503,
            ) from exc
        return list(rows or [])

    async def list_brands(self) -> list[VehicleOption]:
        rows = await self._fetch(
            "SELECT DISTINCT TRIM(brand) AS value FROM vehicle_basic_info_usa "
            "WHERE brand IS NOT NULL AND TRIM(brand) <> ''"
        )
        return distinct_options([_cell(row, "value", 0) for row in rows])

    async def list_series(self, brand: str) -> list[VehicleOption]:
        rows = await self._fetch(
            "SELECT DISTINCT TRIM(series) AS value FROM vehicle_basic_info_usa "
            "WHERE TRIM(brand) = %s AND series IS NOT NULL AND TRIM(series) <> ''",
            [_clean(brand)],
        )
        return distinct_options([_cell(row, "value", 0) for row in rows])

    async def list_models(self, brand: str, series: str) -> list[VehicleOption]:
        rows = await self._fetch(
            "SELECT DISTINCT TRIM(model) AS value FROM vehicle_basic_info_usa "
            "WHERE TRIM(brand) = %s AND TRIM(series) = %s "
            "AND model IS NOT NULL AND TRIM(model) <> ''",
            [_clean(brand), _clean(series)],
        )
        return distinct_options([_cell(row, "value", 0) for row in rows])

    async def list_years(self, brand: str, series: str, model: str) -> list[VehicleOption]:
        rows = await self._fetch(
            "SELECT TRIM(model_year) AS model_year, TRIM(year_from) AS year_from, "
            "TRIM(year_till) AS year_till FROM vehicle_basic_info_usa "
            "WHERE TRIM(brand) = %s AND TRIM(series) = %s AND TRIM(model) = %s",
            [_clean(brand), _clean(series), _clean(model)],
        )
        parsed = [
            (
                _clean(_cell(row, "model_year", 0)),
                _clean(_cell(row, "year_from", 1)),
                _clean(_cell(row, "year_till", 2)),
            )
            for row in rows
        ]
        return year_options(parsed)

    async def _vehicle_exists(self, selection: VehicleSelection) -> bool:
        where, params = vehicle_predicates(selection)
        rows = await self._fetch(
            f"SELECT reach_car_id FROM vehicle_basic_info_usa v WHERE {where} LIMIT 1",
            params,
        )
        return bool(rows)

    async def _oe_materials(self, oe_number: str, selection: VehicleSelection | None) -> list[str]:
        normalized = normalize_oe(oe_number)
        if not normalized:
            return []
        params: list = [normalized]
        join = ""
        where = f"{_normalized_ref_sql('l.ref_num')} = %s"
        if selection and selection.filled():
            vehicle_where, vehicle_params = vehicle_predicates(selection)
            join = "INNER JOIN vehicle_basic_info_usa v ON v.reach_car_id = l.reach_car_id"
            where = f"{where} AND {vehicle_where}"
            params.extend(vehicle_params)
        rows = await self._fetch(
            "SELECT DISTINCT TRIM(l.material_code) AS material_code "
            "FROM product_oe_vehicle_usa l "
            f"{join} "
            "WHERE l.material_code IS NOT NULL AND TRIM(l.material_code) <> '' "
            f"AND {where} ORDER BY material_code",
            params,
        )
        return [_clean(_cell(row, "material_code", 0)) for row in rows if _clean(_cell(row, "material_code", 0))]

    async def _products(self, codes: list[str]) -> dict[str, CatalogProduct]:
        codes = _dedupe(codes)
        if not codes:
            return {}
        products: dict[str, CatalogProduct] = {}
        for chunk in _chunks(codes):
            placeholders = ", ".join(["%s"] * len(chunk))
            rows = await self._fetch(
                "SELECT material_code, short_num, standard_label_cn, standard_label_en, price "
                f"FROM product_basic_info_usa WHERE material_code IN ({placeholders})",
                chunk,
            )
            for row in rows:
                product = _product_from_row(row)
                if product is None:
                    continue
                products[product.material_code] = product
        return products

    async def _products_for_short_nums(self, skus: list[str]) -> dict[str, CatalogProduct]:
        """Load catalog rows whose short_num is a gallery SKU."""
        skus = _dedupe([_clean(sku) for sku in skus])
        if not skus:
            return {}
        products: dict[str, CatalogProduct] = {}
        for chunk in _chunks(skus):
            placeholders = ", ".join(["%s"] * len(chunk))
            rows = await self._fetch(
                "SELECT material_code, short_num, standard_label_cn, standard_label_en, price "
                "FROM product_basic_info_usa "
                f"WHERE short_num IS NOT NULL AND TRIM(short_num) IN ({placeholders})",
                chunk,
            )
            for row in rows:
                product = _product_from_row(row)
                if product is None:
                    continue
                products[product.material_code] = product
        return products

    async def _products_by_label(self, category_name: str) -> list[CatalogProduct]:
        label = _clean(category_name)
        if not label:
            return []
        pattern = _like_pattern(label)
        rows = await self._fetch(
            "SELECT material_code, short_num, standard_label_cn, standard_label_en, price "
            "FROM product_basic_info_usa "
            "WHERE standard_label_cn LIKE %s ESCAPE '\\\\' "
            "OR standard_label_en LIKE %s ESCAPE '\\\\' "
            "ORDER BY CASE WHEN standard_label_cn LIKE %s ESCAPE '\\\\' THEN 0 ELSE 1 END, "
            "material_code LIMIT %s",
            [pattern, pattern, pattern, LABEL_MATCH_LIMIT],
        )
        products: list[CatalogProduct] = []
        for row in rows:
            product = _product_from_row(row)
            if product is not None:
                products.append(product)
        return products

    async def _fit_counts(self, codes: list[str], selection: VehicleSelection) -> dict[str, int]:
        codes = _dedupe(codes)
        if not codes or not selection.filled():
            return {}
        where, params = vehicle_predicates(selection)
        counts: dict[str, int] = {}
        for chunk in _chunks(codes):
            placeholders = ", ".join(["%s"] * len(chunk))
            rows = await self._fetch(
                "SELECT l.material_code AS material_code, COUNT(DISTINCT l.reach_car_id) AS fit_count "
                "FROM product_oe_vehicle_usa l "
                "INNER JOIN vehicle_basic_info_usa v ON v.reach_car_id = l.reach_car_id "
                f"WHERE l.material_code IN ({placeholders}) AND {where} "
                "GROUP BY l.material_code",
                [*chunk, *params],
            )
            for row in rows:
                code = _clean(_cell(row, "material_code", 0))
                if not code:
                    continue
                try:
                    counts[code] = int(_cell(row, "fit_count", 1) or 0)
                except (TypeError, ValueError):
                    counts[code] = 0
        return counts

    async def _fitment_samples(
        self,
        codes: list[str],
        selection: VehicleSelection | None,
    ) -> tuple[dict[str, list[str]], dict[str, CatalogVehicle]]:
        codes = _dedupe(codes)
        if not codes:
            return {}, {}
        placeholders = ", ".join(["%s"] * len(codes))
        params: list = list(codes)
        join = "INNER JOIN vehicle_basic_info_usa v ON v.reach_car_id = l.reach_car_id"
        where = "1 = 1"
        if selection and selection.filled():
            where, vehicle_params = vehicle_predicates(selection)
            params.extend(vehicle_params)
        rows = await self._fetch(
            "SELECT material_code, reach_car_id FROM ("
            "SELECT material_code, reach_car_id, "
            "ROW_NUMBER() OVER (PARTITION BY material_code ORDER BY reach_car_id) AS rn "
            "FROM ("
            "SELECT DISTINCT l.material_code AS material_code, l.reach_car_id AS reach_car_id "
            "FROM product_oe_vehicle_usa l "
            f"{join} WHERE l.material_code IN ({placeholders}) AND {where}"
            ") distinct_links"
            ") ranked WHERE rn <= 3",
            params,
        )
        samples: dict[str, list[str]] = {}
        car_ids: list[str] = []
        for row in rows:
            code = _clean(_cell(row, "material_code", 0))
            car_id = _clean(_cell(row, "reach_car_id", 1))
            if not code or not car_id:
                continue
            samples.setdefault(code, [])
            if car_id not in samples[code]:
                samples[code].append(car_id)
            car_ids.append(car_id)
        return samples, await self._vehicles(_dedupe(car_ids))

    async def _ref_nums(
        self,
        codes: list[str],
        selection: VehicleSelection | None,
    ) -> dict[str, list[str]]:
        """First adapted part number for each material. Vehicle selection narrows the links."""
        codes = _dedupe(codes)
        if not codes:
            return {}
        placeholders = ", ".join(["%s"] * len(codes))
        params: list = list(codes)
        join = ""
        where = "l.ref_num IS NOT NULL AND TRIM(l.ref_num) <> ''"
        if selection and selection.filled():
            join = "INNER JOIN vehicle_basic_info_usa v ON v.reach_car_id = l.reach_car_id"
            vehicle_where, vehicle_params = vehicle_predicates(selection)
            where = f"{where} AND {vehicle_where}"
            params.extend(vehicle_params)
        rows = await self._fetch(
            "SELECT material_code, ref_num FROM ("
            "SELECT material_code, ref_num, "
            "ROW_NUMBER() OVER (PARTITION BY material_code ORDER BY ref_num) AS rn "
            "FROM ("
            "SELECT DISTINCT TRIM(l.material_code) AS material_code, TRIM(l.ref_num) AS ref_num "
            "FROM product_oe_vehicle_usa l "
            f"{join} WHERE l.material_code IN ({placeholders}) AND {where}"
            ") distinct_refs"
            f") ranked WHERE rn <= {REF_NUM_LIMIT}",
            params,
        )
        refs: dict[str, list[str]] = {}
        for row in rows:
            code = _clean(_cell(row, "material_code", 0))
            ref_num = _clean(_cell(row, "ref_num", 1))
            if not code or not ref_num:
                continue
            bucket = refs.setdefault(code, [])
            if ref_num not in bucket:
                bucket.append(ref_num)
        return refs

    async def _vehicles(self, car_ids: list[str]) -> dict[str, CatalogVehicle]:
        if not car_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(car_ids))
        rows = await self._fetch(
            "SELECT reach_car_id, brand, series, model, model_year "
            f"FROM vehicle_basic_info_usa WHERE reach_car_id IN ({placeholders})",
            car_ids,
        )
        vehicles: dict[str, CatalogVehicle] = {}
        for row in rows:
            car_id = _clean(_cell(row, "reach_car_id", 0))
            if not car_id:
                continue
            vehicles[car_id] = CatalogVehicle(
                reach_car_id=car_id,
                brand=_clean(_cell(row, "brand", 1)) or None,
                series=_clean(_cell(row, "series", 2)) or None,
                model=_clean(_cell(row, "model", 3)) or None,
                model_year=_clean(_cell(row, "model_year", 4)) or None,
            )
        return vehicles

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
        vehicle_resolved = await self._vehicle_exists(vehicle) if vehicle_selected else False
        if vehicle_selected and not vehicle_resolved:
            return []

        oe_codes = await self._oe_materials(oe_number or "", None) if normalize_oe(oe_number) else []
        category_products = []
        if not reliable_skus and not normalize_oe(oe_number) and _clean(category_name):
            category_products = await self._products_by_label(category_name or "")

        image_skus = _dedupe([item.sku for item in image_candidates]) if reliable_skus else []
        products = await self._products(
            _dedupe(oe_codes + [item.material_code for item in category_products])
        )
        products.update(await self._products_for_short_nums(image_skus))
        for item in category_products:
            products.setdefault(item.material_code, item)
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
            return attach_ref_nums(fitted, {}, oe_number)
        refs = await self._ref_nums(material_codes, vehicle if vehicle_selected else None)
        return attach_ref_nums(fitted, refs)

    async def search_for_session(self, session) -> list[dict]:
        retrieval = await RetrievalResult.filter(session_id=session.id).order_by("-id").first()
        latest_ocr = await OeOcrResult.filter(session_id=session.id).order_by("-id").first()
        if session.oe_source == "ocr" and latest_ocr and not latest_ocr.confirmed_oe:
            raise AppError("请先确认铭牌识别出的 OE 号后再查询产品")

        image_candidates, reliable = candidates_from_retrieval(retrieval)
        vehicle = VehicleSelection(
            brand=session.vehicle_brand,
            series=session.vehicle_series,
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
                "series": session.vehicle_series,
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
