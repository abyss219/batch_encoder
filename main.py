from encoding import check_ffmpeg_installed, EncodingStatus, MediaFile, Av1Encoding, HevcEncoding
from custom_encoding import get_custom_encoding_class
from logger_util import setup_logger
from typing import Union, List
import re
import os
import heapq
import pickle
import hashlib
import argparse

def parse_arguments():
    parser = argparse.ArgumentParser(description="Batch video encoding script.")
    parser.add_argument("directory", help="Directory containing videos to encode.")
    parser.add_argument("--min-size", default="500MB", help="Minimum file size to encode (e.g., '500MB', '1GB').")
    parser.add_argument(
        "--codec",
        choices=["hevc", "av1"],
        default="hevc",
        help="Select the codec to use for encoding. Options: 'hevc' (H.265) or 'av1'. Default is 'hevc'."
    )
    parser.add_argument("--force-reset", action="store_true", help="Reset encoding state before starting.")
    
    return parser.parse_args()



class BatchEncoder:
    """Handles batch encoding of videos in a directory to AV1 format with resume support."""


    LOG_DIRECOTRY = "logs"
    STATE_FILE_PREFIX = "encoder_state"
    LOG_FILE_PREFIX = "batch_encoder"
    
    def __init__(self, directory: str, min_size: Union[str, float] = "500MB", force_reset:bool=True):
        self.directory = directory
        self.min_size_bytes = self.parse_size(min_size)
        self.dir_hash = self.hash_directory(directory)  # Generate hash for directory\
        self.log_file = os.path.join(self.LOG_DIRECOTRY, f"{self.LOG_FILE_PREFIX}_{self.dir_hash}.log")
        self.state_file = os.path.join(self.LOG_DIRECOTRY, f"{self.STATE_FILE_PREFIX}_{self.dir_hash}.pkl")
        
        self.video_queue = []
        self.success_encodings = set()  # Stores successfully encoded videos
        self.failed_encodings = set()  # Stores videos that failed encoding
        self.skipped_videos = set()  # Stores videos that were skipped due to size limit

        # Set up the logger
        self.logger = setup_logger(f"BatchEncoder_{self.dir_hash}", self.log_file)
        self.logger.info(f"Initializing BatchEncoder for directory: {directory}")

        # Load previous state if applicable
        if not force_reset and self.load_state():
            self.logger.info(f"Resuming previous encoding session for {directory}.")
        else:
            self.reset_state()
            self.prepare_video_queue()

        self.save_state()

        self.initial_queue_size = len(self.video_queue)

        self.encoded_video_count = 0
        self.total_original_size = 0
        self.total_encoded_size = 0

    @staticmethod
    def hash_directory(directory: str) -> str:
        """Generate a short hash for the directory path."""
        return hashlib.md5(directory.encode()).hexdigest()[:8]  # Short hash

    def get_video_files(self) -> List[str]:
        """Retrieve all video files under the directory and its subdirectories."""
        video_extensions = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm"}
        video_files = []
        for root, _, files in os.walk(self.directory):
            for file in files:
                if any(file.lower().endswith(ext) for ext in video_extensions):
                    video_files.append(os.path.join(root, file))
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
                    self.logger.debug(f"Skipping {file} (Size: {self.human_readable_size(file_size)}) - Below threshold.")
                    self.skipped_videos.add(file)
                    continue

                media_file = MediaFile(file)
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
            self.logger.info(f"🎥 Encoding {media_file.file_path} of size {self.human_readable_size(original_size)}, {self.initial_queue_size - len(self.video_queue)}/{self.initial_queue_size} videos left in the queue")
            encoder = CustomEncoding(media_file, delete_original=True)
            status = encoder.encode_wrapper()
            
            if status == EncodingStatus.SUCCESS:
                encoded_size = os.path.getsize(encoder.new_file_path)
                
                # log for size reduction
                self.total_original_size += original_size
                self.total_encoded_size += encoded_size
                self.encoded_video_count += 1
                size_reduction = 100 * (1 - (encoded_size / original_size))

                self.success_encodings.add(media_file.file_path)

                self.logger.info(f"✅ Encoding completed: {media_file.file_path} ({self.human_readable_size(original_size)} → {self.human_readable_size(encoded_size)}, Reduction: {size_reduction:.2f}%)")

            elif status == EncodingStatus.SKIPPED:
                self.skipped_videos.add(media_file.file_path)
                self.logger.info(f"⏭️ Skipping encoding: {media_file.file_path} (Already in desired format).")

            elif status == EncodingStatus.FAILED:
                self.failed_encodings.add(media_file.file_path)
                self.logger.warning(f"❌ Encoding failed for {media_file.file_path}.")
            
            self.save_state()  # Save state in case of failure
        
        # Calculate final average reduction
        if self.encoded_video_count > 0:
            final_avg_reduction = 100 * (1 - (self.total_encoded_size / self.total_original_size))
        else:
            final_avg_reduction = 0

        self.logger.info(
            "\n" + "-" * 50 + "\n"
            f"📊 All tasks finished. Final average size reduction (current run only): {final_avg_reduction:.2f}%. "
            f"✅ Successful: {len(self.success_encodings)}, "
            f"❌ Failed: {len(self.failed_encodings)}, "
            f"⏭️ Skipped: {len(self.skipped_videos)}, "
            f"💾 Total disk space saved (current run only): {self.human_readable_size(self.total_original_size - self.total_encoded_size)}."
        )

    def save_state(self):
        """Save the current encoding state to a file."""
        state = {
            "directory": self.directory,
            "success_encodings": self.success_encodings,
            "failed_encodings": self.failed_encodings,
            "skipped_videos": self.skipped_videos,
            "video_queue": self.video_queue
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
                    self.skipped_videos = state.get("skipped_videos", set())
                    self.video_queue = state.get("video_queue", [])

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

    @staticmethod
    def human_readable_size(size_in_bytes):
        """Convert bytes into a human-readable format (GB, MB, KB) using binary (1024-based) system."""
        if size_in_bytes >= 1_073_741_824:  # 1024 ** 3
            return f"{size_in_bytes / 1_073_741_824:.2f} GB"
        elif size_in_bytes >= 1_048_576:  # 1024 ** 2
            return f"{size_in_bytes / 1_048_576:.2f} MB"
        elif size_in_bytes >= 1024:
            return f"{size_in_bytes / 1024:.2f} KB"
        else:
            return f"{size_in_bytes} B"


if __name__ == "__main__":
    check_ffmpeg_installed()
    args = parse_arguments()
    CustomEncoding = get_custom_encoding_class(args.codec)
    encoder = BatchEncoder(directory=args.directory, min_size=args.min_size, force_reset=args.force_reset)
    encoder.encode_videos()