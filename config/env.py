import subprocess
from pathlib import Path
from typing import Union, Tuple
import platform
import sys

def is_ffmpeg_availiable(ffmpeg_path: Union[str, Path] = "ffmpeg") -> bool:
    """
    Checks whether FFmpeg exists at the specified path and supports required codecs
    and filters: libsvtav1, libaom-av1, libx265, and libvmaf.

    Args:
        ffmpeg_path (Union[str, Path]): Path to the ffmpeg binary. Defaults to "ffmpeg".

    Returns:
        bool: True if FFmpeg is valid and supports required codecs and libvmaf, False otherwise.
    """
    if isinstance(ffmpeg_path, Path):
        ffmpeg_path = ffmpeg_path.resolve()

    ffmpeg_path = str(ffmpeg_path)

    try:
        # Check if FFmpeg is available
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )

        # Check for codec support
        codec_result = subprocess.run(
            [ffmpeg_path, "-codecs"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )
        codec_output = codec_result.stdout.lower()

        # Required codecs
        required_codecs = {"libsvtav1", "libaom-av1", "libx265"}

        # Ensure all required codecs are present
        if not all(codec in codec_output for codec in required_codecs):
            print(
                "❌ Error: FFmpeg is installed but missing required codecs: ",
                required_codecs - set(codec_output.split()),
            )
            return False
        
        # Check for VMAF filter support
        filter_result = subprocess.run(
            [ffmpeg_path, "-filters"],
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
        print("❌ Error: FFmpeg is not installed or not found in the system path.")
        return False


def is_ffprobe_available(ffprobe_path: Union[str, Path] = "ffprobe") -> bool:
    """
    Checks whether ffprobe exists at the specified path.

    Args:
        ffprobe_path (Union[str, Path]): Path to the ffprobe binary. Defaults to "ffprobe".

    Returns:
        bool: True if ffprobe is found and executable, False otherwise.
    """

    if isinstance(ffprobe_path, Path):
        ffprobe_path = ffprobe_path.resolve()
        
    ffprobe_path = str(ffprobe_path)

    try:
        # check if ffprobe binary is executable
        subprocess.run(
            [ffprobe_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )
        return True

    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: ffprobe is not installed or not found in the system path.")
        return False

def check_env() -> Tuple[Path]:
    system_platform = platform.system()
    local_root = Path("ffmpeg")

    if system_platform == "Darwin":
        local_ffmpeg = local_root / "macos" / "ffmpeg"
        local_ffprobe = local_root / "macos" / "ffprobe"
    elif system_platform == "Windows":
        local_ffmpeg = local_root / "windows" / "ffmpeg.exe"
        local_ffprobe = local_root / "windows" / "ffprobe.exe"
    else:  # Linux: system only
        local_ffmpeg = None
        local_ffprobe = None

    if is_ffmpeg_availiable() and is_ffprobe_available():
        # print("✅ Using system FFmpeg and ffprobe.")
        return Path('ffmpeg'), Path('ffprobe')
    elif local_ffprobe and local_ffmpeg.is_file() and local_ffprobe and local_ffprobe.is_file():
        local_ffmpeg = local_ffmpeg.resolve()
        local_ffprobe = local_ffprobe.resolve()
        if is_ffmpeg_availiable(local_ffmpeg) and is_ffprobe_available(local_ffprobe):
            # print(f"⚠️ System FFmpeg not suitable. Using local FFmpeg at: {local_root.resolve()}")
            return local_ffmpeg, local_ffprobe
        print("❌ No valid FFmpeg/ffprobe found or missing required features.")
    
    sys.exit(1)