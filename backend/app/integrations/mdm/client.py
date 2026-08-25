from __future__ import annotations

import logging
from typing import Any, List, Optional

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class VehicleOption(BaseModel):
    value: str
    label: str


class ProductItem(BaseModel):
    sku: str
    name: str
    category_name: Optional[str] = None
    oe_number: Optional[str] = None
    brand: Optional[str] = None
    fitment: Optional[str] = None
    image_url: Optional[str] = None
    stock_status: Optional[str] = None
    price: Optional[float] = None
    match_reason: Optional[str] = None


class MdmAdapter:
    """Read-only adapter for company MDM manage APIs. Falls back to mock when MDM_USE_MOCK=true."""

    def __init__(self) -> None:
        self.base_url = settings.MDM_API_BASE_URL.rstrip("/")
        self.token = settings.MDM_API_TOKEN
        self.timeout = settings.MDM_TIMEOUT_SECONDS
        self.use_mock = settings.MDM_USE_MOCK
        self.vehicle_type = settings.MDM_VEHICLE_TYPE or "passenger"
        self.country = settings.MDM_COUNTRY or ""

    def _headers(self) -> dict:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            # Reach MDM expects header `token`, not Authorization Bearer.
            headers["token"] = self.token
        return headers

    async def _request(self, method: str, path: str, *, params: Optional[dict] = None, json_body: Any = None) -> Any:
        if not self.use_mock and not self.token:
            raise RuntimeError(
                "MDM_API_TOKEN is empty. Set it in backend/.env "
                "(local MDM accepts token=dev) or set MDM_USE_MOCK=true."
            )
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._headers(),
            )
            if response.status_code == 422:
                detail = ""
                try:
                    detail = response.text[:300]
                except Exception:  # noqa: BLE001
                    detail = ""
                logger.error("MDM 422 | %s %s | params=%s | body=%s", method, path, params, detail)
            response.raise_for_status()
            return response.json()

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json_body: Optional[dict] = None) -> Any:
        return await self._request("POST", path, json_body=json_body)

    def _unwrap_data(self, payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    async def _option_list(self, **filters: str) -> dict:
        params = {k: v for k, v in filters.items() if v}
        if self.country:
            params.setdefault("country", self.country)
        payload = await self._get("/api/manage/cars/option_list", params=params)
        data = self._unwrap_data(payload)
        if not isinstance(data, dict):
            logger.warning("MDM option_list unexpected shape | keys=%s", type(data))
            return {}
        return data

    def _to_options(self, items: Any) -> List[VehicleOption]:
        results: List[VehicleOption] = []
        for item in items or []:
            if isinstance(item, dict):
                value = item.get("value")
                label = item.get("label", value)
            else:
                value = item
                label = item
            if value is None or value == "":
                continue
            results.append(VehicleOption(value=str(value), label=str(label)))
        return self._sort_options(results)

    @staticmethod
    def _option_sort_key(opt: VehicleOption) -> tuple:
        """Alphabetical key: Latin A-Z / Chinese pinyin when available."""
        label = (opt.label or "").strip()
        value = (opt.value or "").strip()
        text = label or value
        try:
            from pypinyin import lazy_pinyin

            phonetic = "".join(lazy_pinyin(text)).casefold()
        except Exception:  # noqa: BLE001
            phonetic = text.casefold()
        return (phonetic, value.casefold(), label)

    def _sort_options(self, options: List[VehicleOption]) -> List[VehicleOption]:
        return sorted(options, key=self._option_sort_key)

    @staticmethod
    def option_letter(opt: VehicleOption) -> str:
        """Index letter A-Z, or '#' for digits / others."""
        label = (opt.label or "").strip()
        value = (opt.value or "").strip()
        text = label or value
        try:
            from pypinyin import lazy_pinyin

            phonetic = "".join(lazy_pinyin(text)).strip()
        except Exception:  # noqa: BLE001
            phonetic = text
        if not phonetic:
            return "#"
        ch = phonetic[0].upper()
        if "A" <= ch <= "Z":
            return ch
        return "#"

    def index_options(self, options: List[VehicleOption]) -> dict:
        """Group sorted options for sidebar letter navigation."""
        sorted_opts = self._sort_options(list(options))
        groups_map: dict[str, list[dict]] = {}
        flat: list[dict] = []
        for opt in sorted_opts:
            letter = self.option_letter(opt)
            item = {"value": opt.value, "label": opt.label, "letter": letter}
            flat.append(item)
            groups_map.setdefault(letter, []).append(item)

        letters = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c in groups_map]
        if "#" in groups_map:
            letters.append("#")
        groups = [{"letter": letter, "items": groups_map[letter]} for letter in letters]
        return {"letters": letters, "groups": groups, "items": flat}

    async def list_brands(self) -> List[VehicleOption]:
        if self.use_mock:
            return self._sort_options(
                [
                    VehicleOption(value="BMW", label="宝马"),
                    VehicleOption(value="BENZ", label="奔驰"),
                    VehicleOption(value="AUDI", label="奥迪"),
                    VehicleOption(value="TOYOTA", label="丰田"),
                ]
            )
        data = await self._option_list()
        return self._to_options(data.get("brand"))

    async def list_series(self, brand: str) -> List[VehicleOption]:
        if self.use_mock:
            mapping = {
                "BMW": [VehicleOption(value="3Series", label="3系"), VehicleOption(value="5Series", label="5系")],
                "BENZ": [VehicleOption(value="CClass", label="C级"), VehicleOption(value="EClass", label="E级")],
                "AUDI": [VehicleOption(value="A4", label="A4"), VehicleOption(value="A6", label="A6")],
                "TOYOTA": [VehicleOption(value="Camry", label="凯美瑞"), VehicleOption(value="Corolla", label="卡罗拉")],
            }
            return self._sort_options(mapping.get(brand, []))
        data = await self._option_list(brand=brand)
        return self._to_options(data.get("series"))

    async def list_models(self, brand: str, series: str) -> List[VehicleOption]:
        if self.use_mock:
            return self._sort_options(
                [
                    VehicleOption(value=f"{series}-STD", label=f"{series} 标准型"),
                    VehicleOption(value=f"{series}-SPORT", label=f"{series} 运动型"),
                ]
            )
        data = await self._option_list(brand=brand, series=series)
        return self._to_options(data.get("model"))

    async def list_years(self, brand: str, series: str, model: str) -> List[VehicleOption]:
        if self.use_mock:
            return self._sort_options(
                [VehicleOption(value=str(y), label=f"{y}款") for y in range(2018, 2026)]
            )
        data = await self._option_list(brand=brand, series=series, model=model)
        return self._to_options(data.get("model_year"))

    async def search_products(
        self,
        *,
        category_name: Optional[str] = None,
        category_code: Optional[str] = None,
        brand: Optional[str] = None,
        series: Optional[str] = None,
        model: Optional[str] = None,
        year: Optional[str] = None,
        oe_number: Optional[str] = None,
    ) -> List[ProductItem]:
        if self.use_mock:
            return self._mock_products(category_name, oe_number, brand, series, model, year)

        fit = " / ".join([x for x in [brand, series, model, year] if x]) or None
        results: List[ProductItem] = []

        if oe_number:
            results = await self._search_by_oe(oe_number, category_name=category_name, fitment=fit)
            if results:
                return results

        if category_name:
            results = await self._search_by_category(category_name, oe_number=oe_number, fitment=fit)
            if results:
                return results

        logger.info(
            "MDM search empty | category=%s | code=%s | oe=%s | brand=%s",
            category_name,
            category_code,
            oe_number,
            brand,
        )
        return []

    async def _search_by_oe(
        self,
        oe_number: str,
        *,
        category_name: Optional[str],
        fitment: Optional[str],
    ) -> List[ProductItem]:
        payload = await self._post(
            "/api/manage/products/check_product_exist",
            json_body={"oe": oe_number},
        )
        if isinstance(payload, dict) and payload.get("code") not in (None, 200, 0, "0", "200"):
            logger.warning(
                "MDM check_product_exist non-ok | code=%s | msg=%s",
                payload.get("code"),
                payload.get("msg"),
            )
        items = self._unwrap_data(payload) or []
        results: List[ProductItem] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("Materiel_Number") or item.get("material_code") or "").strip()
            if not sku or sku in seen:
                continue
            seen.add(sku)
            name = str(item.get("part_name") or item.get("Standard_Name") or category_name or sku)
            results.append(
                ProductItem(
                    sku=sku,
                    name=name,
                    category_name=category_name or name,
                    oe_number=oe_number,
                    brand="Reach",
                    fitment=fitment,
                    match_reason="OE精确匹配",
                )
            )
        return results

    async def _search_by_category(
        self,
        category_name: str,
        *,
        oe_number: Optional[str],
        fitment: Optional[str],
    ) -> List[ProductItem]:
        body: dict[str, Any] = {
            "vehicle_type": self.vehicle_type if self.vehicle_type in {"passenger", "truck"} else "passenger",
            "category_name": category_name,
            "page": 1,
            "page_size": 20,
        }
        if oe_number:
            body["oe_numbers"] = oe_number
        payload = await self._post("/api/manage/cn_vehicle/search", json_body=body)
        if isinstance(payload, dict) and payload.get("code") not in (None, 200, 0, "0", "200"):
            logger.warning(
                "MDM cn_vehicle/search non-ok | code=%s | msg=%s",
                payload.get("code"),
                payload.get("msg"),
            )
        items = self._unwrap_data(payload) or []
        results: List[ProductItem] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("reach_number") or item.get("Materiel_Number") or "").strip()
            if not sku or sku in seen:
                continue
            seen.add(sku)
            name = str(item.get("category_name") or category_name)
            results.append(
                ProductItem(
                    sku=sku,
                    name=name,
                    category_name=item.get("category_name") or category_name,
                    oe_number=oe_number,
                    brand="Reach",
                    fitment=fitment,
                    match_reason="品类匹配",
                )
            )
        return results

    def _mock_products(
        self,
        category_name: Optional[str],
        oe_number: Optional[str],
        brand: Optional[str],
        series: Optional[str],
        model: Optional[str],
        year: Optional[str],
    ) -> List[ProductItem]:
        category = category_name or "通用零件"
        oe = oe_number or "OE-UNKNOWN"
        fit = " / ".join([x for x in [brand, series, model, year] if x]) or "通用适配"
        return [
            ProductItem(
                sku=f"RP-{oe[-6:] or '000001'}",
                name=f"瑞琦{category}",
                category_name=category,
                oe_number=oe if oe_number else None,
                brand="Reach",
                fitment=fit,
                image_url=None,
                stock_status="有货",
                price=128.0,
                match_reason="品类匹配" + (" + OE精确匹配" if oe_number else " + 车型适配"),
            ),
            ProductItem(
                sku=f"RP-{oe[-6:] or '000002'}-A",
                name=f"瑞琦{category}加强版",
                category_name=category,
                oe_number=oe if oe_number else None,
                brand="Reach",
                fitment=fit,
                image_url=None,
                stock_status="有货",
                price=168.0,
                match_reason="品类匹配",
            ),
        ]


mdm_adapter = MdmAdapter()
