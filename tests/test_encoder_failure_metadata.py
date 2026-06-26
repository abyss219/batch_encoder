from __future__ import annotations

import tempfile
from pathlib import Path

from encoder.encoders.encoder import CRFEncoder


def make_bare_encoder() -> CRFEncoder:
    """A CRFEncoder with just the failure-metadata state, no ffmpeg/MediaFile."""
    enc = object.__new__(CRFEncoder)
    enc.last_failure = {}
    enc.last_warnings = []
    enc.last_ffmpeg_stderr_tail = None
    enc.last_ffmpeg_stdout_tail = None
    enc.last_return_code = None
    enc.last_cleanup_error = None
    enc.last_ffmpeg_command = None
    enc.output_tmp_file = None
    return enc


def test_set_failure_records_type_and_drops_none():
    enc = make_bare_encoder()
    enc.set_failure(
        "ffmpeg_failed",
        "ffmpeg returned a non-zero exit code.",
        return_code=8,
        stderr_tail="boom",
        stdout_tail=None,
    )

    assert enc.last_failure["failure_type"] == "ffmpeg_failed"
    assert enc.last_failure["reason"].startswith("ffmpeg returned")
    assert enc.last_failure["return_code"] == 8
    assert "stdout_tail" not in enc.last_failure


def test_add_warning_accumulates():
    enc = make_bare_encoder()
    enc.add_warning("progress_ui_error", "tqdm failed", exception_type="TypeError")
    enc.add_warning("progress_ui_error", "tqdm failed again")

    assert len(enc.last_warnings) == 2
    assert enc.last_warnings[0]["warning_type"] == "progress_ui_error"
    assert enc.last_warnings[0]["exception_type"] == "TypeError"


def test_failure_metadata_merges_all_sources():
    enc = make_bare_encoder()
    enc.last_ffmpeg_stderr_tail = "stderr text"
    enc.last_return_code = 4294967283
    enc.last_ffmpeg_command = ["ffmpeg", "-y", "-i", "in.mkv", "out.mp4"]
    enc.set_failure("ffmpeg_failed", "ffmpeg returned a non-zero exit code.")
    enc.add_warning("progress_ui_error", "tqdm failed")

    md = enc.failure_metadata()

    assert md["failure_type"] == "ffmpeg_failed"
    assert md["return_code"] == 4294967283
    assert md["stderr_tail"] == "stderr text"
    assert md["ffmpeg_command"][0] == "ffmpeg"
    assert md["warnings"][0]["warning_type"] == "progress_ui_error"
    assert md["reason"]  # popped by BatchEncoder, present here


def test_failure_metadata_empty_when_nothing_set():
    md = make_bare_encoder().failure_metadata()
    assert md == {}


def test_failure_metadata_does_not_override_explicit_values():
    enc = make_bare_encoder()
    enc.last_return_code = 1
    enc.set_failure("ffmpeg_failed", "reason", return_code=99)

    assert enc.failure_metadata()["return_code"] == 99


def test_temp_output_info_for_existing_file(tmp_path: Path):
    enc = make_bare_encoder()
    tmp = tmp_path / "clip_HevcEncoder_crf-20.mp4"
    tmp.write_bytes(b"x" * 123)
    enc.output_tmp_file = tmp

    info = enc._temp_output_info()

    assert info["temp_output_path"] == str(tmp)
    assert info["temp_output_exists"] is True
    assert info["temp_output_size"] == 123


def test_temp_output_info_missing_file(tmp_path: Path):
    enc = make_bare_encoder()
    enc.output_tmp_file = tmp_path / "gone.mp4"

    info = enc._temp_output_info()

    assert info["temp_output_exists"] is False
    assert info["temp_output_size"] is None


def test_temp_output_info_none():
    assert make_bare_encoder()._temp_output_info() == {}


def test_read_stream_tail_bounds_to_limit():
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as f:
        f.write("x" * 20000 + "TAILEND")
        tail = CRFEncoder._read_stream_tail(f)

    assert tail.endswith("TAILEND")
    assert len(tail) == CRFEncoder.STDERR_TAIL_LIMIT


def test_read_stream_tail_empty():
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as f:
        assert CRFEncoder._read_stream_tail(f) is None
