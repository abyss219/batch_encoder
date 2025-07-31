from __future__ import annotations
from utils import setup_logger
from config import load_config, RESOLUTION, FFMPEG, FFPROBE
from typing import List, Optional, Union
import json
import subprocess
import re
from dataclasses import dataclass, asdict
import sys
import logging
from pathlib import Path
import math

config = load_config()


@dataclass(frozen=True)
class VideoStream:
    """
    Represents a video stream extracted from a media file.

    Attributes:
        index (Optional[int]): Original index of the stream in the media file.
        ffmpeg_index (int): Index used by FFmpeg for mapping.
        codec (Optional[str]): Codec used for the video stream.
        tag (Optional[str]): Additional tag information.
        width (Optional[int]): Width of the video in pixels.
        height (Optional[int]): Height of the video in pixels.
        frame_rate (Optional[float]): Frame rate of the video.
        duration (Optional[float]): Duration of the video in seconds.
    """

    index: Optional[int]
    ffmpeg_index: int
    codec: Optional[str]
    tag: Optional[str]
    width: Optional[int]
    height: Optional[int]
    frame_rate: Optional[float]
    duration: Optional[float]
    pix_fmt: Optional[str]

    def get_readable_resolution_or_default(
        self,
        default=config.general.default_resolution,
        tolerance=config.general.resolution_tolerance,
    ):
        """
        Determines the closest standard resolution for the video based on pixel count.
        If the resolution doesn't match a known category, returns the default resolution.

        Args:
            default (str): Default resolution to return if no match is found.
            tolerance (float): Allowed variation in pixel count when determining resolution.

        Returns:
            str: The identified resolution or the default value.
        """
        if self.height is None or self.width is None:
            return default

        pixel_count = self.width * self.height

        for res, standard_pixels in RESOLUTION.items():
            if (
                abs(pixel_count - standard_pixels) <= standard_pixels * tolerance
                or pixel_count >= standard_pixels
            ):
                resolution = res
                break
        else:
            resolution = default  # If it doesn’t fit any category
        return resolution

    def map_prefix(self, new_index: int):
        """
        Generates FFmpeg mapping arguments for the video stream.

        Args:
            new_index (int): New index assigned to the stream in FFmpeg processing.

        Returns:
            List[str]: FFmpeg command arguments for mapping the video stream.
        """
        return ["-map", f"0:v:{self.ffmpeg_index}", f"-c:v:{new_index}"]


@dataclass(frozen=True)
class AudioStream:
    """
    Represents an audio stream extracted from a media file.

    Attributes:
        codec (Optional[str]): Codec used for the audio stream.
        ffmpeg_index (int): Index used by FFmpeg for mapping.
        index (Optional[int]): Original index of the stream in the media file.
        bit_rate (Optional[int]): Bit rate of the audio stream.
        sample_rate (Optional[int]): Sample rate of the audio stream.
    """

    codec: Optional[str]
    ffmpeg_index: int
    index: Optional[int]
    bit_rate: Optional[int]
    sample_rate: Optional[int]

    def map_prefix(self, new_index: int):
        """
        Generates FFmpeg mapping arguments for the audio stream.

        Args:
            new_index (int): New index assigned to the stream in FFmpeg processing.

        Returns:
            List[str]: FFmpeg command arguments for mapping the audio stream.
        """
        prefix = ["-map", f"0:a:{self.ffmpeg_index}", f"-c:a:{new_index}"]
        return prefix


