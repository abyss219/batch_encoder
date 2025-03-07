import subprocess

def check_ffmpeg_installed() -> bool:
    """Check if FFmpeg is installed and accessible."""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: FFmpeg is not installed or not found in the system path.")
        return False

from .encoders.hevc_encoder import HevcEncoder
from .encoders.av1_encoder import LibaomAV1Encoder, SVTAV1Encoder
from .media import MediaFile

__all__ = [
    'HevcEncoder', 'LibaomAV1Encoder', 'SVTAV1Encoder', 'MediaFile', 'check_ffmpeg_installed'
]