from encoder import *
from encoder.config import *
from encoder.utils.logger import setup_logger
from encoder.encoders.custom_encoder import get_custom_encoding_class
from typing import Union, List, Optional
import re
import os
import heapq
import pickle
import hashlib
import argparse
import sys
import time

VIDEO_EXTENSIONS = {
    ".mp4",  # MPEG-4 Part 14
    ".mkv",  # Matroska
    ".mov",  # QuickTime File Format
    ".avi",  # Audio Video Interleave
    ".flv",  # Flash Video
    ".webm", # WebM
    ".wmv",  # Windows Media Video
    ".mpg",  # MPEG-1
    ".mpeg", # MPEG-1
    ".m4v",  # MPEG-4 Video File
    ".3gp",  # 3GPP Multimedia File
    ".3g2",  # 3GPP2 Multimedia File
    ".ts",   # MPEG Transport Stream
    ".m2ts", # Blu-ray Disc Audio-Video (BDAV) MPEG-2 Transport Stream
    ".mts",  # AVCHD Video File
    ".vob",  # DVD Video Object
    ".ogv",  # Ogg Video
    ".rm",   # RealMedia
    ".rmvb", # RealMedia Variable Bitrate
    ".divx", # DivX-Encoded Movie File
    ".f4v",  # Flash MP4 Video File
    ".swf",  # Shockwave Flash Movie
    ".amv",  # Anime Music Video File
    ".asf",  # Advanced Systems Format
    ".mxf",  # Material Exchange Format
    ".dv",   # Digital Video File
    ".qt",   # QuickTime Movie
    ".yuv",  # YUV Video File
    ".mpe",  # MPEG Movie File
    ".mpv",  # MPEG Elementary Stream Video File
    ".m1v",  # MPEG-1 Video File
    ".m2v",  # MPEG-2 Video
    ".svi",  # Samsung Video File
    ".drc",  # Dirac Video File
    ".ivf",  # Indeo Video Format
    ".nsv",  # Nullsoft Streaming Video
    ".fli",  # FLIC Animation
    ".flc",  # FLIC Animation
    ".gxf",  # General eXchange Format
    ".mxf",  # Material Exchange Format
    ".roq",  # RoQ Video
    ".smi",  # Synchronized Multimedia Integration Language
    ".smil", # Synchronized Multimedia Integration Language
    ".wm",   # Windows Media Video
    ".wtv"   # Windows Recorded TV Show
}

DEFAULT_MIN_SIZE = "100MB"
DEFAULT_DENOISE = "none"
DEFAULT_CODEC = 'hevc'
DEFAULT_FAST_DECODE = 1
DEFAULT_TUNE = 0

def parse_arguments():
    parser = argparse.ArgumentParser(description="Batch video encoding script.")
    parser.add_argument("directory", help="Directory containing videos to encode.")
    parser.add_argument("--min-size", default=DEFAULT_MIN_SIZE, help=f"Minimum file size to encode (e.g., '500MB', '1GB'). Default is '{DEFAULT_MIN_SIZE}'")
    parser.add_argument(
        "--codec",
        choices=["hevc", "av1"],
        default=DEFAULT_CODEC,
        help=f"Select the codec to use for encoding. Options: 'hevc' (H.265) or 'av1'. Default is '{DEFAULT_CODEC}'."
    )
    parser.add_argument("--force-reset", action="store_true", help="Reset encoding state before starting.")
    
    parser.add_argument(
        "--denoise",
        choices=["light", "mild", "moderate", "heavy"],
        help="Apply denoising filter. Options: 'none', 'light', 'mild', 'moderate', 'heavy'. If omitted, no denoising will be applied."
    )


    parser.add_argument(
        "--fast-decode", 
        type=int, 
        choices=[0, 1, 2], 
        default=DEFAULT_SVTAV1_FAST_DECODE, 
        help="Optimize for decoding speed (0-3). Applies only to AV1 encoding."
    )

    parser.add_argument(
        "--tune", 
        type=int, 
        choices=[0, 1, 2], 
        default=DEFAULT_SVTAV1_TUNE, 
        help=(
            "Specifies the tuning metric for encoding quality:\n"
            "  0 = VQ  (Visual Quality): Prioritizes subjective visual quality, making the video look more natural.\n"
            "  1 = PSNR (Peak Signal-to-Noise Ratio): Optimizes for numerical accuracy, useful for technical evaluations.\n"
            "  2 = SSIM (Structural Similarity Index): Preserves structural details for better perceptual quality.\n"
            "Default is VQ (0), which is best for general use."
        )
    )

    parser.add_argument(
        "--verify", 
        action="store_true", 
        help=(
            "Verify the encoded file quality using VMAF before deleting the original video.\n"
            "If enabled, the script will calculate a VMAF score for every file\n"
            "Only use this flag during testing, as it is very time consuming."
        )
    )

    parser.add_argument(
        "--min-resolution",
        choices=["4k", "2k", "1080p", "720p", "480p", "360p"],
        help="Minimum resolution threshold for encoding. Videos below this resolution will be skipped."
    )

    return parser.parse_args()



