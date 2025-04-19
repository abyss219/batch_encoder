from typing import Union, List, Optional
import re
import os
import heapq
import pickle
import hashlib
import argparse
import sys
import time
import logging
from encoder import *
from config import load_config, EncodingStatus, RESOLUTION
from utils import setup_logger, color_text
from encoder.encoders.custom_encoder import get_custom_encoding_class

config = load_config()

# Supported video file extensions
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".flv",
    ".webm",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".m4v",
    ".3gp",
    ".3g2",
    ".ts",
    ".m2ts",
    ".mts",
    ".vob",
    ".ogv",
    ".rm",
    ".rmvb",
    ".divx",
    ".f4v",
    ".swf",
    ".amv",
    ".asf",
    ".mxf",
    ".dv",
    ".qt",
    ".yuv",
    ".mpe",
    ".mpv",
    ".m1v",
    ".m2v",
    ".svi",
    ".drc",
    ".ivf",
    ".nsv",
    ".fli",
    ".flc",
    ".gxf",
    ".roq",
    ".smi",
    ".smil",
    ".wm",
    ".wtv",
}

# Default settings
DEFAULT_MIN_SIZE = "100MB"
DEFAULT_DENOISE = "none"
DEFAULT_CODEC = "hevc"
DEFAULT_FAST_DECODE = 1
DEFAULT_TUNE = 0


def parse_arguments():
    """
    Parses command-line arguments for batch video encoding.

    This function sets up command-line options to control batch encoding of videos using
    HEVC (H.265) or AV1, with features like resolution-based filtering, quality tuning,
    verification with VMAF, and multi-threaded optimizations.

    Available options:
    - Input directory containing videos
    - Minimum file size threshold for encoding
    - Codec selection (HEVC or AV1)
    - Video denoising options
    - CRF (Constant Rate Factor) control for quality vs. file size
    - Encoding preset selection for speed vs. compression efficiency
    - Resolution-based filtering to skip small videos
    - Fast decode optimization for AV1
    - Verification of encoded file quality using VMAF
    - Option to reset encoding progress

    Returns:
        argparse.Namespace: Parsed arguments containing user-specified values.
    """
    parser = argparse.ArgumentParser(
        description="Batch video encoding script with resume support."
    )

    parser.add_argument(
        "directory", help="Path to the directory containing video files for encoding."
    )

    parser.add_argument(
        "--min-size",
        default=DEFAULT_MIN_SIZE,
        help=(
            "Specify the minimum file size for encoding.\n"
            "Example formats: '500MB', '1GB', '200KB'.\n"
            "Videos smaller than this threshold will be skipped.\n"
            f"Default: {DEFAULT_MIN_SIZE}."
        ),
    )

    parser.add_argument(
        "--codec",
        choices=["hevc", "av1"],
        default=DEFAULT_CODEC,
        help=(
            "Choose the codec for encoding:\n"
            "  hevc - High Efficiency Video Coding (H.265) [default]\n"
            "  av1  - Next-gen AV1 codec for better compression and efficiency."
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
        default=DEFAULT_FAST_DECODE,
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
        default=DEFAULT_TUNE,
        help=(
            "Select the tuning metric for encoding quality:\n"
            "  0 - VQ (Visual Quality): Best subjective quality for general use\n"
            "  1 - PSNR: Optimizes for peak signal-to-noise ratio (technical evaluation)\n"
            "  2 - SSIM: Preserves structural details for better perceptual quality"
        ),
    )

    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Enable verification of encoded file quality using VMAF.\n"
            "If enabled, the script will compare the original and encoded videos\n"
            "and only delete the original if the VMAF score meets the threshold."
        ),
    )

    parser.add_argument(
        "--min-resolution",
        choices=["4k", "2k", "1080p", "720p", "480p", "360p"],
        help=(
            "Set the minimum resolution threshold for encoding.\n"
            "Videos with lower resolutions will be skipped.\n"
            "Options: 4k, 2k, 1080p, 720p, 480p, 360p."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force encoding of all videos, even if they are already in the desired codec.\n"
            "By default, videos in efficient codecs (HEVC, AV1, VP9, etc.) are skipped."
        ),
    )

    parser.add_argument(
        "--debug", action="store_true", help="Enable verbose debug logging."
    )

    return parser.parse_args()


