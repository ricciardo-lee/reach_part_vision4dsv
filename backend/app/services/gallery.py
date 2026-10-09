"""Read-only access to local 360 product photos.

Photo360 is laid out as ``{root}/{category}/{sku}/{image}``. The gallery SKU
is the product folder name. This module never writes those files.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import ROOT_DIR, settings

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_cache_key: str | None = None
_exact: dict[str, Path] = {}
_folded: dict[str, Path] = {}


def reset_gallery_cache() -> None:
    global _cache_key, _exact, _folded
    _cache_key = None
    _exact = {}
    _folded = {}


def gallery_root() -> Path | None:
    raw = str(settings.PHOTO360_ROOT or "").strip()
    if raw:
        return _resolve_dir(Path(raw))
    return _discover_photo360_root()


def list_views(sku: str) -> list[str]:
    folder = _find_folder(sku)
    if folder is None:
        return []
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in _IMAGE_SUFFIXES
    ]
    files.sort(key=lambda path: path.name.lower())
    return [path.name for path in files]


def resolve_image(sku: str, name: str) -> Path | None:
    if not _safe_name(name):
        return None
    folder = _find_folder(sku)
    if folder is None:
        return None
    try:
        path = (folder / name).resolve()
        root = folder.resolve()
    except OSError:
        return None
    if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _safe_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text or text.startswith(".") or text != Path(text).name:
        return False
    return Path(text).suffix.lower() in _IMAGE_SUFFIXES


def _find_folder(sku: str) -> Path | None:
    text = str(sku or "").strip()
    if not text or text != Path(text).name or text in {".", ".."}:
        return None
    root = gallery_root()
    if root is None or not root.is_dir():
        return None
    _ensure_index(root)
    return _exact.get(text) or _folded.get(text.casefold())


def _resolve_dir(raw: Path) -> Path:
    if raw.is_absolute():
        return raw
    candidates = [ROOT_DIR.parent / raw, ROOT_DIR / raw, Path.cwd() / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _index_dir() -> Path:
    return _resolve_dir(Path(settings.SEARCH_INDEX_DIR))


def _discover_photo360_root() -> Path | None:
    index_dir = _index_dir()
    meta_paths = [index_dir / "latest_meta.json"]
    if index_dir.is_dir():
        meta_paths.extend(sorted(index_dir.glob("*/index_meta.json")))
    for meta_path in meta_paths:
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw = str(meta.get("photo360_root") or "").strip()
        if raw and Path(raw).is_dir():
            return Path(raw)
    return None


def _ensure_index(root: Path) -> None:
    global _cache_key, _exact, _folded
    key = str(root.resolve())
    if _cache_key == key:
        return
    exact: dict[str, Path] = {}
    folded: dict[str, Path] = {}
    try:
        categories = sorted(
            (path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")),
            key=lambda path: path.name.lower(),
        )
    except OSError:
        categories = []
    for category in categories:
        try:
            products = sorted(
                (path for path in category.iterdir() if path.is_dir() and not path.name.startswith(".")),
                key=lambda path: path.name.lower(),
            )
        except OSError:
            continue
        for product in products:
            exact.setdefault(product.name, product)
            folded.setdefault(product.name.casefold(), product)
    _exact = exact
    _folded = folded
    _cache_key = key
