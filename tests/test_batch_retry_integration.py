from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import batch_encoding
from config import EncodingStatus
from encoder.batch import BatchInput


class FakeMediaFile:
    def __init__(self, file_path, *_, **__):
        self.file_path = Path(file_path)
        self.video_info = [
            SimpleNamespace(codec="h264", width=640, height=360, is_metadata=False)
        ]
        self.audio_info = []


class ConfigurableEncoder:
    """Encoding class whose result/metadata is driven by the filename stem."""

    def __init__(self, media_file, **_):
        self.media_file = media_file
        self.output_tmp_file = media_file.file_path.with_name(
            f"{media_file.file_path.stem}_tmp.mp4"
        )
        self.new_file_path = media_file.file_path.with_name(
            f"{media_file.file_path.stem}_out.mp4"
        )
        self.last_warnings = []

    def encode_wrapper(self) -> EncodingStatus:
        stem = self.media_file.file_path.stem
        if stem == "ffmpeg_fail":
            return EncodingStatus.FAILED
        if stem == "bare_fail":
            return EncodingStatus.FAILED
        if stem == "warned_success":
            self.last_warnings = [
                {"warning_type": "progress_ui_error", "message": "tqdm failed"}
            ]
        self.new_file_path.write_bytes(b"encoded")
        return EncodingStatus.SUCCESS

    def failure_metadata(self) -> dict:
        stem = self.media_file.file_path.stem
        if stem == "ffmpeg_fail":
            return {
                "reason": "ffmpeg returned a non-zero exit code.",
                "failure_type": "ffmpeg_failed",
                "return_code": 1,
                "stderr_tail": "boom",
            }
        return {}  # bare_fail: nothing useful -> fallback path

    @staticmethod
    def human_readable_size(size_in_bytes: int) -> str:
        return f"{size_in_bytes} B"


@pytest.fixture
def fake_media(monkeypatch):
    monkeypatch.setattr(batch_encoding, "MediaFile", FakeMediaFile)


