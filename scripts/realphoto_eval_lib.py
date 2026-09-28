"""Parse real-part photos, group by material, sample per prefix, and pick upload sets."""

from __future__ import annotations

import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

FILENAME_RE = re.compile(r"^(.+)-(\d{2})\.(jpe?g)$", re.IGNORECASE)
OVERALL_ANGLE = "01"
DEFAULT_MAX_IMAGES = 8
DEFAULT_PER_PREFIX = 10
DEFAULT_SEED = 42


@dataclass(frozen=True)
class PhotoFile:
    path: Path
    material_code: str
    prefix: str
    angle: str

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass
class MaterialGroup:
    material_code: str
    prefix: str
    photos: Dict[str, PhotoFile] = field(default_factory=dict)

    def has_overall(self) -> bool:
        return OVERALL_ANGLE in self.photos

    def other_angles(self) -> List[str]:
        return sorted(angle for angle in self.photos if angle != OVERALL_ANGLE)

    def is_eligible(self) -> bool:
        return self.has_overall() and bool(self.other_angles())

    def available_angles(self) -> List[str]:
        angles = []
        if self.has_overall():
            angles.append(OVERALL_ANGLE)
        angles.extend(self.other_angles())
        return angles


@dataclass(frozen=True)
class UploadSet:
    overall: PhotoFile
    others: tuple[PhotoFile, ...]

    @property
    def all_photos(self) -> List[PhotoFile]:
        return [self.overall, *self.others]

    @property
    def angles(self) -> List[str]:
        return [photo.angle for photo in self.all_photos]

    @property
    def filenames(self) -> List[str]:
        return [photo.filename for photo in self.all_photos]


def parse_filename(name: str) -> Optional[tuple[str, str]]:
    """Return (material_code, angle) or None if the filename is not a part photo."""
    match = FILENAME_RE.match(name.strip())
    if not match:
        return None
    material_code = match.group(1).strip()
    angle = match.group(2)
    if not material_code or material_code.startswith("."):
        return None
    return material_code, angle


def category_prefix(material_code: str) -> Optional[str]:
    """Prefix is the first two dotted segments plus a trailing dot, e.g. 1.71.12113 -> 1.71."""
    parts = [part for part in material_code.split(".")]
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return None
    return f"{parts[0]}.{parts[1]}."


def parse_photo(path: Path) -> Optional[PhotoFile]:
    parsed = parse_filename(path.name)
    if parsed is None:
        return None
    material_code, angle = parsed
    prefix = category_prefix(material_code)
    if prefix is None:
        return None
    return PhotoFile(path=path, material_code=material_code, prefix=prefix, angle=angle)


def index_photos(images_dir: Path) -> Dict[str, MaterialGroup]:
    if not images_dir.is_dir():
        raise FileNotFoundError(f"图片目录不存在: {images_dir}")
    groups: Dict[str, MaterialGroup] = {}
    for path in images_dir.iterdir():
        if not path.is_file():
            continue
        photo = parse_photo(path)
        if photo is None:
            continue
        group = groups.get(photo.material_code)
        if group is None:
            group = MaterialGroup(material_code=photo.material_code, prefix=photo.prefix)
            groups[photo.material_code] = group
        group.photos[photo.angle] = photo
    return groups


def eligible_groups(groups: Mapping[str, MaterialGroup]) -> List[MaterialGroup]:
    return sorted(
        (group for group in groups.values() if group.is_eligible()),
        key=lambda group: (group.prefix, group.material_code),
    )


def sample_by_prefix(
    groups: Sequence[MaterialGroup],
    *,
    per_prefix: int = DEFAULT_PER_PREFIX,
    seed: int = DEFAULT_SEED,
) -> List[MaterialGroup]:
    if per_prefix < 1:
        raise ValueError("per_prefix 必须 >= 1")
    rng = random.Random(seed)
    by_prefix: Dict[str, List[MaterialGroup]] = defaultdict(list)
    for group in groups:
        if not group.is_eligible():
            continue
        by_prefix[group.prefix].append(group)

    sampled: List[MaterialGroup] = []
    for prefix in sorted(by_prefix):
        items = sorted(by_prefix[prefix], key=lambda group: group.material_code)
        count = min(per_prefix, len(items))
        picked = rng.sample(items, count)
        picked.sort(key=lambda group: group.material_code)
        sampled.extend(picked)
    return sampled


def select_upload_images(group: MaterialGroup, max_images: int = DEFAULT_MAX_IMAGES) -> UploadSet:
    if max_images < 2:
        raise ValueError("max_images 必须 >= 2")
    if not group.is_eligible():
        raise ValueError(f"物料 {group.material_code} 不满足整体外观+其他角度的入组条件")
    overall = group.photos[OVERALL_ANGLE]
    others = tuple(group.photos[angle] for angle in group.other_angles()[: max_images - 1])
    return UploadSet(overall=overall, others=others)


def prefix_counts(groups: Iterable[MaterialGroup]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for group in groups:
        counts[group.prefix] += 1
    return dict(sorted(counts.items()))
