import os
import subprocess
import json
import sys
import argparse
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum
from logger_util import setup_logger
import re
from dataclasses import dataclass, asdict
from operator import attrgetter

class EncodingStatus(Enum):
    SKIPPED = "skipped"
    SUCCESS = "success"
    FAILED = "failed"

RESOLUTION = {
    "4k": 3840 * 2160,
    "2k": 2560 * 1440,
    "1080p": 1920 * 1080,
    "720p": 1280 * 720,
    "480p": 640 * 480
}

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

@dataclass(frozen=True)
class VideoStream:
    index: Optional[int]
    ffmpeg_index: int
    codec: Optional[str]
    tag: Optional[str]
    width: Optional[int]
    height: Optional[int]
    frame_rate: Optional[float]
    duration: Optional[float]

    def get_readable_resolution(self, default="1080p", tolerance = 0.05):
        if self.height is None or self.width is None:
            return default

        pixel_count = self.width * self.height
        
        for res, standard_pixels in RESOLUTION.items():
            if abs(pixel_count - standard_pixels) <= standard_pixels * tolerance or pixel_count >= standard_pixels:
                resolution = res
                break
        else:
            resolution = default  # If it doesn’t fit any category
        return resolution
    
    def map_prefix(self, new_index:int):
        return ["-map", f"0:v:{self.ffmpeg_index}", f"-c:v:{new_index}"]

@dataclass(frozen=True)
class AudioStream:
    codec: Optional[str]
    ffmpeg_index: int
    index: Optional[int]
    bit_rate: Optional[int]
    sample_rate: Optional[int]

    def map_prefix(self, new_index:int):
        return ["-map", f"0:a:{self.ffmpeg_index}", f"-c:a:{new_index}"]

