import os
import subprocess
import json
import sys
import argparse
from typing import List, Tuple, Optional
from enum import Enum
from logger_util import setup_logger
import signal

class EncodingStatus(Enum):
    SKIPPED = "skipped"
    SUCCESS = "success"
    FAILED = "failed"

def check_ffmpeg_installed():
    """Check if FFmpeg is installed and accessible."""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: FFmpeg is not installed or not found in the system path.", file=sys.stderr)
        sys.exit(1)

def parse_arguments():
    """
    Parses command-line arguments using argparse.

    This function sets up command-line options to control video encoding 
    for HEVC (H.265) and AV1 using FFmpeg.

    Available options:
    - Input file path
    - Codec selection (HEVC or AV1)
    - CRF (Constant Rate Factor) value for quality control
    - Preset for encoding speed vs efficiency
    - CPU usage tuning (only for AV1)
    - Option to delete the original video after encoding
    - Output directory selection
    """
    parser = argparse.ArgumentParser(
        description="Convert video to HEVC (H.265) or AV1 using FFmpeg."
    )

    # Required argument: input video file
    parser.add_argument(
        "input_file", 
        help="Path to the input video file that needs to be encoded."
    )

    # Optional argument: Codec selection (default: HEVC)
    parser.add_argument(
        "--codec", 
        choices=["hevc", "av1"], 
        default="hevc", 
        help=(
            "Specify the codec to use for encoding.\n"
            "Options:\n"
            "  hevc - High Efficiency Video Coding (H.265) [default]\n"
            "  av1  - AV1 codec for better compression at lower bitrates\n"
            "Note: AV1 encoding is significantly slower than HEVC."
        )
    )

    # Optional argument: CRF (Constant Rate Factor) for quality control
    parser.add_argument(
        "--crf", 
        type=int, 
        help=(
            "Set the CRF (Constant Rate Factor) value for controlling video quality.\n"
            "Lower values give better quality but larger file sizes.\n"
            "Typical ranges:\n"
            "  HEVC: 0-51 (default: 24, good quality: 18-28)\n"
            "  AV1:  0-63 (default: 28, good quality: 20-35)\n"
            "Note: 0 means lossless, but file size will be huge."
        )
    )

    # Optional argument: Encoding preset for speed vs compression efficiency
    parser.add_argument(
        "--preset", 
        help=(
            "Set the encoding speed preset.\n"
            "Faster presets encode quickly but result in larger file sizes.\n"
            "Slower presets optimize compression for better quality at the same bitrate.\n"
            "Defaults:\n"
            "  HEVC: slow (use medium, slow, slower, veryslow, etc.)\n"
            "  AV1:  slow (use veryslow, slow, medium, fast, etc.)\n"
        )
    )

    # Optional argument: CPU usage tuning for AV1 encoding
    parser.add_argument(
        "--cpu-used", 
        type=int, 
        help=(
            "Set the AV1 encoder CPU usage level (only applies to AV1 encoding).\n"
            "Higher values result in faster encoding but worse compression efficiency.\n"
            "Typical range: 0-8 (default: 4)\n"
            "  0  - Best compression, extremely slow encoding\n"
            "  4  - Balanced (default)\n"
            "  8  - Fastest, least efficient compression"
        )
    )

    # Optional flag: Delete original file after encoding
    parser.add_argument(
        "--delete-video", 
        action="store_true", 
        help=(
            "Delete the original video file after encoding.\n"
            "Warning: This action is irreversible."
        )
    )

    # Optional argument: Output directory for the encoded file
    parser.add_argument(
        "--output-path", 
        help=(
            "Specify the directory to save the encoded video.\n"
            "If not provided, the output will be saved in the same directory as the input file."
        )
    )

    return parser.parse_args()


