from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from batch_realphoto_eval import EvalWorkbook, build_result_row  # noqa: E402
from realphoto_eval_lib import (  # noqa: E402
    category_prefix,
    eligible_groups,
    index_photos,
    parse_filename,
    prefix_counts,
    sample_by_prefix,
    select_upload_images,
)


def _write_photo(directory: Path, material_code: str, angle: str) -> Path:
    path = directory / f"{material_code}-{angle}.jpg"
    path.write_bytes(b"fake-jpeg")
    return path


def test_parse_filename_valid():
    assert parse_filename("1.71.12113-03.jpg") == ("1.71.12113", "03")
    assert parse_filename("1.A4.102300-01.JPEG") == ("1.A4.102300", "01")
    assert parse_filename("1.41.101.456-04.jpg") == ("1.41.101.456", "04")
    assert parse_filename("1.31.30005.PD-02.jpg") == ("1.31.30005.PD", "02")


def test_parse_filename_rejects_junk():
    assert parse_filename(".-05.jpg") is None
    assert parse_filename("1.71.12113.jpg") is None
    assert parse_filename("1.71.12113-3.jpg") is None
    assert parse_filename("readme.txt") is None
    assert parse_filename("1.71.12113-03.png") is None


def test_category_prefix():
    assert category_prefix("1.71.12113") == "1.71."
    assert category_prefix("1.A4.102300") == "1.A4."
    assert category_prefix("1.T4.10031") == "1.T4."
    assert category_prefix("1.41.101.456") == "1.41."
    assert category_prefix("17112113") is None
    assert category_prefix(".71.12113") is None


def test_index_eligible_and_select(tmp_path: Path):
    _write_photo(tmp_path, "1.71.12113", "01")
    _write_photo(tmp_path, "1.71.12113", "02")
    _write_photo(tmp_path, "1.71.12113", "03")
    _write_photo(tmp_path, "1.71.12113", "04")
    _write_photo(tmp_path, "1.71.12113", "05")
    _write_photo(tmp_path, "1.17.10084", "05")
    (tmp_path / ".-05.jpg").write_bytes(b"x")

    groups = index_photos(tmp_path)
    assert "1.71.12113" in groups
    assert "1.17.10084" in groups
    assert groups["1.17.10084"].is_eligible() is False

    eligible = eligible_groups(groups)
    assert [group.material_code for group in eligible] == ["1.71.12113"]

    upload = select_upload_images(groups["1.71.12113"], max_images=8)
    assert upload.overall.angle == "01"
    assert [photo.angle for photo in upload.others] == ["02", "03", "04", "05"]
    assert len(upload.all_photos) == 5
    assert "01" in upload.angles


def test_select_upload_images_minimum_two(tmp_path: Path):
    _write_photo(tmp_path, "1.40.10001", "01")
    _write_photo(tmp_path, "1.40.10001", "04")
    group = index_photos(tmp_path)["1.40.10001"]
    upload = select_upload_images(group, max_images=8)
    assert len(upload.all_photos) == 2
    assert upload.angles == ["01", "04"]


def test_select_upload_images_caps_at_eight(tmp_path: Path):
    for angle in range(1, 12):
        _write_photo(tmp_path, "1.71.12113", f"{angle:02d}")
    group = index_photos(tmp_path)["1.71.12113"]
    upload = select_upload_images(group, max_images=8)
    assert len(upload.all_photos) == 8
    assert upload.overall.angle == "01"


