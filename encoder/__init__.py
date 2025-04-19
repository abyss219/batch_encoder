import subprocess


def check_ffmpeg_installed() -> bool:
    """
    Check if FFmpeg is installed and accessible.
    Also verifies if FFmpeg supports required codecs: libsvtav1, libaom-av1, and libx265.

    Returns:
        bool: True if FFmpeg is installed and supports required codecs, False otherwise.
    """
    try:
        # Check if FFmpeg is available
        result = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )

        # Check for codec support
        codec_result = subprocess.run(
            ["ffmpeg", "-codecs"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )
        codec_output = codec_result.stdout.lower()

        # Required codecs
        required_codecs = {"libsvtav1", "libaom-av1", "libx265"}

        # Ensure all required codecs are present
        if all(codec in codec_output for codec in required_codecs):
            return True
        else:
            print(
                "❌ Error: FFmpeg is installed but missing required codecs: ",
                required_codecs - set(codec_output.split()),
            )
            return False
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: FFmpeg is not installed or not found in the system path.")
        return False


def is_ffprobe_available() -> bool:
    """
    Checks if the ffprobe command exists in the system and supports VMAF.

    Returns:
        bool: True if ffprobe is available and supports VMAF, False otherwise.
    """
    try:
        # Check if ffprobe is installed
        subprocess.run(
            ["ffprobe", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )

        # Check for VMAF filter support
        filter_result = subprocess.run(
            ["ffmpeg", "-filters"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )
        filter_output = filter_result.stdout.lower()

        if "libvmaf" in filter_output:
            return True
        else:
            print("❌ Error: ffprobe is installed but does not support VMAF.")
            return False
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: ffprobe is not installed or not found in the system path.")
        return False


import sys
from .encoders.hevc_encoder import HevcEncoder
from .encoders.av1_encoder import LibaomAV1Encoder, SVTAV1Encoder
from .media import MediaFile

__all__ = ["HevcEncoder", "LibaomAV1Encoder", "SVTAV1Encoder", "MediaFile"]

if not check_ffmpeg_installed() or not is_ffprobe_available():
    sys.exit(1)
