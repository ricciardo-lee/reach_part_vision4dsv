from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, List, Optional

import httpx
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class MdmError(RuntimeError):
    """Base error for failures while calling the MDM query service."""


class MdmConfigurationError(MdmError):
    """The query service credentials or URL are not configured."""


class MdmAuthenticationError(MdmError):
    """The query service rejected client credentials or a refreshed token."""


class MdmRequestError(MdmError):
    """The query service could not return a usable response."""


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
    """Read-only adapter for the standalone MDM query service."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = settings.MDM_QUERY_BASE_URL.rstrip("/")
        self.client_id = settings.MDM_CLIENT_ID
        self.client_secret = settings.MDM_CLIENT_SECRET
        self.timeout = settings.MDM_QUERY_TIMEOUT_SECONDS
        self.max_retries = max(0, settings.MDM_QUERY_MAX_RETRIES)
        self.token_refresh_skew = max(0, settings.MDM_TOKEN_REFRESH_SKEW_SECONDS)
        self.use_mock = settings.MDM_USE_MOCK
        self.vehicle_type = settings.MDM_VEHICLE_TYPE or "passenger"
        self.country = settings.MDM_COUNTRY or ""
        self._transport = transport
        self._client = client
        self._owns_client = client is None
        self._clock = clock
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    def _validate_configuration(self) -> None:
        if not self.base_url or not self.client_id or not self.client_secret:
            raise MdmConfigurationError(
                "MDM query service is not configured. Set MDM_QUERY_BASE_URL, "
                "MDM_CLIENT_ID and MDM_CLIENT_SECRET, or enable MDM_USE_MOCK."
            )

    async def _send_with_retries(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        client = self._get_client()
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise MdmRequestError(
                        f"MDM request failed after {attempt + 1} attempts: {method} {path}"
                    ) from exc
                continue
            if response.status_code < 500 or attempt >= self.max_retries:
                return response
        raise AssertionError("unreachable")

    async def _fetch_access_token(self) -> tuple[str, float]:
        self._validate_configuration()
        response = await self._send_with_retries(
            "POST",
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code in {400, 401, 403}:
            raise MdmAuthenticationError(
                f"MDM token request was rejected with status {response.status_code}"
            )
        if response.status_code >= 400:
            raise MdmRequestError(f"MDM token request failed with status {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise MdmRequestError("MDM token response was not valid JSON") from exc
        token_data = self._unwrap_data(payload)
        if not isinstance(token_data, dict):
            raise MdmRequestError("MDM token response has an unexpected shape")
        token = str(token_data.get("access_token") or "").strip()
        try:
            expires_in = float(token_data.get("expires_in", 300))
        except (TypeError, ValueError) as exc:
            raise MdmRequestError("MDM token response contains an invalid expires_in") from exc
        if not token or expires_in <= 0:
            raise MdmRequestError("MDM token response is missing a usable access_token")
        return token, expires_in

    def _token_is_fresh(self) -> bool:
        return bool(
            self._access_token
            and self._clock() + self.token_refresh_skew < self._token_expires_at
        )

    async def _get_access_token(self, *, force: bool = False, stale_token: str | None = None) -> str:
        if not force and self._token_is_fresh():
            return self._access_token or ""
        async with self._token_lock:
            if force and stale_token and self._access_token != stale_token and self._token_is_fresh():
                return self._access_token or ""
            if not force and self._token_is_fresh():
                return self._access_token or ""
            token, expires_in = await self._fetch_access_token()
            self._access_token = token
            self._token_expires_at = self._clock() + expires_in
            return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Any = None,
    ) -> Any:
        token = await self._get_access_token()
        response = await self._send_with_retries(
            method,
            path,
            params=params,
            json=json_body,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401:
            token = await self._get_access_token(force=True, stale_token=token)
            response = await self._send_with_retries(
                method,
                path,
                params=params,
                json=json_body,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            )
            if response.status_code == 401:
                raise MdmAuthenticationError(f"MDM rejected the refreshed token for {method} {path}")
        if response.status_code >= 400:
            detail = response.text[:300]
            raise MdmRequestError(
                f"MDM request failed with status {response.status_code}: {method} {path}; {detail}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MdmRequestError(f"MDM response was not valid JSON: {method} {path}") from exc

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json_body: Optional[dict] = None) -> Any:
        return await self._request("POST", path, json_body=json_body)

    def _unwrap_data(self, payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    async def _option_list(self, **filters: str) -> dict[str, Any]:
        params = {key: value for key, value in filters.items() if value}
        if self.country:
            params.setdefault("country", self.country)
        payload = await self._get("/api/public/v1/vehicles/options", params=params)
        data = self._unwrap_data(payload)
        if not isinstance(data, dict):
            logger.warning("MDM vehicle options unexpected shape | type=%s", type(data))
            return {}
        return data

    def _to_options(self, items: Any) -> List[VehicleOption]:
        options: List[VehicleOption] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            label = item.get("label", value)
            if value is None or value == "":
                continue
            options.append(VehicleOption(value=str(value), label=str(label)))
        return self._sort_options(options)

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
            results = await self._search_by_category(
                category_name,
                oe_number=oe_number,
                fitment=fit,
            )
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
            "/api/public/v1/products/resolve-by-oe",
            json_body={"oe_numbers": [oe_number]},
        )
        data = self._unwrap_data(payload)
        items = data.get("items", []) if isinstance(data, dict) else []
        results: List[ProductItem] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("material_code") or "").strip()
            if not sku or sku in seen:
                continue
            seen.add(sku)
            name = str(
                item.get("part_name")
                or item.get("category_name")
                or category_name
                or sku
            )
            results.append(
                ProductItem(
                    sku=sku,
                    name=name,
                    category_name=(
                        item.get("category_name")
                        or category_name
                        or name
                    ),
                    oe_number=item.get("oe_number") or oe_number,
                    brand=item.get("brand") or "Reach",
                    fitment=item.get("fitment") or fitment,
                    image_url=item.get("image_url"),
                    stock_status=item.get("stock_status"),
                    price=item.get("price"),
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
            "vehicle_type": (
                self.vehicle_type
                if self.vehicle_type in {"passenger", "truck"}
                else "passenger"
            ),
            "category_name": category_name,
            "oe_numbers": [oe_number] if oe_number else [],
            "page": 1,
            "page_size": 20,
        }
        payload = await self._post("/api/public/v1/cn-vehicle/products/search", json_body=body)
        data = self._unwrap_data(payload)
        items = data.get("items", []) if isinstance(data, dict) else []
        results: List[ProductItem] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("material_code") or "").strip()
            if not sku or sku in seen:
                continue
            seen.add(sku)
            name = str(
                item.get("part_name")
                or item.get("category_name")
                or category_name
            )
            results.append(
                ProductItem(
                    sku=sku,
                    name=name,
                    category_name=(
                        item.get("category_name")
                        or category_name
                    ),
                    oe_number=item.get("oe_number") or oe_number,
                    brand=item.get("brand") or "Reach",
                    fitment=item.get("fitment") or fitment,
                    image_url=item.get("image_url"),
                    stock_status=item.get("stock_status"),
                    price=item.get("price"),
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
