from __future__ import annotations
from .utils.logger import setup_logger
from .config import *
from typing import List, Optional
import json
import subprocess
import re
from dataclasses import dataclass, asdict
import os, sys

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

    def get_readable_resolution_or_default(self, default=DEFAULT_RESOLUTION, tolerance = DEFAULT_RESOLUTION_TOLERANCE):
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

        self.file_name = os.path.basename(self.file_path)


    def compare(self, other: MediaFile) -> float:
        """
        Compares this video file with another using VMAF and returns the VMAF score.

        :param other: Another MediaFile object to compare against.
        :return: VMAF score as a float, or None if an error occurs.
        """
        self.logger.debug(f"🔍 Comparing {self.file_name} with {other.file_name} using VMAF")
        
        cmd = [
            "ffmpeg", "-i", self.file_path, # Original Video
            "-i", other.file_path, # Encoded Video
            "-filter_complex", "[0:v][1:v]libvmaf", # Apply VMAF comparison
            "-f", "null", "-" #  # No output file, just display results
        ]
        try:
            # Run the FFmpeg command
            result = subprocess.run(cmd,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    encoding='utf-8')

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
                    self.logger.debug(f"✅ VMAF Score successful calculation: {vmaf_score}")
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
                                index=index, 
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