class MediaFile:
    """Handles media metadata extraction using ffprobe."""

    def __init__(self, file_path: str):
        self.logger = setup_logger("MediaFile", "logs/media_file.log")
        self.file_path: str = file_path
        
        self.logger.debug(f"🔍 Initializing MediaFile for: {file_path}")
        
        self.video_info = self.get_video_info()
        if not self.video_info:
            self.logger.error(f"❌ Invalid video file: {file_path}")
            raise ValueError("The provided file does not contain a valid video stream.")
        self.audio_info = self.get_audio_info()
        

    @property
    def num_video_stream(self):
        return len(self.video_info)
    
    @property
    def num_audio_stream(self):
        return len(self.audio_info)


    def get_video_info(self) -> List[VideoStream]:
        """Retrieve all video streams' codec, resolution, and frame rate in one ffprobe call. Returns None if an invalid stream is encountered."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
            "stream=codec_type,codec_name,tag_string,width,height,r_frame_rate,nb_frames,duration,index",
            "-of", "json", self.file_path
        ]


        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            video_streams = []
            
            index_counter = 0

            if "streams" in info:
                for stream in info["streams"]:
                    codec_type = stream.get("codec_type")
                    codec = stream.get("codec_name")
                    tag = stream.get("tag_string")
                    for key in ["index", "width", "height"]:
                        if stream.get(key) is not None:
                            try:
                                stream[key] = int(stream[key])
                            except ValueError:
                                stream[key] = None
                    
                    index = stream["index"] # only used to check if the video is valid
                    width = stream["width"]
                    height = stream["height"]

                    duration=stream.get("duration")

                    frame_rate_str = stream.get("r_frame_rate")
                    if frame_rate_str:
                        frame_match = re.match(r"(\d+)/(\d+)", frame_rate_str)
                        if frame_match:
                            numerator, denominator = int(frame_match.group(1)), int(frame_match.group(2))
                            frame_rate = 0 if denominator == 0 else numerator / denominator
                        else:
                            frame_rate = None

                    stm = VideoStream(
                        index=index, 
                        ffmpeg_index=index_counter, # ffmpeg uses 0 indexing fro both video and audio
                        codec=codec,
                        tag=tag,
                        width=width,
                        height=height,
                        frame_rate=frame_rate,
                        duration=duration
                    )


                    if (
                        codec_type != "video" or 
                        codec in {"png", "mjpeg", "bmp", "gif", "tiff", "jpegxl", "webp", "heif", "avif"} or 
                        # if frame_rate defined then frame_match must be defined
                        frame_rate and int(frame_match.group(2)) == int(frame_match.group(1)) or  # Detect single-frame video.
                        stream.get("nb_frames") == "1" or  # Explicitly check frame count
                        frame_rate == 0 or  # Invalid frame rate
                        index is None # invalid index
                    ):
                        self.logger.warning(f"❌ Invalid video stream detected: {asdict(stm)}")
                    else:
                        video_streams.append(stm)
                    
                    index_counter += 1
                        

            return video_streams  # Return empty list if no valid video streams are found
        
        except subprocess.CalledProcessError as e:
            print(f"⚠️ ffprobe error retrieving video info for {self.file_path}: {e}")
        except json.JSONDecodeError:
            print(f"⚠️ Failed to parse ffprobe output for video info in {self.file_path}")
        
        return []

    def get_audio_info(self) -> List[AudioStream]:
        """Retrieve all audio streams' codec and bit rate in one ffprobe call. Returns None if an invalid stream is encountered."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
            "stream=codec_type,codec_name,index,bit_rate,sample_rate",
            "-of", "json", self.file_path
        ]
        index_counter = 0
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            audio_streams = []
            
            if "streams" in info:
                for stream in info["streams"]:
                    if stream.get("codec_type") != "audio":
                        continue
                    
                    codec = stream.get("codec_name")

                    for key in ["index", "bit_rate", "sample_rate"]:
                        if stream.get(key) is not None:
                            try:
                                stream[key] = int(stream[key])
                            except ValueError:
                                stream[key] = None
                    index = stream.get("index")
                    bit_rate = stream.get("bit_rate")
                    sample_rate = stream.get("sample_rate")

                    if index:
                        audio_streams.append(
                            AudioStream(
                                codec=codec,
                                ffmpeg_index=index_counter, # use index counter to be compatible with ffmpeg
                                index=index_counter, 
                                bit_rate=bit_rate,
                                sample_rate=sample_rate
                            )
                        )
                    index_counter += 1
            
            return audio_streams
        
        except subprocess.CalledProcessError as e:
            self.logger.error(f"⚠️ ffprobe error retrieving audio info for {self.file_path}: {e}")
        except json.JSONDecodeError:
            self.logger.error(f"⚠️ Failed to parse ffprobe output for audio streams in {self.file_path}")
        
        return []



