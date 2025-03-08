from enum import Enum

class EncodingStatus(Enum):
    SKIPPED = "skipped" # Encoding was not necessary (e.g., already in the correct format).
    SUCCESS = "success" # Encoding completed successfully.
    FAILED = "failed" # Encoding process encountered an error.
    LOWQUALITY = "low quality" # The encoded video did not meet quality expectations.
    LARGESIZE = "large size" # The encoded video has larger size then original video.

LOG_DIR = "logs" # Directory path where log files will be stored for encoding logs.

# Encoding and Verification Settings
DEFAULT_DELETE_THRESHOLD = 90.0 # Minimum VMAF score required to delete the original file.
DEFAULT_DELETE_ORIGIN = False # If True, deletes the original file after encoding to save space.
DEFAULT_VERIFY = False # If True, performs a verification check using VMAF before deleting the original file.
DEFAULT_CHECK_SIZE = True

# Video Processing Defaults
DEFAULT_RESOLUTION_TOLERANCE = 0.05 # Allows minor differences in resolution before deciding to re-encode.
DEFAULT_RESOLUTION = '1080p' # Default resolution to assume if video resolution is unknown.
DEFAULT_FRAME_RATE = 30 # Default frame rate used when a video's frame rate is not available (used in key frame calculations).

# Audio Encoding Defaults
DEFAULT_AUDIO_BIT_RATE = "128k" # Default bitrate for encoding audio streams when no specific bitrate is provided.

# SVT-AV1 Specific Defaults
DEFAULT_SVTAV1_TUNE = 0 # Default tuning mode for SVT-AV1 (0 = sharpness [VA], 1 = PSNR optimization, 2 = SSIM).
DEFAULT_SVTAV1_FAST_DECODE = 1 # Default fast decode setting (0-2), 0 means off, reducing CPU load at the cost of compression efficiency.

# Resolution Mapping - Maps resolution labels (e.g., "1080p") to their corresponding pixel counts.
RESOLUTION = {
    "4k": 3840 * 2160,
    "2k": 2560 * 1440,
    "1080p": 1920 * 1080,
    "720p": 1280 * 720,
    "480p": 640 * 480,
    "360p": 480 * 360
}
 # Encoder Defaults - HEVC preset settings determine encoding speed vs. compression efficiency.
DEFAULT_PRESET_HEVC = {
    "4k": "slow",
    "2k": "slow",
    "1080p": "slow",
    "720p": "slow",
    "480p": "slow",
    "360p": "slow"
}

# CRF (Constant Rate Factor) settings for HEVC encoding. Lower values mean higher quality and larger file sizes.
DEFAULT_CRF_HEVC = {
    "4k": 24,
    "2k": 23,
    "1080p": 23,
    "720p": 20,
    "480p": 18,
    "360p": 16
}

# Preset settings for AV1 encoding, where lower values offer better compression at the cost of speed.
DEFAULT_PRESET_SVTAV1 = {
    "4k": 4,
    "2k": 4,
    "1080p": 4,
    "720p": 4,
    "480p": 4,
    "360p": 4
}

# CRF settings for AV1 encoding. Lower values mean better quality and larger file sizes.
DEFAULT_CRF_SVTAV1 = {
    "4k": 31,
    "2k": 30,
    "1080p": 30,
    "720p": 26,
    "480p": 23,
    "360p": 21
}

DEFAULT_CRF_LIBAMOAV1 = {
    "4k": 28,
    "2k": 27,
    "1080p": 27,
    "720p": 24,
    "480p": 21,
    "360p": 19
}

DEFAULT_PRESET_LIBAMOAV1 = {
    "4k": 4,
    "2k": 4,
    "1080p": 4,
    "720p": 4,
    "480p": 4,
    "360p": 4
}