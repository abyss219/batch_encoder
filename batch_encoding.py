from __future__ import annotations

from typing import Any, Optional, Type, Union
import argparse
import heapq
import json
import logging
import pickle
import re
import sys
import time
from pathlib import Path

from encoder import MediaFile
from config import load_config, EncodingStatus, RESOLUTION
from utils import setup_logger, color_text
from encoder.batch import (
    BatchInput,
    discover_batch_input,
    format_skip_codecs,
    make_run_id,
    make_state_id,
    resolve_skip_codecs,
)
from encoder.retry import (
    load_summary_report,
    make_retry_batch_input,
    make_retry_context,
    resolve_retry_report,
)
from encoder.encoders.custom_encoder import get_custom_encoding_class
from encoder.encoders.encoder import PresetCRFEncoder


config = load_config()

VERSION = "1.1.0"
STATUS_ORDER = (
    EncodingStatus.SUCCESS,
    EncodingStatus.SKIPPED,
    EncodingStatus.FAILED,
    EncodingStatus.LOWQUALITY,
    EncodingStatus.LARGESIZE,
)


MODES = ("encode", "retry")


def parse_arguments(argv: Optional[list[str]] = None):
    """
    Parses command-line arguments for batch video encoding.

    Two subcommands share the same encode options:

    - ``encode <dir|list.txt|video>``: the normal batch encode. A directory is
      scanned recursively, a text file is read as one path per line, and a
      single video file is a one-item batch.
    - ``retry [latest|<summary.json>]``: re-run only the FAILED records of a
      previous summary report.

    ``encode`` is the default: ``batch_encoding.py <path>`` is treated as
    ``batch_encoding.py encode <path>`` so existing commands keep working.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    # Default to the encode subcommand when no subcommand is given, so the
    # historical `batch_encoding.py <path>` form still works.
    if not argv or (argv[0] not in MODES and not argv[0].startswith("-")):
        argv = ["encode"] + argv

    # Shared encode options live on a parent parser so each subcommand inherits
    # them without duplication and gets them in its own --help output.
    common = argparse.ArgumentParser(add_help=False)
    _add_common_options(common)

    parser = argparse.ArgumentParser(
        description="Batch video encoding script with resume support.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True, metavar="{encode,retry}")

    encode_parser = subparsers.add_parser(
        "encode",
        parents=[common],
        help="Encode a video directory, a path list, or a single video file.",
        description="Encode a video directory, a path list, or a single video file.",
    )
    encode_parser.add_argument(
        "input_path",
        help="Path to a video directory, a video path list, or a single video file.",
    )

    retry_parser = subparsers.add_parser(
        "retry",
        parents=[common],
        help="Retry only the FAILED records of a previous summary report.",
        description=(
            "Retry only the FAILED records of a previous summary report. "
            "LARGESIZE, LOWQUALITY, SKIPPED, and SUCCESS records are never retried."
        ),
    )
    retry_parser.add_argument(
        "retry_target",
        nargs="?",
        default=None,
        metavar="latest|<summary.json>",
        help=(
            "Retry source: omit for an interactive newest-first menu, "
            "'latest' for the newest summary report, or a path to a "
            "specific batch_encoder_*_summary.json file."
        ),
    )

    return parser.parse_args(argv)


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    """Registers the encode options shared by normal and retry modes."""
    parser.add_argument(
        "--min-size",
        default=config.batch.min_size,
        help=(
            "Specify the minimum file size for encoding.\n"
            "Example formats: '500MB', '1GB', '200KB'.\n"
            "Videos smaller than this threshold will be skipped.\n"
            f"Default: {config.batch.min_size}."
        ),
    )

    parser.add_argument(
        "--codec",
        choices=["hevc", "av1"],
        default=config.batch.codec,
        help=(
            "Choose the codec for encoding:\n"
            "  hevc - High Efficiency Video Coding (H.265)\n"
            "  av1  - Next-gen AV1 codec for better compression and efficiency."
        ),
    )

    parser.add_argument(
        "--skip-codecs",
        nargs="+",
        default=config.batch.skip_codecs,
        help=(
            "Codecs to copy instead of re-encoding. Use 'efficient' for "
            "av1/hevc/vp9/vvc/theora, 'none' to re-encode all video codecs, "
            "or pass a comma/space-separated list such as 'hevc' or 'hevc,vp9'. "
            f"Default: {config.batch.skip_codecs}."
        ),
    )

    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="Reset the encoding state and restart the process from scratch.",
    )

    parser.add_argument(
        "--denoise",
        choices=["light", "mild", "moderate", "heavy"],
        default=config.batch.denoise,
        help=(
            "Apply a denoising filter to improve video quality:\n"
            "  light    - Reduces minor noise while preserving details\n"
            "  mild     - Balanced denoising, removes moderate noise\n"
            "  moderate - Good for reducing grain in low-light videos\n"
            "  heavy    - Strong denoising, suitable for old/noisy videos"
        ),
    )

    parser.add_argument(
        "--fast-decode",
        type=int,
        choices=[0, 1, 2],
        default=config.svt_av1.fast_decode,
        help=(
            "Enable fast decode optimizations for AV1:\n"
            "  0 - No optimization (best compression, slowest decoding)\n"
            "  1 - Balanced mode (good compression, faster decoding)\n"
            "  2 - Maximum optimization (fastest decoding, larger file sizes)"
        ),
    )

    parser.add_argument(
        "--tune",
        type=int,
        choices=[0, 1, 2],
        default=config.svt_av1.tune,
        help=(
            "Select the tuning metric for encoding quality:\n"
            "  0 - VQ (Visual Quality): Best subjective quality for general use\n"
            "  1 - PSNR: Optimizes for peak signal-to-noise ratio\n"
            "  2 - SSIM: Preserves structural details for perceptual quality"
        ),
    )

    parser.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=config.verify.verify,
        help=(
            "Enable or disable VMAF verification. If enabled, the script compares "
            "the original and encoded videos before deleting the original."
        ),
    )

    parser.add_argument(
        "--check-size",
        action=argparse.BooleanOptionalAction,
        default=config.verify.check_size,
        help=(
            "Enable or disable file size checks after encoding. If enabled, larger "
            "encoded videos are removed and reported as LARGESIZE."
        ),
    )

    parser.add_argument(
        "--delete-origin",
        action=argparse.BooleanOptionalAction,
        default=config.verify.delete_origin,
        help=(
            "Enable or disable replacing the original video with the encoded video. "
            "The original is removed only after successful checks."
        ),
    )

    parser.add_argument(
        "--delete-threshold",
        type=lambda x: (
            float(x)
            if 0 <= float(x) <= 100
            else argparse.ArgumentTypeError("Threshold must be between 0 and 100.")
        ),
        default=config.verify.delete_threshold,
        help="Minimum VMAF score required to delete the original video.",
    )

    parser.add_argument(
        "--min-resolution",
        choices=["4k", "2k", "1080p", "720p", "480p", "360p"],
        default=config.batch.min_resolution,
        help=(
            "Set the minimum resolution threshold for encoding.\n"
            "Videos with lower resolutions will be skipped."
        ),
    )

    parser.add_argument(
        "--debug", action="store_true", help="Enable verbose debug logging."
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
        help="Show the version number and exit.",
    )


class BatchEncoder:
    """
    Handles batch video encoding with resume support.

    The class intentionally keeps encoding behavior inside the existing encoder
    classes. BatchEncoder owns input discovery, queueing, state, logs, and reports.
    """

    def __init__(
        self,
        batch_input: BatchInput,
        encoding_class: Type[PresetCRFEncoder],
        codec: str,
        min_size: Union[str, float] = config.batch.min_size,
        verify: bool = config.verify.verify,
        check_size: bool = config.verify.check_size,
        delete_origin: bool = config.verify.delete_origin,
        delete_threshold: float = config.verify.delete_threshold,
        force_reset: bool = False,
        denoise: Optional[str] = None,
        fast_decode: int = config.svt_av1.fast_decode,
        tune: int = config.svt_av1.tune,
        min_resolution: Optional[str] = None,
        skip_codecs: Optional[set[str]] = None,
        debug: bool = False,
        retry_context: Optional[dict[str, Any]] = None,
    ):
        self.batch_input = batch_input
        self.retry_context = retry_context
        self.is_retry_mode = retry_context is not None
        self.encoding_class = encoding_class
        self.codec = codec
        self.min_size = min_size
        self.min_size_bytes = self.parse_size(min_size)
        self.verify = verify
        self.check_size = check_size
        self.delete_origin = delete_origin
        self.delete_threshold = delete_threshold
        self.denoise = denoise
        self.fast_decode = str(fast_decode)
        self.tune = str(tune)
        self.min_resolution = min_resolution
        self.skip_codecs = set(
            skip_codecs if skip_codecs is not None else resolve_skip_codecs(config.batch.skip_codecs)
        )
        self.debug = debug

        self.run_id = make_run_id(batch_input)
        self.state_id = make_state_id(
            batch_input=batch_input,
            codec=codec,
            min_size=str(min_size),
            min_resolution=min_resolution,
            skip_codecs=self.skip_codecs,
        )

        log_dir = Path(config.general.log_dir)
        self.log_filename = f"batch_encoder_{self.run_id}.log"
        self.log_file = log_dir / self.log_filename
        self.report_file = log_dir / f"batch_encoder_{self.run_id}_summary.json"
        self.state_file = log_dir / f"batch_encoder_state_{self.state_id}.pkl"

        self.logger = setup_logger(
            self.__class__.__name__,
            self.log_file,
            logging.DEBUG if debug else logging.INFO,
        )

        self.video_queue: list[tuple[int, str]] = []
        self.results: dict[str, dict[str, dict[str, Any]]] = self._empty_results()
        self.total_original_size = 0
        self.total_encoded_size = 0
        self.start_time = time.time()

        self.logger.info(
            f"Run ID: {color_text(self.run_id, 'cyan', bold=True)} | "
            f"Input: {color_text(self.batch_input.source_path, dim=True)} | "
            f"Mode: {color_text(self.batch_input.kind, 'cyan')} | "
            f"Skip codecs: {color_text(format_skip_codecs(self.skip_codecs), 'yellow')}"
        )
        self.logger.debug(f"State file: {self.state_file}")
        self.logger.debug(f"Report file: {self.report_file}")

        if not force_reset and self.load_state():
            self.logger.info(
                f"Resumed encoding session for {color_text(self.batch_input.source_path, dim=True)}."
            )
        else:
            self.reset_state()
            self.prepare_video_queue()

        self.save_state()
        self.write_report()

        self.initial_queue_size = len(self.video_queue)

    def _empty_results(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {status.name: {} for status in STATUS_ORDER}

    def get_video_files(self) -> list[Path]:
        self.logger.debug(
            f"Input discovery returned {len(self.batch_input.video_paths)} unique paths."
        )
        return list(self.batch_input.video_paths)

    def prepare_video_queue(self):
        """
        Prepares a priority queue for encoding, prioritizing larger files.
        """
        video_files = self.get_video_files()
        temp_queue: list[tuple[int, str]] = []
        processed_paths = self.processed_paths

        for file in video_files:
            path_key = str(file)
            if path_key in processed_paths:
                continue

            try:
                if not file.is_file():
                    if self.is_retry_mode:
                        # In retry mode an unavailable path must stay FAILED, or it
                        # would drop out of the FAILED bucket and never be retried.
                        self.record_result(
                            EncodingStatus.FAILED,
                            file,
                            reason="Input path does not exist or is not a file.",
                            failure_type="path_unavailable",
                            path_exists_at_failure=False,
                            batch_root_exists_at_failure=self._batch_root_exists(),
                        )
                    else:
                        self.record_result(
                            EncodingStatus.SKIPPED,
                            file,
                            reason="Input path does not exist or is not a file.",
                        )
                    continue

                file_size = file.stat().st_size
                if file_size < self.min_size_bytes:
                    self.record_result(
                        EncodingStatus.SKIPPED,
                        file,
                        reason=(
                            f"Below minimum size threshold of {self.min_size} "
                            f"(actual: {self.encoding_class.human_readable_size(file_size)})."
                        ),
                        original_size=file_size,
                    )
                    continue

                media_file = MediaFile(
                    file, debug=self.debug, log_filename=self.log_filename
                )

                if self.min_resolution is not None and self.should_skip_resolution(media_file):
                    self.record_result(
                        EncodingStatus.SKIPPED,
                        file,
                        reason=(
                            f"All video streams are below threshold of {self.min_resolution}."
                        ),
                        original_size=file_size,
                    )
                    continue

                temp_queue.append((-file_size, str(media_file.file_path)))
                self.logger.debug(f"Queued video {media_file.file_path.name}")
            except ValueError:
                self.record_result(
                    EncodingStatus.SKIPPED,
                    file,
                    reason="Not a valid video file.",
                )
            except Exception as e:
                self.record_result(
                    EncodingStatus.FAILED,
                    file,
                    reason=f"Error preparing video: {e}",
                )

        heapq.heapify(temp_queue)
        self.video_queue = temp_queue
        self.logger.info(
            f"Prepared {color_text(len(self.video_queue), 'cyan', bold=True)} videos for encoding."
        )

    def should_skip_resolution(self, media_file: MediaFile) -> bool:
        return all(
            video_stream.width
            and video_stream.height
            and (
                video_stream.width * video_stream.height
                < RESOLUTION.get(self.min_resolution, 0)
            )
            for video_stream in media_file.video_info
        )

    def encode_videos(self):
        """
        Processes the video queue, encoding videos in priority order.
        """
        while self.video_queue:
            neg_file_size, file_path = heapq.heappop(self.video_queue)
            path = Path(file_path)
            original_size = -neg_file_size

            self.logger.info(
                f"🎥 Encoding {color_text(path.name, dim=True)} of size "
                f"{color_text(self.encoding_class.human_readable_size(original_size), 'yellow')}, "
                f"{color_text(self.initial_queue_size - len(self.video_queue), 'magenta')} / "
                f"{color_text(self.initial_queue_size, 'cyan', bold=True)} videos have been processed."
            )

            if self.is_retry_mode:
                self._warn_existing_temp_output(file_path)

            start_time = time.time()
            try:
                media_file = MediaFile(path, debug=self.debug, log_filename=self.log_filename)
                encoder = self.encoding_class(
                    media_file,
                    delete_original=self.delete_origin,
                    verify=self.verify,
                    delete_threshold=self.delete_threshold,
                    check_size=self.check_size,
                    denoise=self.denoise,
                    fast_decode=self.fast_decode,
                    tune=self.tune,
                    skip_codecs=self.skip_codecs,
                    debug=self.debug,
                    log_filename=self.log_filename,
                )

                status = encoder.encode_wrapper()
                self.handle_status(
                    status=status,
                    path=media_file.file_path,
                    encoder=encoder,
                    original_size=original_size,
                    duration_seconds=time.time() - start_time,
                )
            except FileNotFoundError as e:
                self.logger.warning(f"⚠️ Path unavailable during encode: {e}")
                self.record_result(
                    EncodingStatus.FAILED,
                    path,
                    reason="Input path does not exist or is not a file.",
                    failure_type="path_unavailable",
                    exception_type="FileNotFoundError",
                    exception_message=str(e),
                    path_exists_at_failure=path.exists(),
                    batch_root_exists_at_failure=self._batch_root_exists(),
                    original_size=original_size,
                    duration_seconds=time.time() - start_time,
                )
            except Exception as e:
                self.logger.exception(e)
                self.record_result(
                    EncodingStatus.FAILED,
                    path,
                    reason=f"Unexpected batch error: {e}",
                    failure_type="unexpected_exception",
                    exception_type=type(e).__name__,
                    exception_message=str(e),
                    original_size=original_size,
                    duration_seconds=time.time() - start_time,
                )

            self.logger.info(
                f"🕐 Encoding took {color_text(self.format_time(time.time() - start_time), 'cyan')}"
            )
            self.save_state()
            self.write_report()

        self.log_final_results()
        self.write_report()

    def handle_status(
        self,
        status: EncodingStatus,
        path: Path,
        encoder: PresetCRFEncoder,
        original_size: int,
        duration_seconds: float,
    ):
        if status == EncodingStatus.SUCCESS:
            encoded_size = self.safe_file_size(encoder.new_file_path)
            self.total_original_size += original_size
            self.total_encoded_size += encoded_size or 0
            self.record_result(
                EncodingStatus.SUCCESS,
                path,
                reason="Encoding completed successfully.",
                output_path=encoder.new_file_path,
                original_size=original_size,
                encoded_size=encoded_size,
                duration_seconds=duration_seconds,
                **self._warning_metadata(encoder),
            )
        elif status == EncodingStatus.SKIPPED:
            self.record_result(
                EncodingStatus.SKIPPED,
                path,
                reason="Already in a codec configured by --skip-codecs.",
                original_size=original_size,
                duration_seconds=duration_seconds,
                **self._warning_metadata(encoder),
            )
        elif status == EncodingStatus.FAILED:
            metadata = encoder.failure_metadata()
            reason = metadata.pop("reason", None) or "Encoding failed."
            metadata.setdefault("failure_type", "encode_failed")
            self.record_result(
                EncodingStatus.FAILED,
                path,
                reason=reason,
                original_size=original_size,
                duration_seconds=duration_seconds,
                **metadata,
            )
            self.logger.warning(f"❌ Encoding failed for {path}: {reason}")
        elif status == EncodingStatus.LOWQUALITY:
            output_path = encoder.output_tmp_file
            encoded_size = self.safe_file_size(output_path)
            self.record_result(
                EncodingStatus.LOWQUALITY,
                path,
                reason="Encoded video did not meet the VMAF quality threshold.",
                output_path=output_path,
                original_size=original_size,
                encoded_size=encoded_size,
                duration_seconds=duration_seconds,
                **self._warning_metadata(encoder),
            )
            encoder._delete_encoded()
            self.logger.warning(
                f"❌ LOWQUALITY for {color_text(path.name, dim=True)}. Encoded video deleted."
            )
        elif status == EncodingStatus.LARGESIZE:
            output_path = encoder.output_tmp_file
            encoded_size = self.safe_file_size(output_path)
            size_log = self.format_size_change(original_size, encoded_size)
            self.record_result(
                EncodingStatus.LARGESIZE,
                path,
                reason=f"Encoded video is larger than the original ({size_log}).",
                output_path=output_path,
                original_size=original_size,
                encoded_size=encoded_size,
                duration_seconds=duration_seconds,
                **self._warning_metadata(encoder),
            )
            encoder._delete_encoded()
            self.logger.warning(
                f"❌ LARGESIZE for {path}: {color_text(size_log, 'magenta')}. Encoded video deleted."
            )

    def record_result(
        self,
        status: EncodingStatus,
        path: Path,
        reason: str,
        **metadata: Any,
    ):
        path_key = str(path)
        for bucket in self.results.values():
            bucket.pop(path_key, None)

        entry = {
            "path": path_key,
            "reason": reason,
        }
        for key, value in metadata.items():
            entry[key] = self.json_safe(value)

        entry["status"] = status.name
        entry["status_value"] = status.value

        self.results[status.name][path_key] = entry

        if status == EncodingStatus.SKIPPED:
            self.logger.debug(f"Skipping {path}: {reason}")
        else:
            self.logger.debug(f"Recorded {status.name} for {path}: {reason}")

    @staticmethod
    def _warning_metadata(encoder: PresetCRFEncoder) -> dict[str, Any]:
        """Surface any non-fatal encoder warnings into the result entry."""
        warnings = getattr(encoder, "last_warnings", None)
        return {"warnings": list(warnings)} if warnings else {}

    def _batch_root_exists(self) -> Optional[bool]:
        try:
            return self.batch_input.source_path.exists()
        except OSError:
            return None

    def _warn_existing_temp_output(self, file_path: str) -> None:
        """Warn (without touching) about leftover temp output for a retry target."""
        entries = (self.retry_context or {}).get("_failed_entries") or {}
        entry = entries.get(file_path)
        if not entry:
            return
        temp_path = entry.get("temp_output_path")
        if not temp_path:
            return
        temp = Path(temp_path)
        try:
            if not temp.is_file():
                return
            size = self.encoding_class.human_readable_size(temp.stat().st_size)
        except OSError:
            return
        self.logger.warning(
            f"⚠️ Existing temp output for retry target: {temp} ({size}). "
            "It will not be reused or deleted automatically."
        )

    @property
    def processed_paths(self) -> set[str]:
        processed: set[str] = set()
        for bucket in self.results.values():
            processed.update(bucket.keys())
        return processed

    def save_state(self):
        state = {
            "input_path": str(self.batch_input.source_path),
            "input_kind": self.batch_input.kind,
            "codec": self.codec,
            "skip_codecs": sorted(self.skip_codecs),
            "min_size": self.min_size,
            "min_resolution": self.min_resolution,
            "results": self.results,
            "video_queue": self.video_queue,
            "total_original_size": self.total_original_size,
            "total_encoded_size": self.total_encoded_size,
            "time_elapsed": time.time() - self.start_time,
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with self.state_file.open("wb") as f:
                pickle.dump(state, f)
            self.logger.debug("State saved successfully.")
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")

    def load_state(self) -> bool:
        if not self.state_file.is_file():
            self.logger.info(
                f"No previous encoding session found for {self.batch_input.source_path}."
            )
            return False

        try:
            with self.state_file.open("rb") as f:
                state = pickle.load(f)

            if not self.state_matches_current_run(state):
                self.logger.info("Saved encoding session has different parameters. Restarting.")
                return False

            self.results = self.normalize_results(state.get("results", {}))
            self.video_queue = state.get("video_queue", [])
            heapq.heapify(self.video_queue)
            self.total_original_size = state.get("total_original_size", 0)
            self.total_encoded_size = state.get("total_encoded_size", 0)
            self.start_time = time.time() - state.get("time_elapsed", 0)

            if not self.video_queue:
                self.logger.info(
                    f"Previous encoding has finished or has no remaining queue. Restarting for {color_text(self.batch_input.source_path, dim=True)}."
                )
                return False

            return True
        except Exception as e:
            self.logger.error("Failed to load state")
            self.logger.exception(e)
            return False

    def state_matches_current_run(self, state: dict[str, Any]) -> bool:
        return (
            state.get("input_path") == str(self.batch_input.source_path)
            and state.get("input_kind") == self.batch_input.kind
            and state.get("codec") == self.codec
            and state.get("skip_codecs") == sorted(self.skip_codecs)
            and state.get("min_size") == self.min_size
            and state.get("min_resolution") == self.min_resolution
        )

    def normalize_results(
        self, saved_results: dict[str, dict[str, dict[str, Any]]]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        results = self._empty_results()
        for status in STATUS_ORDER:
            for key in (status.name, status.value):
                bucket = saved_results.get(key, {})
                for path, entry in bucket.items():
                    entry = dict(entry)
                    entry["status"] = status.name
                    entry["status_value"] = status.value
                    results[status.name][path] = entry
        return results

    def reset_state(self):
        self.results = self._empty_results()
        self.video_queue.clear()
        self.total_original_size = 0
        self.total_encoded_size = 0
        self.save_state()
        self.logger.info("Encoding state reset.")

    def write_report(self):
        report = {
            "run_id": self.run_id,
            "state_id": self.state_id,
            "input": {
                "path": str(self.batch_input.source_path),
                "kind": self.batch_input.kind,
                "label": self.batch_input.label,
                "target_hash": self.batch_input.target_hash,
                "discovered_paths": len(self.batch_input.video_paths),
            },
            "options": {
                "codec": self.codec,
                "min_size": self.min_size,
                "min_resolution": self.min_resolution,
                "denoise": self.denoise,
                "verify": self.verify,
                "check_size": self.check_size,
                "delete_origin": self.delete_origin,
                "delete_threshold": self.delete_threshold,
                "skip_codecs": format_skip_codecs(self.skip_codecs),
                "fast_decode": self.fast_decode,
                "tune": self.tune,
            },
            "files": {
                "log": str(self.log_file),
                "state": str(self.state_file),
                "report": str(self.report_file),
            },
            "counts": self.result_counts(),
            "totals": {
                "successful_original_size": self.total_original_size,
                "successful_encoded_size": self.total_encoded_size,
                "successful_disk_saved": self.total_original_size - self.total_encoded_size,
                "elapsed_seconds": round(time.time() - self.start_time, 3),
            },
            "results": {
                status.name: list(self.results[status.name].values())
                for status in STATUS_ORDER
            },
        }

        if self.retry_context:
            report["retry"] = {
                "source_report": self.retry_context.get("source_report"),
                "source_run_id": self.retry_context.get("source_run_id"),
                "source_input": self.retry_context.get("source_input"),
                "selected_status": self.retry_context.get("selected_status", "FAILED"),
                "selected_failed_count": self.retry_context.get("selected_failed_count"),
            }

        try:
            self.report_file.parent.mkdir(parents=True, exist_ok=True)
            with self.report_file.open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to write report: {e}")

    def log_final_results(self):
        total_time_seconds = time.time() - self.start_time
        final_avg_reduction = self.final_average_reduction()

        self.logger.info(color_text("==== Encoding Process Detail ====", dim=True))
        self.logger.info(
            f"Input: {color_text(self.batch_input.source_path, 'cyan')} "
            f"({self.batch_input.kind})"
        )
        self.logger.info(
            f"Run ID: {color_text(self.run_id, 'cyan', bold=True)} | "
            f"Report: {color_text(self.report_file, dim=True)}"
        )

        for status in STATUS_ORDER:
            entries = list(self.results[status.name].values())
            label = self.status_label(status)
            self.logger.info(
                f"{label}: {color_text(str(len(entries)), self.status_color(status), bold=True)}"
            )
            for entry in entries:
                reason = entry.get("reason", "")
                self.logger.info(
                    f"  - {color_text(entry['path'], dim=True)} | {reason}"
                )

        self.logger.info(
            "📉 Final average size reduction: "
            f"{color_text(f'{final_avg_reduction:.2f}%', 'magenta')}."
        )
        self.logger.info(
            "💾 Total disk space saved: "
            f"{color_text(self.encoding_class.human_readable_size(self.total_original_size - self.total_encoded_size), 'magenta', bold=True)}."
        )
        self.logger.info(
            f"⌛ Time taken: {color_text(self.format_time(total_time_seconds), 'blue', bold=True)}"
        )
        self.logger.info(color_text("====================================", dim=True))

    def result_counts(self) -> dict[str, int]:
        return {status.name: len(self.results[status.name]) for status in STATUS_ORDER}

    def final_average_reduction(self) -> float:
        if self.total_original_size <= 0:
            return 0.0
        return 100 * (1 - (self.total_encoded_size / self.total_original_size))

    def safe_file_size(self, path: Optional[Path]) -> Optional[int]:
        if path is None:
            return None
        try:
            return path.stat().st_size if path.is_file() else None
        except OSError:
            return None

    def format_size_change(self, original_size: int, encoded_size: Optional[int]) -> str:
        original = self.encoding_class.human_readable_size(original_size)
        if encoded_size is None:
            return f"{original} -> unknown"
        encoded = self.encoding_class.human_readable_size(encoded_size)
        return f"{original} -> {encoded}"

    def json_safe(self, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        return value

    @staticmethod
    def status_label(status: EncodingStatus) -> str:
        return {
            EncodingStatus.SUCCESS: "✅ SUCCESS",
            EncodingStatus.SKIPPED: "⏭️ SKIPPED",
            EncodingStatus.FAILED: "❌ FAILED",
            EncodingStatus.LOWQUALITY: "📉 LOWQUALITY",
            EncodingStatus.LARGESIZE: "📦 LARGESIZE",
        }[status]

    @staticmethod
    def status_color(status: EncodingStatus) -> str:
        return {
            EncodingStatus.SUCCESS: "cyan",
            EncodingStatus.SKIPPED: "yellow",
            EncodingStatus.FAILED: "red",
            EncodingStatus.LOWQUALITY: "magenta",
            EncodingStatus.LARGESIZE: "magenta",
        }[status]

    @staticmethod
    def parse_size(size: Union[str, float]) -> int:
        if isinstance(size, (int, float)):
            return int(size)

        size = size.strip().lower()
        size_map = {"kb": 1_024, "mb": 1_048_576, "gb": 1_073_741_824, "b": 1}

        match = re.match(r"([\d\.]+)\s*([kmgt]?b)", size)
        if match:
            value, unit = match.groups()
            return int(float(value) * size_map.get(unit, 1))

        raise ValueError(f"Invalid size format: {size}")

    @staticmethod
    def format_time(seconds: float) -> str:
        seconds = round(seconds)

        weeks, remainder = divmod(seconds, 604800)
        days, remainder = divmod(remainder, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        formatted_time = []

        if weeks > 0:
            formatted_time.append(f"{int(weeks)} week{'s' if weeks > 1 else ''}")
        if days > 0:
            formatted_time.append(f"{int(days)} day{'s' if days > 1 else ''}")
        if hours > 0:
            formatted_time.append(f"{int(hours)} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            formatted_time.append(f"{int(minutes)} minute{'s' if minutes > 1 else ''}")
        if seconds > 0 or not formatted_time:
            formatted_time.append(f"{int(seconds)} second{'s' if seconds > 1 else ''}")

        return ", ".join(formatted_time)


def main() -> int:
    args = parse_arguments()

    try:
        skip_codecs = resolve_skip_codecs(args.skip_codecs)
        encoding_class = get_custom_encoding_class(args.codec)

        if args.mode == "retry":
            log_dir = Path(config.general.log_dir)
            report_path = resolve_retry_report(args.retry_target, log_dir)
            report = load_summary_report(report_path)
            batch_input = make_retry_batch_input(report_path, report)
            retry_context = make_retry_context(report_path, report, batch_input)
        else:
            batch_input = discover_batch_input(args.input_path)
            retry_context = None
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    encoder = BatchEncoder(
        batch_input=batch_input,
        encoding_class=encoding_class,
        codec=args.codec,
        min_size=args.min_size,
        force_reset=args.force_reset,
        denoise=args.denoise,
        verify=args.verify,
        check_size=args.check_size,
        delete_origin=args.delete_origin,
        delete_threshold=args.delete_threshold,
        min_resolution=args.min_resolution,
        fast_decode=args.fast_decode,
        tune=args.tune,
        skip_codecs=skip_codecs,
        debug=args.debug,
        retry_context=retry_context,
    )
    encoder.encode_videos()
    return 0


if __name__ == "__main__":
    sys.exit(main())
