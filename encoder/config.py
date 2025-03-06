from enum import Enum

DEFAULT_DELETE_THRESHOLD = 90.0
DEFAULT_DELETE_ORIGIN = False
DEFAULT_RESOLUTION_TOLERANCE = 0.05
DEFAULT_RESOLUTION = '1080p'
DEFAULT_CODEC = "hevc"
DEFAULT_FRAME_RATE = 30 # used in get_maximum_keyframe_interval
DEFAULT_VERIFY = False
DEFAULT_AUDIO_BIT_RATE = "128k"

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
DEFAULT_PRESET_HEVC = {
    "4k": "veryslow",
    "2k": "slower",
    "1080p": "slow",
    "720p": "medium",
    "480p": "medium"
}

DEFAULT_CRF_HEVC = {
    "4k": 20,
    "2k": 22,
    "1080p": 24,
    "720p": 26,
    "480p": 28
}

DEFAULT_PRESET_AV1 = {
    "4k": 0,
    "2k": 1,
    "1080p": 2,
    "720p": 3,
    "480p": 4
}

DEFAULT_CRF_AV1 = {
    "4k": 21,
    "2k": 23,
    "1080p": 25,
    "720p": 27,
    "480p": 30
}