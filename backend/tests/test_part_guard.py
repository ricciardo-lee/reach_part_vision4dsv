from __future__ import annotations

from app.integrations.deepseek.client import format_vision_result
from app.services.part_guard import parse_is_auto_part


def test_parse_is_auto_part_from_payload():
    assert parse_is_auto_part({"is_auto_part": False}, part_name="手机", confidence=0.9) is False
    assert parse_is_auto_part({"is_auto_part": True}, part_name="散热器", confidence=0.9) is True


def test_parse_is_auto_part_heuristic():
    assert parse_is_auto_part({}, part_name="非汽配", confidence=0.9) is False
    assert parse_is_auto_part({}, part_name="手机", confidence=0.9) is False
    assert parse_is_auto_part({}, part_name="未知零件", confidence=0.2) is False
    assert parse_is_auto_part({}, part_name="散热器", confidence=0.9) is True


def test_format_vision_result_non_auto_part():
    payload = {
        "is_auto_part": False,
        "part_name": "手机",
        "confidence": 0.91,
        "reason": "主体为手机",
        "candidates": [{"name": "手机", "confidence": 0.91}],
    }
    result = format_vision_result(payload)
    assert result.is_auto_part is False
    assert result.part_name == "手机"
    assert result.candidates == []