class MediaFile:
    """Handles media metadata extraction using ffprobe."""

    def __init__(self, file_path: str):
        self.logger = setup_logger("MediaFile", "logs/media_file.log")
        self.file_path: str = file_path
        
        self.logger.debug(f"🔍 Initializing MediaFile for: {file_path}")

        if not self.is_valid_video():
            self.logger.error(f"❌ Invalid video file: {file_path}")
            raise ValueError("The provided file does not contain a valid video stream.")
        
        self.video_codec, self.tag_string = self.get_video_codec_and_tag()
        self.audio_streams = self.get_audio_info()

    def get_audio_info(self) -> List[Tuple[int, str, Optional[str]]]:
        """Retrieve all audio streams' codec and bit rate."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
            "stream=index,codec_name,bit_rate", "-of", "json", self.file_path
        ]
        self.logger.debug(f"🎵 Running ffprobe for audio info: {cmd}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            audio_streams = [
                (stream.get("index", 0), stream.get("codec_name", ""), stream.get("bit_rate", None))
                for stream in info.get("streams", [])
            ]

            self.logger.debug(f"🎵 Found {len(audio_streams)} audio streams in {self.file_path}")
            return audio_streams

        except subprocess.CalledProcessError as e:
            self.logger.error(f"⚠️ ffprobe error retrieving audio info for {self.file_path}: {e}")
        except json.JSONDecodeError:
            self.logger.error(f"⚠️ Failed to parse ffprobe output for audio streams in {self.file_path}")

        return []  # Return an empty list if audio info cannot be retrieved

    def get_video_codec_and_tag(self) -> Tuple[Optional[str], Optional[str]]:
        """Retrieve video codec and tag from the video file."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=codec_name,tag_string", "-of", "json", self.file_path
        ]
        self.logger.debug(f"📺 Running ffprobe for video codec and tag: {cmd}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)

            if "streams" in info and info["streams"]:
                codec = info["streams"][0].get("codec_name", "unknown")
                tag = info["streams"][0].get("tag_string", "unknown")
                self.logger.debug(f"📺 Video codec: {codec}, Tag: {tag} for {self.file_path}")
                return codec, tag

            self.logger.warning(f"⚠️ No video codec found for {self.file_path}")

        except subprocess.CalledProcessError as e:
            self.logger.error(f"⚠️ ffprobe error retrieving video codec info for {self.file_path}: {e}")
        except json.JSONDecodeError:
            self.logger.error(f"⚠️ Failed to parse ffprobe output for video codec in {self.file_path}")

        return "unknown", "unknown"  # Return "unknown" instead of None to prevent errors

    def is_valid_video(self) -> bool:
        """Check if the file contains at least one video stream."""
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", self.file_path
        ]
        self.logger.debug(f"🛠️ Running ffprobe to check video validity: {cmd}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            stream_types = [stream["codec_type"] for stream in json.loads(result.stdout).get("streams", [])]

            if "video" in stream_types:
                self.logger.debug(f"✅ Valid video file detected: {self.file_path}")
                return True
            else:
                self.logger.warning(f"❌ No video stream found in {self.file_path}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"⚠️ ffprobe failed for {self.file_path}: {e}")
        except json.JSONDecodeError:
            self.logger.error(f"⚠️ Failed to parse ffprobe output when checking validity for {self.file_path}")

        return False  # Return False if any error occurs

    def get_video_resolution(self) -> Tuple[int, int]:
        """Retrieve the resolution (width, height) of the video."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height", "-of", "json", self.file_path
        ]
        self.logger.debug(f"📏 Running ffprobe for video resolution: {cmd}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            width = info.get("streams", [{}])[0].get("width", 1920)  # Default to 1920
            height = info.get("streams", [{}])[0].get("height", 1080)  # Default to 1080

            if width and height:
                self.logger.debug(f"📏 Resolution: {width}x{height} for {self.file_path}")
            else:
                self.logger.warning(f"⚠️ Resolution not found for {self.file_path}, defaulting to 1920x1080")

            return width, height

        except subprocess.CalledProcessError as e:
            self.logger.error(f"⚠️ ffprobe error retrieving resolution for {self.file_path}: {e}")
        except json.JSONDecodeError:
            self.logger.error(f"⚠️ Failed to parse ffprobe output for resolution in {self.file_path}")

        return (1920, 1080)  # Return default resolution if any error occurs


class Encoding:
    """Base class for video encoding."""


    RESOLUTION = {
        "4k": 3840 * 2160,
        "1080p": 1920 * 1080,
        "720p": 1280 * 720,
        "480p": 854 * 480  # Approximate for SD
    }

    def __init__(self, media_file: MediaFile, codec: str, preset: str, crf: int, delete_original: bool, output_dir: Optional[str] = None):
        self.logger = setup_logger("Encoding", "logs/encoding.log")
        self.media_file = media_file
        self.codec = codec
        self.preset = preset
        self.crf = crf
        self.delete_original = delete_original
        self.output_dir = output_dir or os.path.dirname(media_file.file_path)

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

        self.output_tmp_file = self.generate_output_filename()
        self.new_file_path = self.get_new_file_path()
        self.logger.debug(f"🎬 Encoding initialized for {self.media_file.file_path}")

    def get_new_file_path(self) -> str:
        """
        Generate a unique file path by checking if the file already exists.
        If the file exists, append a number suffix until a unique name is found.
        
        Example:
            - "video.mp4"  → (exists) → "video_1.mp4"
            - "video_1.mp4" → (exists) → "video_2.mp4"
        """
        base_name, _ = os.path.splitext(self.media_file.file_path)
        new_file_name = f"{base_name}.mp4"
        
        counter = 1
        while os.path.exists(new_file_name):
            new_file_name = f"{base_name}_{counter}.mp4"  # Append suffix before extension
            counter += 1

        return new_file_name
    
    def get_readable_resolution(self, media_file:MediaFile, tolerance = 0.05):
        width, height = media_file.get_video_resolution()
        pixel_count = width * height
        
        
        for res, standard_pixels in self.RESOLUTION.items():
            if abs(pixel_count - standard_pixels) <= standard_pixels * tolerance or pixel_count >= standard_pixels:
                resolution = res
                break
        else:
            resolution = "480p"  # If it doesn’t fit any category
        return resolution

    def generate_output_filename(self) -> str:
        """Generate a unique output filename based on encoding parameters."""
        base_name = os.path.splitext(os.path.basename(self.media_file.file_path))[0]

        # Get the suffix from the subclass
        suffix = self._get_filename_suffix()
        
        output_filename = os.path.join(self.output_dir, f"{base_name}{suffix}.mp4")

        # Ensure the filename is unique
        counter = 1
        while os.path.exists(output_filename):
            output_filename = os.path.join(self.output_dir, f"{base_name}{suffix}_{counter}.mp4")
            counter += 1

        self.logger.debug(f"📂 Generated output filename: {output_filename}")
        return output_filename

    def _get_filename_suffix(self) -> str:
        """This method should be overridden by subclasses to define the filename format."""
        raise NotImplementedError("Subclasses must implement _get_filename_suffix()")

    def prepare_cmd(self) -> List[str]:
        raise NotImplementedError("This method should be implemented in child classes.")

    def prepare_audio_args(self) -> List[str]:
        """Prepare audio conversion arguments."""
        compatible_codecs = {"aac", "mp3", "ac3"}
        audio_args = []

        for index, codec, bit_rate in self.media_file.audio_streams:
            if codec in compatible_codecs:
                audio_args.extend(["-c:a:{0}".format(index), "copy"])
            else:
                target_bitrate = f"{bit_rate}k" if bit_rate else "128k"
                audio_args.extend(["-c:a:{0}".format(index), "aac", "-b:a:{0}".format(index), target_bitrate])
        
        self.logger.debug(f"🎵 Prepared audio arguments: {audio_args}")
        return audio_args

    def delete_original_file(self):
        """Delete the original file after encoding, if required."""
        if self.delete_original:
            try:
                new_file_name = self.new_file_path
                
                os.remove(self.media_file.file_path)
                os.rename(self.output_tmp_file, new_file_name)
                self.logger.info(f"🗑️ Deleted original file: {self.media_file.file_path}")
            except OSError as e:
                self.logger.error(f"❌ Failed to delete original file: {e}")

    def _encode(self) -> EncodingStatus:
        ffmpeg_cmd = self.prepare_cmd()
        if not ffmpeg_cmd:
            self.logger.warning(f"⚠️ Skipping encoding: {self.media_file.file_path} (Already in desired format).")
            return EncodingStatus.SKIPPED

        self.logger.debug(f"🎬 Starting encoding: {self.media_file.file_path}")
        result = subprocess.run(ffmpeg_cmd, check=True)
        self.delete_original_file()
        return EncodingStatus.SUCCESS

    def encode_wrapper(self) -> EncodingStatus:
        """Encodes the video and returns its status."""
        try:
            ret = self._encode()
            self.logger.debug(f"✅ Encoding successful: {self.media_file.file_path}")
            return ret
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else "Unknown FFmpeg error"
            self.logger.error(f"❌ Encoding failed for {self.media_file.file_path}: {error_msg}")
            if os.path.isfile(self.output_tmp_file):
                os.remove(self.output_tmp_file)
            return EncodingStatus.FAILED

        except FileNotFoundError:
            self.logger.error(f"❌ FFmpeg not found. Make sure it is installed and accessible.")
            return EncodingStatus.FAILED

        except KeyboardInterrupt:
            self.logger.warning(f"🔴 Encoding interrupted manually (Ctrl+C). Cleaning up temp files {self.output_tmp_file}...")
            if os.path.isfile(self.output_tmp_file):
                os.remove(self.output_tmp_file)
            sys.exit(1)
            return EncodingStatus.FAILED

        except Exception as e:
            self.logger.error(f"❌ Unexpected error during encoding of {self.media_file.file_path}: {e}")
            return EncodingStatus.FAILED

class HevcEncoding(Encoding):
    """Handles HEVC (H.265) encoding with resolution-based parameter selection."""

    DEFAULT_PRESET = {
        "4k": "slow",
        "1080p": "slow",
        "720p": "slow",
        "480p": "medium"  # Change: Use medium for 480p for better speed
    }

    DEFAULT_CRF = {
        "4k": 22,
        "1080p": 24,
        "720p": 26,
        "480p": 28
    }

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 delete_original: bool = False, output_dir: Optional[str] = None):
        self.resolution = self.get_readable_resolution(media_file)
        selected_crf = crf if crf is not None else self.DEFAULT_CRF[self.resolution]
        selected_preset = preset if preset is not None else self.DEFAULT_PRESET[self.resolution]

        super().__init__(media_file, codec="libx265", preset=selected_preset, crf=selected_crf,
                         delete_original=delete_original, output_dir=output_dir)
        
        self.logger.info(f"🔹 HEVC encoding initialized for {media_file.file_path} | Preset: {selected_preset} | CRF: {selected_crf}")

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for HEVC encoding."""
        return f"_hevc_preset-{self.preset}_crf-{self.crf}"
    
    def prepare_cmd(self) -> List[str]:
        """Prepare FFmpeg command for HEVC encoding."""
        try:
            if self.media_file.video_codec == "hevc":
                if self.media_file.tag_string == "hev1":
                    self.logger.info(f"🔄 Remuxing '{self.media_file.file_path}' from hev1 to hvc1 (no re-encoding).")
                    
                    return [
                        "ffmpeg", "-y", "-i", self.media_file.file_path,
                        "-c:v", "copy", "-c:a", "copy", "-tag:v", "hvc1",
                        "-movflags", "+faststart",
                        self.output_tmp_file
                    ]
                else:
                    self.logger.warning(f"⚠️ Skipping HEVC encoding: {self.media_file.file_path} is already in the desired format.")
                    return None

            return [
                "ffmpeg", "-y", "-i", self.media_file.file_path, "-c:v", "libx265",
                "-preset", self.preset, "-tag:v", "hvc1", "-crf", str(self.crf),
                "-movflags", "+faststart"
            ] + self.prepare_audio_args() + [self.output_tmp_file]

        except Exception as e:
            self.logger.error(f"❌ Error preparing FFmpeg command: {e}")
            return None

class Av1Encoding(Encoding):
    """Handles AV1 encoding with resolution-based parameter selection."""

    DEFAULT_PRESET = {
        "4k": "slow",
        "1080p": "slow",
        "720p": "slow",
        "480p": "medium"  # Change: Use medium for 480p for better speed
    }

    # 8-10% quality loss
    DEFAULT_CRF = {
        "4k": 23,
        "2k": 25,
        "1080p": 26,
        "720p": 28,
        "480p": 32
    }

    DEFAULT_CPU_USED = {
        "4k": 4,
        "1080p": 5,
        "720p": 5,
        "480p": 6
    }

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 cpu_used: Optional[int] = None, delete_original: bool = False, output_dir: Optional[str] = None):
        self.resolution = self.get_readable_resolution(media_file)
        selected_cpu_used = cpu_used if cpu_used is not None else self.DEFAULT_CPU_USED[self.resolution]


        available_cpus = os.cpu_count()
        if selected_cpu_used > available_cpus:
            self.logger.warning(f"⚠️ Requested cpu-used={selected_cpu_used}, but only {available_cpus} CPUs available. Adjusting to {available_cpus}.")
            selected_cpu_used = available_cpus
        if selected_cpu_used > 8:
            selected_cpu_used = 8 # valid values for -cpu-used are from 0 to 8 inclusive.

        self.cpu_used = selected_cpu_used
        selected_crf = crf if crf is not None else self.DEFAULT_CRF[self.resolution]
        selected_preset = preset if preset is not None else self.DEFAULT_PRESET[self.resolution]

        super().__init__(media_file, codec="libaom-av1", preset=selected_preset, crf=selected_crf,
                         delete_original=delete_original, output_dir=output_dir)
        
        self.logger.info(f"🔹 AV1 encoding initialized for {media_file.file_path} | Preset: {selected_preset} | CRF: {selected_crf} | CPU: {selected_cpu_used}")

    @staticmethod
    def get_cpu_count():
        """Returns the available CPU count, ensuring a safe fallback."""
        cpu_count = os.cpu_count()
        if cpu_count is None or cpu_count < 1:
            return 1  # Default to at least 1 core if unknown
        return cpu_count

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for AV1 encoding, including CPU-used."""
        return f"_av1_preset-{self.preset}_crf-{self.crf}_cpu-{self.cpu_used}"
    
    def prepare_cmd(self) -> List[str]:
        if self.media_file.video_codec == "av1":
            print(f"⚠️ Skipping encoding: The input video '{self.media_file.file_path}' is already in AV1 format.")
            return None
        
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", self.media_file.file_path, "-c:v", "libaom-av1",
            "-preset", self.preset, "-cpu-used", str(self.cpu_used), "-row-mt", "1",
            "-crf", str(self.crf), "-b:v", "0", "-movflags", "+faststart"
        ] + self.prepare_audio_args() + [self.output_tmp_file]

        return ffmpeg_cmd

if __name__ == "__main__":
    check_ffmpeg_installed()
    args = parse_arguments()
    
    if not os.path.exists(args.input_file):
        print("Error: Input file does not exist.", file=sys.stderr)
        sys.exit(1)
    
    media = MediaFile(args.input_file)
    output_dir = args.output_path if args.output_path else os.path.dirname(args.input_file)
    
    if args.codec == "hevc":
        encoder = HevcEncoding(media, preset=args.preset, crf=args.crf, delete_original=args.delete_video, output_dir=output_dir)
    else:
        encoder = Av1Encoding(media, preset=args.preset, crf=args.crf, cpu_used=args.cpu_used, delete_original=args.delete_video, output_dir=output_dir)
    
    encoder.encode_wrapper()