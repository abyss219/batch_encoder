from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import batch_encoding
from config import EncodingStatus
from encoder.batch import discover_batch_input


class FakeMediaFile:
    def __init__(self, file_path: str | Path, *_, **__):
        self.file_path = Path(file_path)
        if "invalid" in self.file_path.name:
            raise ValueError("not a video")

        codec = "hevc" if "hevc" in self.file_path.name else "h264"
        width, height = (96, 54) if "lowres" in self.file_path.name else (640, 360)
        self.video_info = [
            SimpleNamespace(
                codec=codec,
                width=width,
                height=height,
                is_metadata=False,
            )
        ]
        self.audio_info = []


class FakeEncodingClass:
    def __init__(self, media_file: FakeMediaFile, skip_codecs=None, **_):
        self.media_file = media_file
        self.skip_codecs = set(skip_codecs or [])
        self.output_tmp_file = media_file.file_path.with_name(
            f"{media_file.file_path.stem}_tmp.mp4"
        )
        self.new_file_path = media_file.file_path.with_name(
            f"{media_file.file_path.stem}_encoded.mp4"
        )

    def encode_wrapper(self) -> EncodingStatus:
        stem = self.media_file.file_path.stem
        codec = self.media_file.video_info[0].codec
        if codec in self.skip_codecs:
            return EncodingStatus.SKIPPED
        if stem == "failed":
            return EncodingStatus.FAILED
        if stem == "lowquality":
            self.output_tmp_file.write_bytes(b"low quality output")
            return EncodingStatus.LOWQUALITY
        if stem == "largesize":
            self.output_tmp_file.write_bytes(b"large output")
            return EncodingStatus.LARGESIZE

        self.new_file_path.write_bytes(b"encoded")
        return EncodingStatus.SUCCESS

    def _delete_encoded(self) -> bool:
        if self.output_tmp_file and self.output_tmp_file.exists():
            self.output_tmp_file.unlink()
        return True

    @staticmethod
    def human_readable_size(size_in_bytes: int) -> str:
        return f"{size_in_bytes} B"


def write_video_like(path: Path, size: int = 64) -> Path:
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture
def fake_media(monkeypatch):
    monkeypatch.setattr(batch_encoding, "MediaFile", FakeMediaFile)


def make_encoder(tmp_path: Path, **kwargs) -> batch_encoding.BatchEncoder:
    batch_input = discover_batch_input(tmp_path)
    return batch_encoding.BatchEncoder(
        batch_input=batch_input,
        encoding_class=FakeEncodingClass,
        codec="hevc",
        min_size=kwargs.pop("min_size", "1B"),
        verify=False,
        check_size=False,
        delete_origin=False,
        force_reset=True,
        min_resolution=kwargs.pop("min_resolution", None),
        skip_codecs=kwargs.pop("skip_codecs", set()),
        **kwargs,
    )


def test_directory_discovery_ignores_images_and_includes_raw_streams(tmp_path: Path):
    mp4 = write_video_like(tmp_path / "Video.MP4")
    raw_hevc = write_video_like(tmp_path / "raw.HEVC")
    (tmp_path / "cover.jpg").write_bytes(b"fake image")
    (tmp_path / "notes.txt").write_text("not media", encoding="utf-8")

    batch_input = discover_batch_input(tmp_path)

    assert batch_input.kind == "directory"
    assert batch_input.video_paths == tuple(sorted([mp4.resolve(), raw_hevc.resolve()]))


def test_batch_encoder_records_all_terminal_statuses(tmp_path: Path, fake_media):
    for name in ("success.mp4", "hevc_skip.mp4", "failed.mp4", "lowquality.mp4", "largesize.mp4"):
        write_video_like(tmp_path / name, size=128)

    encoder = make_encoder(tmp_path, skip_codecs={"hevc"})
    encoder.encode_videos()

    assert encoder.result_counts() == {
        "SUCCESS": 1,
        "SKIPPED": 1,
        "FAILED": 1,
        "LOWQUALITY": 1,
        "LARGESIZE": 1,
    }

    with encoder.report_file.open("r", encoding="utf-8") as f:
        report = json.load(f)

    assert report["counts"]["SUCCESS"] == 1
    assert report["counts"]["SKIPPED"] == 1
    assert report["counts"]["FAILED"] == 1
    assert report["counts"]["LOWQUALITY"] == 1
    assert report["counts"]["LARGESIZE"] == 1
    assert report["results"]["LOWQUALITY"][0]["output_path"].endswith("_tmp.mp4")
    assert report["results"]["LARGESIZE"][0]["output_path"].endswith("_tmp.mp4")


def test_batch_encoder_skips_invalid_small_and_low_resolution_inputs(
    tmp_path: Path, fake_media
):
    write_video_like(tmp_path / "tiny.mp4", size=2)
    write_video_like(tmp_path / "invalid.mp4", size=128)
    write_video_like(tmp_path / "lowres.mp4", size=128)

    encoder = make_encoder(tmp_path, min_size="10B", min_resolution="360p")

    assert encoder.video_queue == []
    skipped = list(encoder.results["SKIPPED"].values())
    reasons = " ".join(entry["reason"] for entry in skipped)
    assert len(skipped) == 3
    assert "Below minimum size threshold" in reasons
    assert "Not a valid video file" in reasons
    assert "below threshold of 360p" in reasons
