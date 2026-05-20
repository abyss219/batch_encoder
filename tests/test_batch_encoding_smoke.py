from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_report_from_stdout(stdout: str) -> dict:
    match = re.search(r"Report: (logs/batch_encoder_[^\s]+_summary\.json)", stdout)
    assert match, stdout
    report_path = REPO_ROOT / match.group(1)
    with report_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def generated_source(
    fixture_media_root: Path, available_generated_entries, fixture_id: str
) -> Path:
    source_entry = next(
        entry for entry in available_generated_entries if entry["id"] == fixture_id
    )
    return fixture_media_root / source_entry["path"]


@pytest.mark.fixtures
@pytest.mark.slow
def test_batch_encoder_smoke_encodes_single_fixture(
    tmp_path: Path, fixture_media_root: Path, available_generated_entries
):
    source = generated_source(fixture_media_root, available_generated_entries, "h264_aac_mp4")
    work_file = tmp_path / source.name
    shutil.copy2(source, work_file)

    result = subprocess.run(
        [
            sys.executable,
            "batch_encoding.py",
            str(work_file),
            "--min-size",
            "1B",
            "--codec",
            "hevc",
            "--skip-codecs",
            "none",
            "--no-check-size",
            "--no-delete-origin",
            "--no-verify",
            "--force-reset",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "SUCCESS: 1" in result.stdout

    report = read_report_from_stdout(result.stdout)
    assert report["counts"]["SUCCESS"] == 1


@pytest.mark.fixtures
@pytest.mark.slow
def test_batch_encoder_directory_input_reports_success_skip_and_invalid(
    tmp_path: Path, fixture_media_root: Path, available_generated_entries
):
    h264 = generated_source(fixture_media_root, available_generated_entries, "h264_aac_mp4")
    hevc = generated_source(fixture_media_root, available_generated_entries, "hevc_aac_mp4")
    shutil.copy2(h264, tmp_path / "encode_me.mp4")
    shutil.copy2(hevc, tmp_path / "already_hevc.mp4")
    (tmp_path / "not_a_video.mp4").write_text("not media", encoding="utf-8")
    (tmp_path / "cover.jpg").write_text("not discovered", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "batch_encoding.py",
            str(tmp_path),
            "--min-size",
            "1B",
            "--codec",
            "hevc",
            "--skip-codecs",
            "efficient",
            "--no-check-size",
            "--no-delete-origin",
            "--no-verify",
            "--force-reset",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    report = read_report_from_stdout(result.stdout)
    assert report["input"]["kind"] == "directory"
    assert report["input"]["discovered_paths"] == 3
    assert report["counts"]["SUCCESS"] == 1
    assert report["counts"]["SKIPPED"] == 2
    skipped_reasons = " ".join(entry["reason"] for entry in report["results"]["SKIPPED"])
    assert "Already in a codec configured by --skip-codecs" in skipped_reasons
    assert "Not a valid video file" in skipped_reasons


@pytest.mark.fixtures
@pytest.mark.slow
def test_batch_encoder_list_input_handles_duplicates_missing_and_relative_paths(
    tmp_path: Path, fixture_media_root: Path, available_generated_entries
):
    h264 = generated_source(fixture_media_root, available_generated_entries, "h264_aac_mp4")
    work_file = tmp_path / "relative_source.mp4"
    shutil.copy2(h264, work_file)
    list_file = tmp_path / "videos.txt"
    list_file.write_text(
        "\n".join(
            [
                "# relative path",
                work_file.name,
                work_file.name,
                "missing.mp4",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "batch_encoding.py",
            str(list_file),
            "--min-size",
            "1B",
            "--codec",
            "hevc",
            "--skip-codecs",
            "none",
            "--no-check-size",
            "--no-delete-origin",
            "--no-verify",
            "--force-reset",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    report = read_report_from_stdout(result.stdout)
    assert report["input"]["kind"] == "list"
    assert report["input"]["discovered_paths"] == 2
    assert report["counts"]["SUCCESS"] == 1
    assert report["counts"]["SKIPPED"] == 1
    assert report["results"]["SKIPPED"][0]["reason"] == (
        "Input path does not exist or is not a file."
    )
