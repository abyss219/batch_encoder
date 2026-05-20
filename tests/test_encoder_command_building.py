from __future__ import annotations

import pytest

from encoder.encoders.custom_encoder import get_custom_encoding_class
from encoder.encoders.hevc_encoder import HevcEncoder
from encoder.media import MediaFile


@pytest.mark.fixtures
def test_hevc_command_copies_attached_picture_metadata_stream(
    fixture_media_root, available_generated_entries
):
    entry = next(
        entry for entry in available_generated_entries if entry["id"] == "attached_pic_mp4"
    )
    media = MediaFile(fixture_media_root / entry["path"])
    encoder = HevcEncoder(media, skip_codecs=set(), check_size=False, verify=False)

    video_args = encoder.prepare_video_args()
    metadata_args = [
        args
        for stream, args in video_args.items()
        if stream.is_metadata
    ]

    assert metadata_args
    assert all("copy" in args for args in metadata_args)
    assert all(
        not any(arg.startswith("-filter:v") for arg in stream_args)
        for stream_args in metadata_args
    )


@pytest.mark.fixtures
def test_custom_denoise_only_applies_to_encoded_video_streams(
    fixture_media_root, available_generated_entries
):
    entry = next(
        entry for entry in available_generated_entries if entry["id"] == "attached_pic_mp4"
    )
    media = MediaFile(fixture_media_root / entry["path"])
    encoder_cls = get_custom_encoding_class("hevc")
    encoder = encoder_cls(
        media,
        denoise="light",
        skip_codecs=set(),
        check_size=False,
        verify=False,
    )

    video_args = encoder.prepare_video_args()

    encoded_args = [
        args
        for stream, args in video_args.items()
        if not stream.is_metadata
    ]
    metadata_args = [
        args
        for stream, args in video_args.items()
        if stream.is_metadata
    ]
    assert any(any(arg.startswith("-filter:v") for arg in args) for args in encoded_args)
    assert all(not any(arg.startswith("-filter:v") for arg in args) for args in metadata_args)


@pytest.mark.fixtures
def test_audio_args_copy_compatible_codecs_and_transcode_others(
    fixture_media_root, available_generated_entries
):
    entry = next(
        entry for entry in available_generated_entries if entry["id"] == "multi_audio_mkv"
    )
    media = MediaFile(fixture_media_root / entry["path"])
    encoder = HevcEncoder(media, skip_codecs=set(), check_size=False, verify=False)

    audio_args = {
        stream.codec: args
        for stream, args in encoder.prepare_audio_args().items()
    }

    assert "copy" in audio_args["aac"]
    assert "copy" in audio_args["ac3"]
    assert "aac" in audio_args["opus"]
