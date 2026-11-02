"""Supported part-category allowlist (Compressor / Condenser / Radiator only)."""

from __future__ import annotations

from typing import Optional

from app.core.constants import (
    CATEGORY_CN,
    CATEGORY_EN,
    SUPPORTED_CATEGORY_CODES,
    SUPPORTED_CATEGORY_IDS,
)
from app.core.exceptions import AppError

# Map many aliases → canonical lowercase id.
_ALIAS_TO_ID: dict[str, str] = {}
for _id, cn in CATEGORY_CN.items():
    _ALIAS_TO_ID[_id.casefold()] = _id
    _ALIAS_TO_ID[cn.casefold()] = _id
for key, en in CATEGORY_EN.items():
    _id = key.casefold()
    if _id in SUPPORTED_CATEGORY_IDS:
        _ALIAS_TO_ID[_id] = _id
        _ALIAS_TO_ID[str(en).casefold()] = _id
    elif str(en).casefold() in {CATEGORY_EN.get(i, "").casefold() for i in SUPPORTED_CATEGORY_IDS}:
        # English label → id
        for sid in SUPPORTED_CATEGORY_IDS:
            if CATEGORY_EN.get(sid, "").casefold() == str(en).casefold():
                _ALIAS_TO_ID[key.casefold()] = sid
                _ALIAS_TO_ID[str(en).casefold()] = sid
                break

for _code, _id in (
    ("COMPRESSOR", "compressor"),
    ("CONDENSER", "condenser"),
    ("RADIATOR", "radiator"),
):
    _ALIAS_TO_ID[_code.casefold()] = _id

# Extra common aliases
_ALIAS_TO_ID.update(
    {
        "空调压缩机".casefold(): "compressor",
        "水箱".casefold(): "radiator",
    }
)


def normalize_category_id(raw: str | None) -> Optional[str]:
    """Return canonical category id (compressor/condenser/radiator) or None."""
    text = str(raw or "").strip()
    if not text:
        return None
    folded = text.casefold()
    if folded in SUPPORTED_CATEGORY_IDS:
        return folded
    hit = _ALIAS_TO_ID.get(folded)
    if hit in SUPPORTED_CATEGORY_IDS:
        return hit
    # Contains match against known aliases
    for alias, cid in _ALIAS_TO_ID.items():
        if alias and (alias in folded or folded in alias) and cid in SUPPORTED_CATEGORY_IDS:
            return cid
    return None


def normalize_category_code(raw: str | None) -> Optional[str]:
    cid = normalize_category_id(raw)
    if not cid:
        return None
    return cid.upper()


def is_supported_category(code_or_name: str | None) -> bool:
    return normalize_category_id(code_or_name) is not None


def category_cn(cid: str | None) -> Optional[str]:
    if not cid:
        return None
    return CATEGORY_CN.get(cid) or CATEGORY_CN.get(str(cid).casefold())


def category_en(cid: str | None) -> Optional[str]:
    if not cid:
        return None
    key = str(cid).casefold()
    return CATEGORY_EN.get(key) or CATEGORY_EN.get(cid)


def ensure_supported_category_value(
    code: str | None = None,
    name: str | None = None,
) -> str:
    """Raise AppError if neither code nor name maps to a supported category. Return id."""
    cid = normalize_category_id(code) or normalize_category_id(name)
    if cid is None:
        raise AppError(
            "暂仅支持压缩机、冷凝器、散热器三类零件",
            code="unsupported_category",
            status_code=400,
            message_key="part.unsupported_category",
        )
    return cid


def supported_category_list_en() -> list[str]:
    return [CATEGORY_EN[i] for i in SUPPORTED_CATEGORY_IDS if i in CATEGORY_EN]


def supported_category_payload() -> list[dict[str, str]]:
    return [
        {
            "id": cid,
            "code": cid.upper(),
            "name_cn": CATEGORY_CN[cid],
            "name_en": CATEGORY_EN.get(cid, cid.title()),
        }
        for cid in SUPPORTED_CATEGORY_IDS
    ]
