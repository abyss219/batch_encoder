from enum import Enum

LOG_DIR = "logs"

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
    LOWQUALITY = "low quality"

RESOLUTION = {
    "4k": 3840 * 2160,
    "2k": 2560 * 1440,
    "1080p": 1920 * 1080,
    "720p": 1280 * 720,
    "480p": 640 * 480
}

DEFAULT_PRESET_HEVC = {
    "4k": "slow",
    "2k": "slow",
    "1080p": "slow",
    "720p": "slow",
    "480p": "slow"
}

'''
DEFAULT_PRESET_HEVC = {
    "4k": "slow",
    "2k": "slow",
    "1080p": "medium",
    "720p": "medium",
    "480p": "fast"
}
'''


DEFAULT_CRF_HEVC = {
    "4k": 20,
    "2k": 21,
    "1080p": 22,
    "720p": 24,
    "480p": 26
}


DEFAULT_PRESET_AV1 = {
    "4k": 3,
    "2k": 3,
    "1080p": 4,
    "720p": 5,
    "480p": 6
}


DEFAULT_CRF_AV1 = {
    "4k": 22,
    "2k": 23,
    "1080p": 25,
    "720p": 27,
    "480p": 29
}