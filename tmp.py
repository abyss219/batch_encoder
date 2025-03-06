import os
import subprocess
import json
import sys
import argparse
import re
from typing import List, Tuple, Optional, Dict
from enum import Enum
from logger_util import setup_logger
import signal

logger = setup_logger("tmp")

def get_video_info(file_path) -> Dict[str, any]:
    """Retrieve video codec, tag, resolution, and frame rate in one ffprobe call."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=codec_type,codec_name,tag_string,width,height,r_frame_rate", "-of", "json", file_path
    ]
    logger.debug(f"📊 Running ffprobe for video info: {cmd}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        
        if "streams" in info and info["streams"]:
            stream = info["streams"][0]
            codec_type = stream.get("codec_type")
            codec = stream.get("codec_name", "unknown")


            tag = stream.get("tag_string", "unknown")
            width = stream.get("width", 1920)  # Default to 1920
            height = stream.get("height", 1080)  # Default to 1080
            frame_rate_str = stream.get("r_frame_rate", "30/1")
            frame_match = re.match(r"(\d+)/(\d+)", frame_rate_str)
            frame_rate = int(frame_match.group(1)) / int(frame_match.group(2)) if frame_match else 30.0
            
            print(codec_type)

            if (
                codec_type != "video" or 
                codec in {"png", "mjpeg", "bmp", "gif", "tiff", "jpegxl", "webp", "heif", "avif"} or 
                frame_match and int(frame_match.group(2)) == int(frame_match.group(1)) or  # Detect single-frame video
                stream.get("nb_frames") == "1" or  # Explicitly check frame count
                float(stream.get("duration", 0)) < 0.1 or  # Very short videos/images
                frame_rate == 0  # Invalid frame rate
            ):
                logger.warning(f"❌ Invalid video detected: {file_path}")
                return None


            logger.debug(f"📊 Video Info: Codec={codec}, Tag={tag}, Resolution={width}x{height}, FrameRate={frame_rate} for {file_path}")
            return {"codec": codec, "tag": tag, "width": width, "height": height, "frame_rate": frame_rate}
        
        logger.warning(f"⚠️ No video stream info found for {file_path}")

    except subprocess.CalledProcessError as e:
        logger.error(f"⚠️ ffprobe error retrieving video info for {file_path}: {e}")
        return None
    except json.JSONDecodeError:
        logger.error(f"⚠️ Failed to parse ffprobe output for video info in {file_path}")
    
    return {"codec": "unknown", "tag": "unknown", "width": 1920, "height": 1080, "frame_rate": 30.0}  # Return defaults if any error occurs\
        
output = get_video_info(r"C:\Users\ryan2\OneDrive\Videos\2021-11-12 11-14-15.mkv")
print(output)