class MediaFile:
    """
    Handles media metadata extraction using ffprobe.

    Attributes:
        file_path (Path): Path to the media file.
        video_info (List[VideoStream]): List of detected video streams.
        audio_info (List[AudioStream]): List of detected audio streams.
    """

    def __init__(self, file_path: Union[str, Path], debug: bool = False, log_filename="media_file.log"):
        self.logger = setup_logger(
            self.__class__.__name__,
            Path(config.general.log_dir) / log_filename,
            logging.DEBUG if debug else logging.INFO,
        )
        self.file_path = Path(file_path)

        if not self.file_path.is_file():
            self.logger.error(f"❌ File does not exist or is not a file: {self.file_path}")
            raise FileNotFoundError(f"'{self.file_path}' is not a valid file path.")

        self.logger.debug(f"🔍 Initializing MediaFile for: {file_path}")

        self.video_info = self.get_video_info()
        if not self.video_info:
            self.logger.error(f"❌ Invalid video file: {file_path}")
            raise ValueError("The provided file does not contain a valid video stream.")

        self.audio_info = self.get_audio_info()

    def compare(self, other: MediaFile) -> float:
        """
        Compares this video file with another using VMAF and returns the VMAF score.

        Args:
            other (MediaFile): Another MediaFile object to compare against.

        Returns:
            float: VMAF score or None if an error occurs.
        """
        self.logger.debug(
            f"🔍 Comparing {self.file_path.name} with {other.file_path.name} using VMAF"
        )

        cmd = [
            FFMPEG,
            "-i",
            self.file_path.resolve(),  # Original Video
            "-i",
            other.file_path.resolve(),  # Encoded Video
            "-filter_complex",
            "[0:v][1:v]libvmaf",  # Apply VMAF comparison
            "-f",
            "null",
            "-",  #  # No output file, just display results
        ]
        try:
            # Run the FFmpeg command
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8"
            )

            # Check if FFmpeg execution failed
            if result.returncode != 0:
                self.logger.error(f"❌ FFmpeg execution failed: {result.stderr}")
                raise subprocess.SubprocessError(f"FFmpeg error: {result.stderr}")

            output = result.stderr  # VMAF results appear in stderr

            # Extract VMAF score using regex
            match = re.search(r"VMAF score: ([0-9]+(?:\.[0-9]+)?)", output)
            if match:
                try:
                    vmaf_score = float(match.group(1))
                    self.logger.debug(
                        f"✅ VMAF Score successful calculation: {vmaf_score}"
                    )
                    return vmaf_score
                except ValueError:
                    self.logger.error("❌ Error converting VMAF score to float")
                    return None

            # Log if VMAF score was not found
            self.logger.warning("⚠️ VMAF score not found in FFmpeg output")
            return None

        except subprocess.SubprocessError as e:
            self.logger.error(f"❌ Subprocess Error: {e}")
            return None

        except ValueError as e:
            self.logger.error(f"❌ Float Conversion Error: {e}")
            return None

        except KeyboardInterrupt:
            self.logger.warning(f"🔴 VMAF calculation interrupted manually (Ctrl+C).")
            sys.exit(1)

        except Exception as e:
            self.logger.exception(e)
            return None

    def get_video_info(self) -> List[VideoStream]:
        """
        Retrieve all video streams' codec, resolution, and frame rate in one ffprobe call.
        Returns a list of VideoStream objects. If no valid stream is found, returns an empty list.

        Returns:
            List[VideoStream]: List of valid video streams extracted from the file.
        """
        cmd = [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=codec_type,codec_name,tag_string,width,height,r_frame_rate,nb_frames,duration,index,pix_fmt",
            "-of",
            "json",
            self.file_path.resolve(),
        ]
        
        self.logger.debug(f"🔍 Running ffprobe for video stream info: {' '.join(map(str, cmd))}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, check=True, encoding="utf-8"
            )
            self.logger.debug(f"✅ ffprobe video stdout:\n{result.stdout}")
            self.logger.debug(f"✅ ffprobe video stderr:\n{result.stderr}")
            info = json.loads(result.stdout)
            video_streams = []

            index_counter = 0  # FFmpeg assigns 0-based indexes to video streams

            if "streams" in info:
                for stream in info["streams"]:
                    self.logger.debug(f"🔍 Processing video stream: {stream}")
                    codec_type = stream.get("codec_type")
                    codec = stream.get("codec_name")
                    tag = stream.get("tag_string")

                    # Convert relevant keys to integers where possible
                    for key in ["index", "width", "height"]:
                        if stream.get(key) is not None:
                            try:
                                stream[key] = int(stream[key])
                            except ValueError:
                                self.logger.warning(f"⚠️ Failed to convert '{key}' to int: {stream[key]}")
                                stream[key] = None

                    index = stream["index"]  # Used to validate the video stream
                    width = stream["width"]
                    height = stream["height"]

                    duration = stream.get("duration")

                    pix_fmt = stream.get("pix_fmt")

                    # Extract frame rate from string format (e.g., "30000/1001")
                    frame_rate_str = stream.get("r_frame_rate")
                    if frame_rate_str:
                        frame_match = re.match(r"(\d+)/(\d+)", frame_rate_str)
                        if frame_match:
                            numerator, denominator = int(frame_match.group(1)), int(
                                frame_match.group(2)
                            )
                            frame_rate = (
                                0 if denominator == 0 else numerator / denominator
                            )
                        else:
                            frame_rate = None

                    stm = VideoStream(
                        index=index,
                        ffmpeg_index=index_counter,  # ffmpeg uses 0 indexing fro both video and audio
                        codec=codec,
                        tag=tag,
                        width=width,
                        height=height,
                        frame_rate=frame_rate,
                        duration=duration,
                        pix_fmt=pix_fmt,
                    )

                    if (
                        codec_type != "video"
                        or codec
                        in {
                            "png",
                            "mjpeg",
                            "bmp",
                            "gif",
                            "tiff",
                            "jpegxl",
                            "webp",
                            "heif",
                            "avif",
                        }
                        or
                        # if frame_rate defined then frame_match must be defined
                        frame_rate
                        and int(frame_match.group(2))
                        == int(frame_match.group(1))  # Detect single-frame video.
                        or stream.get("nb_frames")
                        == "1"  # Explicit check for single-frame videos
                        or frame_rate == 0  # Invalid frame rate
                        or index is None  # Ensure index exists
                    ):
                        self.logger.warning(
                            f"❌ Invalid video stream detected for file {self.file_path.name}: {asdict(stm)}"
                        )
                    else:
                        self.logger.debug(f"✅ Valid video stream found: {asdict(stm)}")
                        video_streams.append(stm)

                    index_counter += 1  # Increment FFmpeg stream index

            if not video_streams:
                self.logger.debug(f"⚠️ No valid video streams found in: {self.file_path}")

            return (
                video_streams  # Return empty list if no valid video streams are found
            )

        except subprocess.CalledProcessError as e:
            print(f"⚠️ ffprobe error retrieving video info for {self.file_path}: {e}")
        except json.JSONDecodeError:
            print(
                f"⚠️ Failed to parse ffprobe output for video info in {self.file_path}"
            )

        return []

    def get_audio_info(self) -> List[AudioStream]:
        """
        Retrieve all audio streams' codec and bit rate in one ffprobe call.
        Returns a list of AudioStream objects. If no valid stream is found, returns an empty list.

        Returns:
            List[AudioStream]: List of valid audio streams extracted from the file.
        """
        cmd = [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type,codec_name,index,bit_rate,sample_rate",
            "-of",
            "json",
            self.file_path.resolve(),
        ]
        self.logger.debug(f"🔍 Running ffprobe for audio stream info: {' '.join(map(str, cmd))}")

        index_counter = 0  # FFmpeg assigns 0-based indexes to audio streams
        try:
            result = subprocess.run(
                cmd, capture_output=True, check=True, encoding="utf-8"
            )
            self.logger.debug(f"✅ ffprobe audio stdout:\n{result.stdout}")
            self.logger.debug(f"✅ ffprobe audio stderr:\n{result.stderr}")
            info = json.loads(result.stdout)
            audio_streams = []

            if "streams" in info:
                for stream in info["streams"]:
                    self.logger.debug(f"🔍 Processing audio stream: {stream}")
                    if stream.get("codec_type") != "audio":
                        continue

                    codec = stream.get("codec_name")
                    # Convert relevant keys to integers where possible
                    for key in ["index", "bit_rate", "sample_rate"]:
                        if stream.get(key) is not None:
                            try:
                                stream[key] = int(stream[key])
                            except ValueError:
                                self.logger.warning(f"⚠️ Failed to convert '{key}' to int: {stream[key]}")
                                stream[key] = None
                    index = stream.get("index")
                    bit_rate = stream.get("bit_rate")
                    sample_rate = stream.get("sample_rate")

                    try:
                        bit_rate = math.ceil(int(bit_rate) / 1000)
                    except (ValueError, TypeError):
                        self.logger.debug(f"Unable to fetch audio bit_rate, the value is not an integer {bit_rate}.")

                    if index is not None:
                        stm = AudioStream(
                                codec=codec,
                                ffmpeg_index=index_counter,  # Use FFmpeg's 0-based indexing
                                index=index,
                                bit_rate=bit_rate,
                                sample_rate=sample_rate,
                            )
                        audio_streams.append(stm)
                        self.logger.debug(f"✅ Valid audio stream found: {asdict(stm)}")

                    index_counter += 1  # Increment FFmpeg stream index

            if not audio_streams:
                self.logger.warning(f"⚠️ No valid audio streams found in: {self.file_path}")

            return audio_streams

        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"⚠️ ffprobe error retrieving audio info for {self.file_path}: {e}"
            )
        except json.JSONDecodeError:
            self.logger.error(
                f"⚠️ Failed to parse ffprobe output for audio streams in {self.file_path}"
            )

        return []