def make_retry_encoder(tmp_path: Path, video_paths, **kwargs):
    report_path = tmp_path / "batch_encoder_src_summary.json"
    report_path.write_text("{}", encoding="utf-8")
    batch_input = BatchInput(
        source_path=report_path.resolve(strict=False),
        kind="retry",
        video_paths=tuple(video_paths),
        label="retry-src",
        target_hash="abc12345",
    )
    retry_context = {
        "source_report": str(report_path),
        "source_run_id": "20260101-000000_src_hash_nonce",
        "source_input": "/data/src",
        "selected_status": "FAILED",
        "selected_failed_count": len(video_paths),
        "_failed_entries": kwargs.pop("failed_entries", {}),
    }
    return batch_encoding.BatchEncoder(
        batch_input=batch_input,
        encoding_class=ConfigurableEncoder,
        codec="hevc",
        min_size="1B",
        verify=False,
        check_size=False,
        delete_origin=False,
        force_reset=True,
        skip_codecs=set(),
        retry_context=retry_context,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Retry-mode queue behavior
# --------------------------------------------------------------------------- #
def test_retry_mode_missing_path_recorded_failed_not_skipped(tmp_path: Path):
    missing = tmp_path / "gone.mkv"
    encoder = make_retry_encoder(tmp_path, [missing])

    assert encoder.result_counts()["FAILED"] == 1
    assert encoder.result_counts()["SKIPPED"] == 0
    entry = list(encoder.results["FAILED"].values())[0]
    assert entry["failure_type"] == "path_unavailable"
    assert entry["path_exists_at_failure"] is False


def test_normal_mode_missing_path_is_skipped(tmp_path: Path, fake_media):
    # A plain directory batch with a list pointing at a missing file -> SKIPPED.
    missing = tmp_path / "gone.mkv"
    list_file = tmp_path / "videos.txt"
    list_file.write_text(str(missing) + "\n", encoding="utf-8")
    from encoder.batch import discover_batch_input

    encoder = batch_encoding.BatchEncoder(
        batch_input=discover_batch_input(list_file),
        encoding_class=ConfigurableEncoder,
        codec="hevc",
        min_size="1B",
        verify=False,
        check_size=False,
        delete_origin=False,
        force_reset=True,
        skip_codecs=set(),
    )

    assert encoder.result_counts()["SKIPPED"] == 1
    assert encoder.result_counts()["FAILED"] == 0


def test_retry_report_includes_provenance_block(tmp_path: Path):
    encoder = make_retry_encoder(tmp_path, [tmp_path / "gone.mkv"])

    report = json.loads(encoder.report_file.read_text(encoding="utf-8"))

    assert report["input"]["kind"] == "retry"
    assert report["retry"]["selected_status"] == "FAILED"
    assert report["retry"]["source_run_id"] == "20260101-000000_src_hash_nonce"
    assert report["retry"]["selected_failed_count"] == 1


def test_retry_warns_about_leftover_temp_output(tmp_path: Path, fake_media):
    import logging

    target = tmp_path / "clip.mkv"
    target.write_bytes(b"x" * 128)
    leftover = tmp_path / "clip_HevcEncoder_crf-20.mp4"
    leftover.write_bytes(b"x" * 4096)

    failed_entries = {str(target.resolve(strict=False)): {"temp_output_path": str(leftover)}}

    # The project's logger sets propagate=False, so attach a handler directly.
    messages: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    encoder = make_retry_encoder(tmp_path, [target], failed_entries=failed_entries)
    encoder.logger.addHandler(Capture())
    encoder.encode_videos()

    assert any("Existing temp output for retry target" in m for m in messages)
    # Warn-only: the leftover temp file is never touched.
    assert leftover.exists()


# --------------------------------------------------------------------------- #
# handle_status failure enrichment + warnings
# --------------------------------------------------------------------------- #
def test_failed_entry_carries_encoder_failure_metadata(tmp_path: Path, fake_media):
    target = tmp_path / "ffmpeg_fail.mkv"
    target.write_bytes(b"x" * 128)

    encoder = make_retry_encoder(tmp_path, [target])
    encoder.encode_videos()

    entry = list(encoder.results["FAILED"].values())[0]
    assert entry["failure_type"] == "ffmpeg_failed"
    assert entry["return_code"] == 1
    assert entry["stderr_tail"] == "boom"
    assert entry["reason"].startswith("ffmpeg returned")


def test_failed_entry_falls_back_to_encode_failed(tmp_path: Path, fake_media):
    target = tmp_path / "bare_fail.mkv"
    target.write_bytes(b"x" * 128)

    encoder = make_retry_encoder(tmp_path, [target])
    encoder.encode_videos()

    entry = list(encoder.results["FAILED"].values())[0]
    assert entry["failure_type"] == "encode_failed"
    assert entry["reason"] == "Encoding failed."


def test_warnings_attached_to_successful_entry(tmp_path: Path, fake_media):
    target = tmp_path / "warned_success.mkv"
    target.write_bytes(b"x" * 128)

    encoder = make_retry_encoder(tmp_path, [target])
    encoder.encode_videos()

    entry = list(encoder.results["SUCCESS"].values())[0]
    assert entry["warnings"][0]["warning_type"] == "progress_ui_error"


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
def test_parse_arguments_encode_mode_default_shim():
    # Bare path with no subcommand defaults to encode (backward compatibility).
    args = batch_encoding.parse_arguments(["some/path.mp4"])
    assert args.mode == "encode"
    assert args.input_path == "some/path.mp4"


def test_parse_arguments_explicit_encode_subcommand():
    args = batch_encoding.parse_arguments(["encode", "some/path.mp4", "--codec", "av1"])
    assert args.mode == "encode"
    assert args.input_path == "some/path.mp4"
    assert args.codec == "av1"


def test_parse_arguments_requires_a_target():
    # encode subcommand (via shim) with no positional is an error, as before.
    with pytest.raises(SystemExit):
        batch_encoding.parse_arguments([])


def test_parse_arguments_retry_no_target():
    args = batch_encoding.parse_arguments(["retry"])
    assert args.mode == "retry"
    assert args.retry_target is None


def test_parse_arguments_retry_latest():
    args = batch_encoding.parse_arguments(["retry", "latest"])
    assert args.mode == "retry"
    assert args.retry_target == "latest"


def test_parse_arguments_retry_keeps_encode_options():
    args = batch_encoding.parse_arguments(
        ["retry", "report.json", "--codec", "av1", "--skip-codecs", "efficient"]
    )
    assert args.mode == "retry"
    assert args.retry_target == "report.json"
    assert args.codec == "av1"


def test_parse_arguments_unpassed_options_are_absent():
    # SUPPRESS defaults: options the user did not pass are not on the namespace.
    args = batch_encoding.parse_arguments(["encode", "d"])
    assert not hasattr(args, "codec")
    assert not hasattr(args, "min_size")


def test_parse_arguments_retry_has_use_current_config_flag():
    args = batch_encoding.parse_arguments(["retry", "latest", "--use-current-config"])
    assert args.use_current_config is True
    args = batch_encoding.parse_arguments(["retry", "latest"])
    assert args.use_current_config is False


# --------------------------------------------------------------------------- #
# Option resolution / precedence
# --------------------------------------------------------------------------- #
REPORT_OPTIONS = {
    "codec": "av1",
    "min_size": "500MB",
    "skip_codecs": "none",
    "denoise": "heavy",
    "fast_decode": "1",
    "tune": "2",
    "verify": True,
    "check_size": False,
    "delete_origin": False,
    "delete_threshold": 80.0,
    "min_resolution": "720p",
}


def test_resolve_options_encode_uses_config_then_cli():
    defaults = batch_encoding._config_option_defaults()

    bare = batch_encoding.resolve_encode_options(batch_encoding.parse_arguments(["encode", "d"]))
    assert bare["codec"] == defaults["codec"]

    overridden = batch_encoding.resolve_encode_options(
        batch_encoding.parse_arguments(["encode", "d", "--codec", "av1"])
    )
    assert overridden["codec"] == "av1"
    assert overridden["min_size"] == defaults["min_size"]


def test_resolve_options_retry_inherits_report():
    args = batch_encoding.parse_arguments(["retry", "latest"])
    opts = batch_encoding.resolve_encode_options(args, REPORT_OPTIONS)

    assert opts["codec"] == "av1"
    assert opts["denoise"] == "heavy"
    assert opts["verify"] is True
    assert opts["min_resolution"] == "720p"


def test_resolve_options_cli_overrides_report():
    args = batch_encoding.parse_arguments(
        ["retry", "latest", "--codec", "hevc", "--no-verify"]
    )
    opts = batch_encoding.resolve_encode_options(args, REPORT_OPTIONS)

    # Explicit flags win; everything else still comes from the report.
    assert opts["codec"] == "hevc"
    assert opts["verify"] is False
    assert opts["denoise"] == "heavy"


def test_resolve_options_use_current_config_skips_report():
    defaults = batch_encoding._config_option_defaults()
    args = batch_encoding.parse_arguments(["retry", "latest", "--use-current-config"])
    # main() passes report_options=None when the flag is set.
    opts = batch_encoding.resolve_encode_options(args, None)

    assert opts["codec"] == defaults["codec"]
    assert opts["denoise"] == defaults["denoise"]