def test_sample_by_prefix_respects_count_and_seed(tmp_path: Path):
    for index in range(12):
        code = f"1.16.{12000 + index}"
        _write_photo(tmp_path, code, "01")
        _write_photo(tmp_path, code, "02")
    for index in range(4):
        code = f"1.40.{10001 + index}"
        _write_photo(tmp_path, code, "01")
        _write_photo(tmp_path, code, "02")
    _write_photo(tmp_path, "1.17.10084", "05")

    groups = eligible_groups(index_photos(tmp_path))
    sampled = sample_by_prefix(groups, per_prefix=10, seed=42)
    again = sample_by_prefix(groups, per_prefix=10, seed=42)
    other_seed = sample_by_prefix(groups, per_prefix=10, seed=7)

    counts = prefix_counts(sampled)
    assert counts == {"1.16.": 10, "1.40.": 4}
    assert [group.material_code for group in sampled] == [group.material_code for group in again]
    assert [group.material_code for group in sampled] != [group.material_code for group in other_seed]
    assert all(group.is_eligible() for group in sampled)


def test_eval_workbook_append_and_resume(tmp_path: Path):
    photos = tmp_path / "photos"
    photos.mkdir()
    _write_photo(photos, "1.71.12113", "01")
    _write_photo(photos, "1.71.12113", "02")
    group = index_photos(photos)["1.71.12113"]
    upload = select_upload_images(group)

    output = tmp_path / "eval.xlsx"
    workbook = EvalWorkbook(output)
    workbook.write_run_info([("seed", 42), ("API", "http://127.0.0.1:8000")])
    workbook.write_sample_list([group], {group.material_code: upload}, set())
    row = build_result_row(
        group=group,
        upload=upload,
        session={
            "public_id": "abc123",
            "status": "done",
            "result": {
                "is_auto_part": True,
                "part_name": "散热器",
                "mapped_category_name": "散热器",
                "mapped_category_code": "RADIATOR",
                "confidence": 0.92,
                "reason": "铝制散热芯",
                "candidates": [{"name": "散热器", "confidence": 0.92}],
            },
        },
        elapsed_s=3.2,
    )
    workbook.append_result(row, overall_path=upload.overall.path)
    workbook.save()

    resumed = EvalWorkbook(output)
    assert resumed.successful_material_codes() == {"1.71.12113"}
    assert resumed.completed_material_codes() == {"1.71.12113"}
    result_sheet = resumed.wb["识别结果"]
    values = [cell.value for cell in result_sheet[2]]
    assert "1.71.12113" in values
    assert "散热器" in values
    assert 0.92 in values
    path_cell = result_sheet.cell(2, 6)
    assert path_cell.hyperlink is not None
    sample_sheet = resumed.wb["抽样清单"]
    assert sample_sheet.cell(2, 2).value == "1.71.12113"
    info_sheet = resumed.wb["运行信息"]
    assert info_sheet.cell(2, 1).value == "seed"
    candidates = json.loads(result_sheet.cell(2, 15).value)
    assert candidates[0]["name"] == "散热器"


def test_resume_retries_error_rows_and_upserts(tmp_path: Path):
    photos = tmp_path / "photos"
    photos.mkdir()
    _write_photo(photos, "1.18.12461", "01")
    _write_photo(photos, "1.18.12461", "02")
    group = index_photos(photos)["1.18.12461"]
    upload = select_upload_images(group)

    output = tmp_path / "eval.xlsx"
    workbook = EvalWorkbook(output)
    error_row = build_result_row(group=group, upload=upload, error="请求过于频繁", elapsed_s=150)
    workbook.append_result(error_row, overall_path=upload.overall.path)
    workbook.save()

    resumed = EvalWorkbook(output)
    assert resumed.successful_material_codes() == set()

    success = build_result_row(
        group=group,
        upload=upload,
        session={
            "public_id": "retry-1",
            "status": "done",
            "result": {"is_auto_part": True, "part_name": "暖风水箱", "confidence": 0.95},
        },
        elapsed_s=8.0,
    )
    resumed.upsert_result(success, overall_path=upload.overall.path)
    resumed.save()

    again = EvalWorkbook(output)
    assert again.successful_material_codes() == {"1.18.12461"}
    sheet = again.wb["识别结果"]
    assert sheet.max_row == 2
    assert sheet.cell(2, 7).value == "retry-1"
    assert sheet.cell(2, 10).value == "暖风水箱"