class BatchEncoder:
    """
    Handles batch video encoding for an entire directory with resume support.

    This class automates the process of encoding videos using HEVC (H.265) or AV1,
    providing features such as:
    - Recursive file discovery
    - Resolution-based filtering
    - State saving for resume support
    - Multi-threaded prioritization of larger videos first
    - Automatic skipping of already encoded files
    - Encoding verification using VMAF
    - Custom denoising options

    It prioritizes larger videos using a max heap to maximize storage savings efficiently.
    """

    STATE_FILE_PREFIX = "encoder_state"
    LOG_FILE_PREFIX = "batch_encoding"

    # List of efficient codecs that do not require re-encoding
    EFFICIENT_CODEC = {"av1", "hevc", "vp9", "vvc", "theora"}

    def __init__(
        self,
        directory: str,
        min_size: Union[str, float] = DEFAULT_MIN_SIZE,
        verify: bool = False,
        force_reset: bool = False,
        denoise: str = None,
        fast_decode: int = DEFAULT_FAST_DECODE,
        tune: int = DEFAULT_TUNE,
        min_resolution: Optional[str] = None,
        force: bool = False,
        debug=False,
    ):
        """
        Initializes the BatchEncoder instance.

        Args:
            directory (str): The directory containing video files to be encoded.
            min_size (Union[str, float]): Minimum file size threshold for encoding.
                                          Videos smaller than this value are skipped.
            verify (bool): Whether to verify encoded video quality using VMAF before deleting originals.
            force_reset (bool): If True, resets encoding progress and starts fresh.
            denoise (str): Denoising filter level ('light', 'mild', 'moderate', 'heavy') or None.
            fast_decode (int): Fast decode setting for AV1 (0, 1, or 2).
            tune (int): AV1 tuning metric (0 = VQ, 1 = PSNR, 2 = SSIM).
            min_resolution (Optional[str]): Minimum resolution threshold (e.g., '720p').
                                            Videos below this are skipped.
            force (bool): If True, encodes all videos, even if they are already in an efficient codec.
        """

        if not os.path.isdir(directory):
            raise ValueError(
                f"The input to {self.__class__.__name__} must be a directory"
            )
        self.directory = directory
        self.min_size = min_size
        self.min_size_bytes = self.parse_size(min_size)
        self.dir_hash = self.hash_directory(directory)  # Generate hash for directory\
        self.log_file = os.path.join(
            config.general.log_dir, f"{self.LOG_FILE_PREFIX}_{self.dir_hash}.log"
        )
        self.state_file = os.path.join(
            config.general.log_dir, f"{self.STATE_FILE_PREFIX}_{self.dir_hash}.pkl"
        )

        self.denoise = denoise
        self.verify = verify
        self.fast_decode = str(fast_decode)
        self.tune = str(tune)
        self.min_resolution = min_resolution
        self.force = force

        self.video_queue = []
        self.success_encodings = set()  # Stores successfully encoded videos
        self.failed_encodings = set()  # Stores videos that failed encoding
        self.skipped_videos = {}  # Stores videos that were skipped and their reason

        self.total_original_size = 0  # for encoded videos only
        self.total_encoded_size = 0

        # Set up the logger
        self.debug = debug
        self.logger = setup_logger(
            self.__class__.__name__,
            self.log_file,
            logging.DEBUG if debug else logging.INFO,
        )
        self.logger.debug(f"Initializing BatchEncoder for directory: {directory}")

        # Load previous state if applicable
        if not force_reset and self.load_state():
            self.logger.debug(f"Resuming previous encoding session for {directory}.")
        else:
            self.reset_state()
            self.prepare_video_queue()

        self.save_state()

        self.initial_queue_size = len(
            self.video_queue
        )  # record the total queue size at the beginning
        self.start_time = time.time()

    @staticmethod
    def hash_directory(directory: str) -> str:
        """
        Generate a short hash for the directory path.

        Args:
            directory (str): Path of the directory to hash.

        Returns:
            str: An 8-character hash representing the directory.
        """
        return hashlib.md5(directory.encode()).hexdigest()[:8]  # Short hash

    def get_video_files(self) -> List[str]:
        """
        Recursively retrieves all video files in the directory.

        Returns:
            List[str]: A list of video file paths.
        """
        video_files = []
        for root, _, files in os.walk(self.directory):
            for file in files:
                if any(file.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
                    video_files.append(os.path.join(root, file))
                    self.logger.debug(f"Found video {file}")
        return video_files

    def prepare_video_queue(self):
        """
        Scans the directory and prepares a priority queue for encoding, prioritizing larger files.
        Skips files that have already been processed.
        """
        video_files = self.get_video_files()
        temp_queue = []

        for file in video_files:
            if file in self.success_encodings or file in self.failed_encodings:
                continue  # Skip already processed files

            try:
                file_size = os.path.getsize(file)
                if file_size < self.min_size_bytes:
                    log = f"Skipping {file} (Size: {CustomEncoding.human_readable_size(file_size)}) - Below threshold of {self.min_size}."
                    self.logger.debug(log)
                    self.skipped_videos[file] = log
                    continue

                media_file = MediaFile(file, debug=self.debug)

                if self.min_resolution is not None:
                    """Set to True if all video streams are below the resolution threshold, otherwise False."""
                    skip_resolution = all(
                        video_stream.width
                        and video_stream.height
                        and (
                            video_stream.width * video_stream.height
                            < RESOLUTION.get(self.min_resolution, 0)
                        )
                        for video_stream in media_file.video_info
                    )

                    if skip_resolution:
                        log = (
                            f"Skipping {file} "
                            f"- All video streams are below threshold of {self.min_resolution}."
                        )
                        self.logger.debug(log)
                        self.skipped_videos[file] = log
                        continue

                temp_queue.append(
                    (-file_size, media_file.file_path, media_file)
                )  # Max heap (largest size first)
            except ValueError:
                self.logger.warning(f"Skipping {file}, not a valid video.")
            except Exception as e:
                self.logger.error(f"Error processing {file}: {e}")

        heapq.heapify(temp_queue)  # More efficient than pushing one by one
        self.video_queue = temp_queue
        self.logger.info(f"Prepared {color_text(len(self.video_queue), 'cyan', bold=True)} videos for encoding.")

    def encode_videos(self):
        """
        Processes the video queue, encoding videos in priority order.
        """

        while self.video_queue:
            neg_file_size, _, media_file = heapq.heappop(self.video_queue)

            original_size = -neg_file_size
            self.logger.info(
                f"🎥 Encoding {color_text(media_file.file_name, dim=True)} of size "
                f"{color_text(CustomEncoding.human_readable_size(original_size), 'yellow')}, "
                f"{color_text(self.initial_queue_size - len(self.video_queue), 'cyan')}/{color_text(self.initial_queue_size, 'magenta', bold=True)} "
                f"videos has been processed"
            )

            ignore_codec = {} if self.force else self.EFFICIENT_CODEC

            encoder = CustomEncoding(
                media_file,
                delete_original=True,
                verify=self.verify,
                delete_threshold=0,
                check_size=True,
                denoise=self.denoise,
                fast_decode=self.fast_decode,
                tune=self.tune,
                ignore_codec=ignore_codec,
                debug=self.debug,
            )

            start_time = time.time()
            status = encoder.encode_wrapper()

            if status == EncodingStatus.SUCCESS:
                encoded_size = os.path.getsize(encoder.new_file_path)
                self.logger.debug(encoder.new_file_path)

                self.success_encodings.add(media_file.file_path)
                if os.path.isfile(media_file.file_path):
                    self.total_encoded_size += os.path.getsize(media_file.file_path)
                    self.total_original_size += original_size

            elif status == EncodingStatus.SKIPPED:
                log = f"⏭️ Skipping encoding: {media_file.file_path} (Already in desired format)."
                self.skipped_videos[media_file.file_path] = log

            elif (
                status == EncodingStatus.FAILED
            ):  # the encoded file will be automatically removed
                self.failed_encodings.add(media_file.file_path)
                self.logger.warning(f"❌ Encoding failed for {media_file.file_path}.")
            elif status == EncodingStatus.LOWQUALITY:
                self.logger.warning(
                    f"❌ The encoded video {color_text(media_file.file_name, dim=True)} has been deleted."
                )
                encoder._delete_encoded()
                pass
            elif status == EncodingStatus.LARGESIZE:
                size_log = "(Unknown size change)"
                if os.path.isfile(encoder.output_tmp_file):
                    encoded_size = os.path.getsize(encoder.output_tmp_file)
                    size_log = (
                        CustomEncoding.human_readable_size(original_size)
                        + " → "
                        + CustomEncoding.human_readable_size(encoded_size)
                    )
                    encoder._delete_encoded()

                log = f"❌ Encoding skipped for {media_file.file_path} due to large size {color_text(size_log, 'magenta')}. The encoded video has been deleted."
                self.skipped_videos[media_file.file_path] = log
                self.logger.warning(log)

            self.logger.info(f"🕐 Encoding took {color_text(self.format_time(time.time()-start_time), 'magenta')}")

            self.save_state()  # Save state in case of failure

        # Calculate final average reduction
        if len(self.success_encodings) > 0 and self.total_original_size > 0:
            final_avg_reduction = 100 * (
                1 - (self.total_encoded_size / self.total_original_size)
            )
        else:
            final_avg_reduction = 0

        total_time_seconds = time.time() - self.start_time

        self.log_final_results()

        self.logger.info(
            color_text("\n" + "-" * 50 + "\n", dim=True)
            + f"📊 All tasks finished for directory {color_text(self.directory, 'cyan')}\n"
            "✅ Successful: "
            f"{color_text(str(len(self.success_encodings)), 'cyan', bold=True)}, "
            "❌ Failed: "
            f"{color_text(str(len(self.failed_encodings)), 'red', bold=True)}, "
            "⏭️ Skipped: "
            f"{color_text(str(len(self.skipped_videos)), 'yellow', bold=True)}.\n"
            "📉 Final average size reduction: "
            f"{color_text(f'{final_avg_reduction:.2f}%', 'magenta')}.\n"
            "💾 Total disk space saved: "
            f"{color_text(CustomEncoding.human_readable_size(self.total_original_size - self.total_encoded_size), 'magenta', bold=True)}.\n"
            "⌛ Time taken current pass: "
            f"{color_text(self.format_time(total_time_seconds), 'blue', bold=True)}"
        )

    def save_state(self):
        """Save the current encoding state to a file."""
        state = {
            "directory": self.directory,
            "success_encodings": self.success_encodings,
            "failed_encodings": self.failed_encodings,
            "skipped_videos": self.skipped_videos,
            "video_queue": self.video_queue,
            "min_size": self.min_size,
            "min_resolution": self.min_resolution,
            "total_original_size": self.total_original_size,
            "total_encoded_size": self.total_encoded_size,
        }
        try:
            with open(self.state_file, "wb") as f:
                pickle.dump(state, f)
            self.logger.debug("State saved successfully.")
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")

    def load_state(self) -> bool:
        """Load the previous encoding state if available, reset if directory has changed."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "rb") as f:
                    state = pickle.load(f)

                if state.get("directory") == self.directory:
                    self.success_encodings = state.get("success_encodings", set())
                    self.failed_encodings = state.get("failed_encodings", set())
                    self.skipped_videos = state.get("skipped_videos", {})
                    self.video_queue = state.get("video_queue", [])

                    min_size = state.get("min_size", DEFAULT_MIN_SIZE)
                    min_resolution = state.get("min_resolution", None)

                    self.total_original_size = state.get("total_original_size", 0)
                    self.total_encoded_size = state.get("total_encoded_size", 0)

                    if len(self.video_queue) < 1:
                        self.logger.info(
                            f"Previous encoding has finished or hasn't started. Restarting for {color_text(self.directory, dim=True)}."
                        )
                        return False
                    elif (
                        min_size != self.min_size
                        or min_resolution != self.min_resolution
                    ):
                        self.logger.info(
                            "Current encoding session has different parameters than saved encoding session.\n"
                            f"  - min_size:       got {color_text(min_size, 'cyan', bold=True)}, passed {color_text(self.min_size, 'magenta')}\n"
                            f"  - min_resolution: got {color_text(min_resolution, 'cyan', bold=True)}, passed {color_text(self.min_resolution, 'magenta')}\n"
                            f"Restarting for: {color_text(self.directory, dim=True)}"
                        )
                        return False

                    self.logger.info(f"Resumed encoding session for {color_text(self.directory, dim=True)}.")
                    return True
                else:
                    self.logger.warning(
                        f"Directory has changed from {color_text(state.get('directory'), 'cyan', dim=True)} to {color_text(self.directory, 'magenta', bold=True)}. Resetting state."
                    )
            except Exception as e:
                self.logger.error(f"Failed to load state")
                self.logger.exception(e)
        else:
            self.logger.info(
                f"No previous encoding session found for {self.directory}."
            )
        return False

    def reset_state(self):
        """Reset the encoding state if the directory has changed."""
        self.success_encodings.clear()
        self.failed_encodings.clear()
        self.skipped_videos.clear()
        self.video_queue.clear()

        self.total_original_size = 0
        self.total_encoded_size = 0

        self.save_state()  # Save the reset state
        open(self.log_file, "w").close()  # Clear file
        self.logger.info("Encoding state reset.")

    @staticmethod
    def parse_size(size: Union[str, float]) -> int:
        """
        Convert human-readable file sizes (e.g., "1GB", "500MB", "200KB") into bytes.

        :param size: File size in human-readable format (string) or numeric bytes (float).
        :return: Size in bytes (int).
        """
        if isinstance(size, (int, float)):  # If already in bytes
            return int(size)

        size = size.strip().lower()
        size_map = {"kb": 1_024, "mb": 1_048_576, "gb": 1_073_741_824, "b": 1}

        match = re.match(r"([\d\.]+)\s*([kmgt]?b)", size)
        if match:
            value, unit = match.groups()
            return int(float(value) * size_map.get(unit, 1))

        raise ValueError(f"Invalid size format: {size}")

    def log_final_results(self):
        """Log the final encoding summary including success, failure, skipped videos,
        total processed, average size reduction, and total encoding time."""

        self.logger.info(color_text("==== Encoding Process Detail ====", dim=True))

        total_processed = (
            len(self.success_encodings)
            + len(self.failed_encodings)
            + len(self.skipped_videos)
        )

        # ✅ Log total processed files
        self.logger.info(
            f"Total Processed Videos: {color_text(str(total_processed), 'blue', bold=True)}"
        )

        # ✅ Log successfully encoded videos
        if self.success_encodings:
            self.logger.info(
                f"✅ Successfully Encoded: {color_text(str(len(self.success_encodings)), 'cyan', bold=True)} videos."
            )
        else:
            self.logger.info(
                color_text(
                    "❌ No videos were successfully encoded.",
                )
            )

        # ✅ Log skipped videos with reasons
        if self.skipped_videos:
            self.logger.info(
                f"⏭️ Skipped: {color_text(str(len(self.skipped_videos)), 'yellow', bold=True)} videos:"
            )
            for file_path, reason in self.skipped_videos.items():
                self.logger.info(
                    f"  - {color_text(file_path, dim=True)} | Reason: {color_text(reason, 'reset', dim=True)}"
                )
        else:
            self.logger.info(
                color_text(
                    "⏭️ No videos were skipped.",
                )
            )

        # ✅ Log failed encodings
        if self.failed_encodings:
            self.logger.info(
                f"❌ Failed: {color_text(str(len(self.failed_encodings)), 'red', bold=True)} encodings:"
            )
            for file_path in self.failed_encodings:
                self.logger.warning(f"  - {color_text(file_path, 'yellow', dim=True)}")
        else:
            self.logger.info(color_text("✅ No failed encodings.", dim=True))

        self.logger.info(color_text("====================================", dim=True))

    @staticmethod
    def format_time(seconds: float) -> str:
        """Convert seconds into a human-readable format including weeks, days, hours, minutes, and seconds."""
        weeks, remainder = divmod(seconds, 604800)  # 604800 seconds in a week
        days, remainder = divmod(remainder, 86400)  # 86400 seconds in a day
        hours, remainder = divmod(remainder, 3600)  # 3600 seconds in an hour
        minutes, seconds = divmod(remainder, 60)  # 60 seconds in a minute

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


if __name__ == "__main__":
    args = parse_arguments()

    if not os.path.isdir(args.directory):
        print("Error: input argument not a directory.")
        sys.exit(1)

    CustomEncoding = get_custom_encoding_class(args.codec)

    if args.codec == "hevc":
        encoder = BatchEncoder(
            directory=args.directory,
            min_size=args.min_size,
            force_reset=args.force_reset,
            verify=args.verify,
            min_resolution=args.min_resolution,
            denoise=args.denoise,
            force=args.force,
            debug=args.debug,
        )
    else:
        encoder = BatchEncoder(
            directory=args.directory,
            min_size=args.min_size,
            force_reset=args.force_reset,
            denoise=args.denoise,
            verify=args.verify,
            min_resolution=args.min_resolution,
            fast_decode=args.fast_decode,
            tune=args.tune,
            force=args.force,
            debug=args.debug,
        )

    encoder.encode_videos()
