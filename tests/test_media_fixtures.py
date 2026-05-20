from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from encoder.media import MediaFile


def ffprobe_streams(path: Path) -> list[dict]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["streams"]


@pytest.mark.fixtures
def test_generated_fixtures_match_expected_streams(
    fixture_media_root, available_generated_entries
):
    for entry in available_generated_entries:
        path = fixture_media_root / entry["path"]
        media = MediaFile(path)
        expect = entry.get("expect", {})

        if "video_streams" in expect:
            assert len(media.video_info) == expect["video_streams"], entry["id"]
        if "audio_streams" in expect:
            assert len(media.audio_info) == expect["audio_streams"], entry["id"]
        if "video_codecs" in expect:
            codecs = {stream.codec for stream in media.video_info}
            assert set(expect["video_codecs"]).issubset(codecs), entry["id"]
        if "audio_codecs" in expect:
            codecs = {stream.codec for stream in media.audio_info}
            assert set(expect["audio_codecs"]).issubset(codecs), entry["id"]


@pytest.mark.fixtures
def test_fixture_media_exercises_metadata_and_multistream_cases(
    fixture_media_root, available_generated_entries
):
    entries = {entry["id"]: entry for entry in available_generated_entries}

    multi_audio = MediaFile(fixture_media_root / entries["multi_audio_mkv"]["path"])
    assert len(multi_audio.audio_info) == 3

    multi_video = MediaFile(fixture_media_root / entries["multi_video_mkv"]["path"])
    assert len(multi_video.video_info) == 2

    attached_pic = MediaFile(fixture_media_root / entries["attached_pic_mp4"]["path"])
    assert any(stream.is_metadata for stream in attached_pic.video_info)


@pytest.mark.fixtures
def test_generated_fixtures_cover_hdr_and_broadcast_formats(
    fixture_media_root, available_generated_entries
):
    entries = {entry["id"]: entry for entry in available_generated_entries}

    hdr10_stream = ffprobe_streams(
        fixture_media_root / entries["hdr10_hevc_mkv"]["path"]
    )[0]
    assert hdr10_stream["codec_name"] == "hevc"
    assert hdr10_stream["pix_fmt"] == "yuv420p10le"
    assert hdr10_stream["color_primaries"] == "bt2020"
    assert hdr10_stream["color_transfer"] == "smpte2084"
    assert hdr10_stream["color_space"] == "bt2020nc"

    hlg_stream = ffprobe_streams(fixture_media_root / entries["hlg_hevc_mov"]["path"])[0]
    assert hlg_stream["codec_name"] == "hevc"
    assert hlg_stream["color_transfer"] == "arib-std-b67"

    prores = MediaFile(fixture_media_root / entries["prores_422_mov"]["path"])
    assert prores.video_info[0].codec == "prores"
    assert prores.video_info[0].pix_fmt == "yuv422p10le"

    dnxhr = MediaFile(fixture_media_root / entries["dnxhr_mxf"]["path"])
    assert dnxhr.video_info[0].codec == "dnxhd"
    assert dnxhr.audio_info[0].codec == "pcm_s16le"

    alpha = MediaFile(fixture_media_root / entries["alpha_qtrle_mov"]["path"])
    assert alpha.video_info[0].codec == "qtrle"
    assert alpha.video_info[0].pix_fmt == "argb"


def test_media_file_rejects_still_images_even_with_video_codec(tmp_path: Path):
    image = tmp_path / "cover.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=128x128:duration=0.1",
            "-frames:v",
            "1",
            str(image),
        ],
        check=True,
    )

    disguised_video = tmp_path / "cover.mp4"
    disguised_video.write_bytes(image.read_bytes())

    with pytest.raises(ValueError):
        MediaFile(image)
    with pytest.raises(ValueError):
        MediaFile(disguised_video)
