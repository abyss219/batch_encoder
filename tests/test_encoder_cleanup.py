from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from config import EncodingStatus
from encoder.encoders.hevc_encoder import HevcEncoder
from encoder.media import MediaFile


def copy_fixture(
    tmp_path: Path, fixture_media_root: Path, available_generated_entries, fixture_id: str
) -> Path:
    entry = next(entry for entry in available_generated_entries if entry["id"] == fixture_id)
    source = fixture_media_root / entry["path"]
    target = tmp_path / source.name
    shutil.copy2(source, target)
    return target


@pytest.mark.fixtures
def test_cleanup_reports_large_size_when_encoded_output_is_not_smaller(
    tmp_path: Path, fixture_media_root: Path, available_generated_entries
):
    source = copy_fixture(tmp_path, fixture_media_root, available_generated_entries, "h264_aac_mp4")
    media = MediaFile(source)
    encoder = HevcEncoder(
        media,
        check_size=True,
        verify=False,
        delete_original=False,
    )
    encoder.output_tmp_file.write_bytes(b"x" * (source.stat().st_size + 1))

    status = encoder.clean_up(EncodingStatus.SUCCESS)

    assert status == EncodingStatus.LARGESIZE
    assert source.exists()
    assert encoder.output_tmp_file.exists()


@pytest.mark.fixtures
def test_cleanup_reports_low_quality_when_vmaf_threshold_fails(
    tmp_path: Path, fixture_media_root: Path, available_generated_entries, monkeypatch
):
    source = copy_fixture(tmp_path, fixture_media_root, available_generated_entries, "h264_aac_mp4")
    media = MediaFile(source)
    encoder = HevcEncoder(
        media,
        check_size=False,
        verify=True,
        delete_original=False,
    )
    encoder.output_tmp_file.write_bytes(b"encoded")
    monkeypatch.setattr(encoder, "_verify", lambda: EncodingStatus.LOWQUALITY)

    status = encoder.clean_up(EncodingStatus.SUCCESS)

    assert status == EncodingStatus.LOWQUALITY
    assert source.exists()
    assert encoder.output_tmp_file.exists()