class Encoding:
    """Base class for video encoding."""

    DEFAULT_PRESET = {
        "4k": "medium",
        "2k": "medium",
        "1080p": "medium",
        "720p": "medium",
        "480p": "medium"
    }

    DEFAULT_CRF = {
        "4k": 18,
        "2k": 18,
        "1080p": 18,
        "720p": 18,
        "480p": 18
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

        self.output_tmp_file = self.generate_tmp_output_filename()
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
    

    def generate_tmp_output_filename(self) -> str:
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

    def get_preset(self, video_stream:VideoStream) -> str:
        return self.preset if self.preset is not None else self.DEFAULT_PRESET[video_stream.get_readable_resolution()]
    
    def get_crf(self, video_stream:VideoStream) -> str:
        crf = self.crf if self.crf is not None else self.DEFAULT_CRF[video_stream.get_readable_resolution()]
        return str(crf)

    def _get_filename_suffix(self) -> str:
        """This method should be overridden by subclasses to define the filename format."""
        raise NotImplementedError("Subclasses must implement _get_filename_suffix()")

    def prepare_cmd(self) -> Optional[List[str]]:
        """Prepare FFmpeg command for HEVC encoding."""
        video_args = self.prepare_video_args()
        audio_args = self.prepare_audio_args()

        if not video_args:
            return None
        elif self.codec not in video_args:
            return None
        
        cmd = ["ffmpeg", "-y", "-i", self.media_file.file_path,
                *video_args,
                *audio_args,
                "-movflags", "+faststart",
                "-c:s", "copy",
                self.output_tmp_file
                 ]
        return cmd

    def prepare_video_args(self, copy_codec={}) -> List[str]:
        raise NotImplementedError("This method should be implemented in child classes.")

    def prepare_audio_args(self) -> List[str]:
        """Prepare audio conversion arguments."""
        compatible_codecs = {"aac", "mp3", "ac3"}
        audio_args = []

        for index, audio_stream in enumerate(self.media_file.audio_info):
            audio_args.extend(audio_stream.map_prefix(index))
            if audio_stream.codec in compatible_codecs:
                audio_args.extend(["copy"])
            else:
                target_bitrate = f"{audio_stream.bit_rate}k" if audio_stream.bit_rate else "128k"
                audio_args.extend([f"-c:a:{audio_stream.index}", "aac", f"-b:a:{audio_stream.index}", target_bitrate])
                # ffmpeg preserves sample rate by default
        
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
            self.logger.exception(e)
            return EncodingStatus.FAILED

class HevcEncoding(Encoding):
    """Handles HEVC (H.265) encoding with resolution-based parameter selection."""

    DEFAULT_PRESET = {
        "4k": "veryslow",
        "2k": "slower",
        "1080p": "slow",
        "720p": "medium",
        "480p": "medium"
    }

    DEFAULT_CRF = {
        "4k": 20,
        "2k": 22,
        "1080p": 24,
        "720p": 26,
        "480p": 28
    }

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 delete_original: bool = False, output_dir: Optional[str] = None):
        super().__init__(media_file, codec="libx265", preset=preset, crf=crf,
                         delete_original=delete_original, output_dir=output_dir)
        
        self.logger.debug(f"🔹 HEVC class initialized for {media_file.file_path}")

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for HEVC encoding."""
        first_video = self.media_file.video_info[0]
        return f"_hevc_preset-{self.get_preset(first_video)}_crf-{self.get_crf(first_video)}"
    
    def prepare_video_args(self, copy_codec={"hevc"}) -> List[str]:
        """Prepare video conversion arguments."""
        video_args = []
        
        preset_log = []
        crf_log = []

        counter = 0
        for video_stream in self.media_file.video_info:
            if video_stream.codec in copy_codec:
                video_args.extend(video_stream.map_prefix(counter))
                if video_stream.tag == "hev1":
                    self.logger.info(f"🔄 Remuxing '{self.media_file.file_path}' from hev1 to hvc1 (no re-encoding).")
                    video_args.extend(["copy", "-tag:v", "hvc1"])
                else:
                    video_args.extend(["copy"])
                    self.logger.warning(f"⚠️ Skipping HEVC encoding: {self.media_file.file_path} is already in the desired format.")
                counter += 1
                preset_log.append("copy")
                crf_log.append("copy")
            else:
                video_args.extend(video_stream.map_prefix(counter))
                video_args.extend(["libx265", "-preset", self.get_preset(video_stream), "-tag:v", "hvc1", "-crf", self.get_crf(video_stream)])
                counter += 1

                preset_log.append(self.get_preset(video_stream))
                crf_log.append(self.get_crf(video_stream))
        
        self.logger.debug(f"🎬 Prepared video arguments: {video_args}")
        self.logger.info(f"🔹 HEVC encoding initialized for {self.media_file.file_path} | Preset: {", ".join(preset_log)} | CRF: {", ".join(crf_log)}")
        return video_args

class Av1Encoding(Encoding):
    """Handles AV1 encoding with resolution-based parameter selection."""

    DEFAULT_PRESET = {
        "4k": "slowest",
        "2k": "slower",
        "1080p": "slow",
        "720p": "medium",
        "480p": "medium"  # Change: Use medium for 480p for better speed
    }

    # 8-10% quality loss
    DEFAULT_CRF = {
        "4k": 21,
        "2k": 23,
        "1080p": 25,
        "720p": 27,
        "480p": 30
    }

    DEFAULT_CPU_USED = {
        "4k": 4,
        "2k": 4,
        "1080p": 5,
        "720p": 5,
        "480p": 6
    }

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 cpu_used: Optional[int] = None, delete_original: bool = False, output_dir: Optional[str] = None):
        self.cpu_used = cpu_used
        super().__init__(media_file, codec="libaom-av1", preset=preset, crf=crf,
                         delete_original=delete_original, output_dir=output_dir)
        
        
        self.logger.debug(f"🔹 AV1 class initialized for {media_file.file_path}")


    def get_cpu_used(self, video_stream:VideoStream) -> str:
        selected_cpu_used = self.cpu_used if self.cpu_used is not None else self.DEFAULT_CPU_USED[video_stream.get_readable_resolution()]
        if selected_cpu_used > 8:
            selected_cpu_used = 8
        elif selected_cpu_used < 0:
            selected_cpu_used = 0
        
        return str(selected_cpu_used)
    
    def get_maximum_keyframe_interval(self, video_stream:VideoStream) -> str:
        frame_rate = video_stream.frame_rate if video_stream.frame_rate else 60
        interval = round(frame_rate * 10)
        return str(interval)

    def get_keyint_min(self, video_stream:VideoStream) -> str:
        return self.get_maximum_keyframe_interval(video_stream)

    def prepare_video_args(self, copy_codec={"av1"}) -> List[str]:
        """Prepare video conversion arguments."""
        video_args = []

        preset_log = []
        crf_log = []
        cpu_used_log = []

        counter = 0
        for video_stream in self.media_file.video_info:
            video_args.extend(video_stream.map_prefix(counter))
            if video_stream.codec in copy_codec:
                self.logger.info(f"⚠️ Skipping encoding: The input video '{self.media_file.file_path}' is already in AV1 format.")
                video_args.extend(["copy"])

                preset_log.append("copy")
                crf_log.append("copy")
                cpu_used_log.append("copy")
            else:
                
                preset, crf, cpu_used = self.get_preset(video_stream), self.get_crf(video_stream), self.get_cpu_used(video_stream)
                maximum_keyframe_interval = self.get_maximum_keyframe_interval(video_stream)
                keyint_min = self.get_keyint_min(video_stream)
                video_args.extend(["libaom-av1", "-preset", preset, 
                                   "-cpu-used", cpu_used, "-row-mt", "1", 
                                   "-crf", crf, "-b:v", "0",
                                   "-g", maximum_keyframe_interval,
                                   "-keyint_min", keyint_min,
                                   ])
                # Note that in FFmpeg versions prior to 4.3, triggering the CRF mode also requires setting the bitrate to 0 with -b:v 0. If this is not done, the -crf switch triggers the constrained quality mode with a default bitrate of 256kbps.
                preset_log.append(preset)
                crf_log.append(crf)
                cpu_used_log.append(cpu_used)
            
            counter += 1
        
        self.logger.info(f"🔹 AV1 encoding initialized for {self.media_file.file_path} | Preset: {", ".join(preset_log)} | CRF: {", ".join(crf_log)} | CPU: {", ".join(cpu_used_log)}")
        self.logger.debug(f"🎬 Prepared video arguments: {video_args}")
        return video_args

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for AV1 encoding, including CPU-used."""
        first_media = self.media_file.video_info[0]
        return f"_av1_preset-{self.get_preset(first_media)}_crf-{self.get_crf(first_media)}_cpu-{self.get_cpu_used(first_media)}"
    


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