class BatchEncoder:
    """Handles batch encoding of videos in a directory to AV1 format with resume support."""

    STATE_FILE_PREFIX = "encoder_state"
    LOG_FILE_PREFIX = "batch_encoding"
    
    def __init__(self, directory: str, min_size: Union[str, float] = DEFAULT_MIN_SIZE, 
                 verify:bool=False, force_reset:bool=False, denoise:str=None,
                 fast_decode:int=DEFAULT_FAST_DECODE, tune:int=DEFAULT_TUNE, min_resolution:Optional[str]=None):
        if not os.path.isdir(directory):
            raise ValueError(f"The input to {self.__class__.__name__} must be a directory")
        self.directory = directory
        self.min_size = min_size
        self.min_size_bytes = self.parse_size(min_size)
        self.dir_hash = self.hash_directory(directory)  # Generate hash for directory\
        self.log_file = os.path.join(LOG_DIR, f"{self.LOG_FILE_PREFIX}_{self.dir_hash}.log")
        self.state_file = os.path.join(LOG_DIR, f"{self.STATE_FILE_PREFIX}_{self.dir_hash}.pkl")

        self.denoise = denoise
        self.verify = verify
        self.fast_decode = str(fast_decode)
        self.tune = str(tune)
        self.min_resolution = min_resolution
        
        self.video_queue = []
        self.success_encodings = set()  # Stores successfully encoded videos
        self.failed_encodings = set()  # Stores videos that failed encoding
        self.skipped_videos = {}  # Stores videos that were skipped and their reason

        self.encoded_video_count = 0
        self.total_original_size = 0
        self.total_encoded_size = 0

        # Set up the logger
        self.logger = setup_logger(self.__class__.__name__, self.log_file)
        self.logger.info(f"Initializing BatchEncoder for directory: {directory}")

        # Load previous state if applicable
        if not force_reset and self.load_state():
            self.logger.info(f"Resuming previous encoding session for {directory}.")
        else:
            self.reset_state()
            self.prepare_video_queue()

        self.save_state()

        self.initial_queue_size = len(self.video_queue) # record the total queue size at the beginning
        self.start_time = time.time()

    @staticmethod
    def hash_directory(directory: str) -> str:
        """Generate a short hash for the directory path."""
        return hashlib.md5(directory.encode()).hexdigest()[:8]  # Short hash

    def get_video_files(self) -> List[str]:
        """Retrieve all video files under the directory and its subdirectories."""
        video_files = []
        for root, _, files in os.walk(self.directory):
            for file in files:
                if any(file.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
                    video_files.append(os.path.join(root, file))
                    self.logger.debug(f"Found video {file}")
        return video_files

    def prepare_video_queue(self):
        """Find and prioritize videos in the directory, excluding already encoded ones."""
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

                media_file = MediaFile(file)

                if self.min_resolution is not None:
                    """Set to True if all video streams are below the resolution threshold, otherwise False."""
                    skip_resolution = all(
                        video_stream.width and video_stream.height and 
                        (video_stream.width * video_stream.height < RESOLUTION.get(self.min_resolution, 0))
                        for video_stream in media_file.video_info
                    )

                    if skip_resolution:
                        log = (f"Skipping {file} "
                            f"- All video streams are below threshold of {self.min_resolution}.")
                        self.logger.debug(log)
                        self.skipped_videos[file] = log
                        continue


                temp_queue.append((-file_size, media_file.file_path, media_file))  # Max heap (largest size first)
            except ValueError:
                self.logger.warning(f"Skipping {file}, not a valid video.")
            except Exception as e:
                self.logger.error(f"Error processing {file}: {e}")

        heapq.heapify(temp_queue)  # More efficient than pushing one by one
        self.video_queue = temp_queue
        self.logger.info(f"Prepared {len(self.video_queue)} videos for encoding.")
    
    
    
    def encode_videos(self):
        """Encode videos from the priority queue."""
        while self.video_queue:
            neg_file_size, _, media_file = heapq.heappop(self.video_queue)
            
            original_size = -neg_file_size
            self.logger.info(f"🎥 Encoding {media_file.file_path} of size {CustomEncoding.human_readable_size(original_size)}, {self.initial_queue_size - len(self.video_queue)}/{self.initial_queue_size} videos left in the queue")
            
            encoder = CustomEncoding(media_file, delete_original=True, verify=self.verify, 
                                     delete_threshold=0, check_size=True,
                                     denoise=self.denoise, fast_decode=self.fast_decode,
                                     tune=self.tune)
            status = encoder.encode_wrapper()
            
            if status == EncodingStatus.SUCCESS or status == EncodingStatus.LOWQUALITY:
                encoded_size = os.path.getsize(encoder.new_file_path)
                self.logger.info(encoder.new_file_path)

                # log for size reduction
                self.total_original_size += original_size
                self.total_encoded_size += encoded_size
                self.encoded_video_count += 1
                size_reduction = 100 * (1 - (encoded_size / original_size))

                self.success_encodings.add(media_file.file_path)

                self.logger.info(f"✅ Encoding completed: {media_file.file_name} ({CustomEncoding.human_readable_size(original_size)} → {CustomEncoding.human_readable_size(encoded_size)}, Reduction: {size_reduction:.2f}%)")

            elif status == EncodingStatus.SKIPPED:
                log = f"⏭️ Skipping encoding: {media_file.file_path} (Already in desired format)."
                self.skipped_videos[media_file.file_path] = log
                self.logger.info(log)

            elif status == EncodingStatus.FAILED:
                self.failed_encodings.add(media_file.file_path)
                self.logger.warning(f"❌ Encoding failed for {media_file.file_path}.")
            elif status == EncodingStatus.LARGESIZE:
                log = f"❌ Encoding skipped for {media_file.file_path} due to large size. The encoded video has been deleted."
                self.skipped_videos[media_file.file_path] = log
                if os.path.isfile(encoder.output_tmp_file):
                    os.remove(encoder.output_tmp_file)
                self.logger.warning(log)
            
            self.save_state()  # Save state in case of failure
        
        # Calculate final average reduction
        if self.encoded_video_count > 0:
            final_avg_reduction = 100 * (1 - (self.total_encoded_size / self.total_original_size))
        else:
            final_avg_reduction = 0

        total_time_seconds = time.time() - self.start_time

        self.logger.info(
            "\n" + "-" * 50 + "\n"
            f"📊 All tasks finished. Final average size reduction: {final_avg_reduction:.2f}%. "
            f"✅ Successful: {len(self.success_encodings)}, "
            f"❌ Failed: {len(self.failed_encodings)}, "
            f"⏭️ Skipped: {len(self.skipped_videos)}, "
            f"💾 Total disk space saved: {CustomEncoding.human_readable_size(self.total_original_size - self.total_encoded_size)}."
            f"⌛ Time taken current pass: {self.format_time(total_time_seconds)}"
        )

        self.log_final_results()
        

    def save_state(self):
        """Save the current encoding state to a file."""
        state = {
            "directory": self.directory,
            "success_encodings": self.success_encodings,
            "failed_encodings": self.failed_encodings,
            "skipped_videos": self.skipped_videos,
            "video_queue": self.video_queue,
            'encoded_video_count' : self.encoded_video_count,
            'total_original_size' : self.total_original_size,
            'total_encoded_size' : self.total_encoded_size
        }
        try:
            with open(self.state_file, "wb") as f:
                pickle.dump(state, f)
            self.logger.info("State saved successfully.")
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

                    self.encoded_video_count = state.get("encoded_video_count", 0)
                    self.total_original_size = state.get("total_original_size", 0)
                    self.total_encoded_size = state.get("total_encoded_size", 0)

                    if len(self.video_queue) <= 0:
                        self.logger.info(f"Previous encoding session has finished or not yet started. Restarting for {self.directory}.")
                        return False

                    self.logger.info(f"Resumed encoding session for {self.directory}.")
                    return True
                else:
                    self.logger.warning(f"Directory has changed from {state.get('directory')} to {self.directory}. Resetting state.")
            except Exception as e:
                self.logger.error(f"Failed to load state: {e}")
        else:
            self.logger.info(f"No previous encoding session found for {self.directory}.")
        return False

    def reset_state(self):
        """Reset the encoding state if the directory has changed."""
        self.success_encodings.clear()
        self.failed_encodings.clear()
        self.skipped_videos.clear()
        self.video_queue.clear()

        self.encoded_video_count = 0
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

        self.logger.info("==== Encoding Process Detail ====")

        total_processed = len(self.success_encodings) + len(self.failed_encodings) + len(self.skipped_videos)
        
        # ✅ Log total processed files
        self.logger.info(f"Total Processed Videos: {total_processed}")

        # ✅ Log successfully encoded videos
        if self.success_encodings:
            self.logger.info(f"Successfully Encoded {len(self.success_encodings)} Videos.")
        else:
            self.logger.info("No videos were successfully encoded.")

        # ✅ Log skipped videos with reasons
        if self.skipped_videos:
            self.logger.info(f"Skipped {len(self.skipped_videos)} Videos:")
            for file_path, reason in self.skipped_videos.items():
                self.logger.info(f"  - {file_path} | Reason: {reason}")
        else:
            self.logger.info("No videos were skipped.")

        # ✅ Log failed encodings
        if self.failed_encodings:
            self.logger.info(f"Failed {len(self.failed_encodings)} Encodings:")
            for file_path in self.failed_encodings:
                self.logger.info(f"  - {file_path}")
        else:
            self.logger.info("No failed encodings.")

        self.logger.info("====================================")

    @staticmethod
    def format_time(seconds: float) -> str:
        """Convert seconds into a human-readable format including weeks, days, hours, minutes, and seconds."""
        weeks, remainder = divmod(seconds, 604800)  # 604800 seconds in a week
        days, remainder = divmod(remainder, 86400)  # 86400 seconds in a day
        hours, remainder = divmod(remainder, 3600)  # 3600 seconds in an hour
        minutes, seconds = divmod(remainder, 60)    # 60 seconds in a minute

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
    if not check_ffmpeg_installed():
        print("Error: ffmpeg not installed.")
        sys.exit(1)

    args = parse_arguments()

    if not os.path.isdir(args.directory):
        print("Error: input argument not a directory.")
        sys.exit(1)

    CustomEncoding = get_custom_encoding_class(args.codec)

    if args.codec == 'hevc':
        encoder = BatchEncoder(directory=args.directory, min_size=args.min_size, 
                               force_reset=args.force_reset, verify=args.verify,
                               min_resolution=args.min_resolution, denoise=args.denoise)
    else:
        encoder = BatchEncoder(directory=args.directory, min_size=args.min_size, 
                               force_reset=args.force_reset, denoise=args.denoise, 
                               verify=args.verify, min_resolution=args.min_resolution,
                               fast_decode=args.fast_decode, tune=args.tune)

    encoder.encode_videos()