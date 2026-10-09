from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.exceptions import AppError
from app.integrations.deepseek.client import format_vision_result, parse_json_object
from app.services.eval_metrics import score_session
from app.utils.images import compress_to_jpeg_bytes, compute_phash, validate_image_meta


def _make_png_bytes(color=(20, 120, 200)) -> bytes:
    image = Image.new("RGB", (320, 240), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_validate_image_rejects_bad_extension():
    with pytest.raises(AppError):
        validate_image_meta("a.gif", "image/gif", 100, 10 * 1024 * 1024)


def test_compress_and_phash():
    raw = _make_png_bytes()
    jpeg, w, h = compress_to_jpeg_bytes(raw, max_side=128)
    assert jpeg[:2] == b"\xff\xd8"
    assert w <= 128 and h <= 128
    assert len(compute_phash(jpeg)) == 40


def test_vision_candidates_enrichment_shape():
    payload = parse_json_object(
        '{"part_name":"冷凝器","confidence":0.77,"reason":"扁管","candidates":[{"name":"冷凝器","confidence":0.77},{"name":"散热器","confidence":0.4}]}'
    )
    result = format_vision_result(payload)
    assert result.part_name == "冷凝器"
    assert len(result.candidates) == 2


def test_eval_score_top1_top3_reject():
    scored = score_session(
        confirmed_code="RAD",
        confirmed_name="散热器",
        mapped_code="RAD",
        mapped_name="散热器",
        candidates=[
            {"name": "散热器", "category_code": "RAD", "confidence": 0.9},
            {"name": "冷凝器", "category_code": "COND", "confidence": 0.2},
        ],
        confidence=0.9,
        reject_confidence=0.45,
    )
    assert scored["top1_hit"] is True
    assert scored["top3_hit"] is True
    assert scored["is_reject"] is False

    scored2 = score_session(
        confirmed_code="RAD",
        confirmed_name="散热器",
        mapped_code="COND",
        mapped_name="冷凝器",
        candidates=[
            {"name": "冷凝器", "category_code": "COND", "confidence": 0.5},
            {"name": "水泵", "category_code": "WP", "confidence": 0.3},
            {"name": "散热器", "category_code": "RAD", "confidence": 0.2},
        ],
        confidence=0.3,
        reject_confidence=0.45,
    )
    assert scored2["top1_hit"] is False
    assert scored2["top3_hit"] is True
    assert scored2["is_reject"] is True
