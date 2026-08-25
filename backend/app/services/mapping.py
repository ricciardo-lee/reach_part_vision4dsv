from __future__ import annotations

from typing import Optional, Tuple

from app.models import CategoryMapping


async def map_category(alias_name: str) -> Tuple[Optional[str], Optional[str]]:
    if not alias_name:
        return None, None
    mapping = (
        await CategoryMapping.filter(alias_name=alias_name, is_active=True)
        .order_by("-priority")
        .first()
    )
    if mapping:
        return mapping.category_code, mapping.category_name

    # fuzzy contains match
    candidates = await CategoryMapping.filter(is_active=True).all()
    for item in sorted(candidates, key=lambda x: -x.priority):
        if item.alias_name in alias_name or alias_name in item.alias_name:
            return item.category_code, item.category_name
    return None, alias_name
