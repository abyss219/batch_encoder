from dataclasses import dataclass, field
from enum import Enum
from typing import Dict
from pathlib import Path
from .env import check_env

class EncodingStatus(Enum):
    SKIPPED = (
        "skipped"  # Encoding was not necessary (e.g., already in the correct format).
    )
    SUCCESS = "success"  # Encoding completed successfully.
    FAILED = "failed"  # Encoding process encountered an error.
    LOWQUALITY = "low quality"  # The encoded video did not meet quality expectations.
    LARGESIZE = "large size"  # The encoded video has larger size than original video.


# Resolution Mapping - Maps resolution labels (e.g., "1080p") to their corresponding pixel counts.
RESOLUTION = {
    "4k": 3840 * 2160,
    "2k": 2560 * 1440,
    "1080p": 1920 * 1080,
    "720p": 1280 * 720,
    "480p": 640 * 480,
    "360p": 480 * 360,
}

FFMPEG, FFPROBE = check_env()

@dataclass
class GeneralConfig:
    """General logging and default video metadata assumptions."""

    log_dir: str = (
        "logs"  # Directory path where log files will be stored for encoding logs.
    )
    resolution_tolerance: float = (
        0.05  # Allows minor differences in resolution before deciding to re-encode.
    )
    default_resolution: str = (
        "1080p"  # Default resolution to assume if video resolution is unknown.
    )
    default_frame_rate: int = (
        30  # Default frame rate used when a video's frame rate is not available.
    )

    def validate(self):
        if not (0 <= self.resolution_tolerance <= 1):
            raise ValueError("resolution_tolerance must be between 0 and 1")
        if self.default_resolution not in RESOLUTION:
            raise ValueError(f"Unsupported default resolution: {self.default_resolution}")
        if self.default_frame_rate <= 0:
            raise ValueError("default_frame_rate must be positive")

        # Check and create log directory
        log_path = Path(self.log_dir)
        if not log_path.exists():
            log_path.mkdir(parents=True, exist_ok=True)
        elif not log_path.is_dir():
            raise ValueError(f"log_dir '{self.log_dir}' exists but is not a directory")

@dataclass
class VerificationConfig:
    """Settings controlling deletion, quality verification, and size checks."""

    delete_threshold: float = (
        90.0  # Minimum VMAF score required to delete the original file.
    )
    delete_origin: bool = (
        False  # If True, deletes the original file after encoding to save space.
    )
    verify: bool = (
        False  # If True, performs a verification check using VMAF before deleting the original file.
    )
    check_size: bool = True  # If True, checks if encoded file is smaller than original.

    def validate(self):
        if not (0 <= self.delete_threshold <= 100):
            raise ValueError("delete_threshold must be between 0 and 100")

        if not isinstance(self.delete_origin, bool):
            raise TypeError("delete_origin must be a boolean")
        if not isinstance(self.verify, bool):
            raise TypeError("verify must be a boolean")
        if not isinstance(self.check_size, bool):
            raise TypeError("check_size must be a boolean")

@dataclass
class SVTAV1Config:
    """SVT-AV1 encoder configuration defaults."""

    tune: int = 0  # Tuning mode: 0 = sharpness (VA), 1 = PSNR, 2 = SSIM.
    fast_decode: int = 1  # Fast decode setting (0-2), 0 means off.
    preset: Dict[str, int] = field(
        default_factory=lambda: {
            "4k": 4,
            "2k": 4,
            "1080p": 5,
            "720p": 5,
            "480p": 6,
            "360p": 6,
        }
    )  # Preset levels for SVT-AV1 by resolution (lower = slower, better compression).
    crf: Dict[str, int] = field(
        default_factory=lambda: {
            "4k": 30,
            "2k": 29,
            "1080p": 28,
            "720p": 27,
            "480p": 25,
            "360p": 24,
        }
    )  # CRF values for SVT-AV1 by resolution (lower = better quality, larger size).

    def validate(self):
        if self.tune not in {0, 1, 2}:
            raise ValueError("tune must be one of: 0 (sharpness), 1 (PSNR), 2 (SSIM)")

        if self.fast_decode not in {0, 1, 2}:
            raise ValueError("fast_decode must be between 0 and 2")

        for res, val in self.preset.items():
            if res not in RESOLUTION:
                raise ValueError(f"Unsupported resolution in preset: {res}")
            if not (1 <= val <= 13):
                raise ValueError(f"preset for {res} must be between 1 and 13")

        for res, val in self.crf.items():
            if res not in RESOLUTION:
                raise ValueError(f"Unsupported resolution in crf: {res}")
            if not (1 <= val <= 63):
                raise ValueError(f"crf for {res} must be between 1 and 63")

@dataclass
class HEVCConfig:
    """HEVC (H.265) encoder configuration defaults."""

    preset: Dict[str, str] = field(
        default_factory=lambda: {
            "4k": "slow",
            "2k": "slow",
            "1080p": "medium",
            "720p": "medium",
            "480p": "fast",
            "360p": "fast",
        }
    )  # Preset settings (speed vs. compression efficiency).
    crf: Dict[str, int] = field(
        default_factory=lambda: {
            "4k": 25,
            "2k": 24,
            "1080p": 23,
            "720p": 22,
            "480p": 20,
            "360p": 19,
        }
    )  # CRF values for HEVC (lower = higher quality).

    def validate(self):
        supported_presets = {
            "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
            "slow", "slower", "veryslow", "placebo"
        }

        for res, p in self.preset.items():
            if res not in RESOLUTION:
                raise ValueError(f"Unsupported resolution in preset: {res}")
            if p not in supported_presets:
                raise ValueError(f"Invalid HEVC preset '{p}' for resolution {res}")

        for res, v in self.crf.items():
            if res not in RESOLUTION:
                raise ValueError(f"Unsupported resolution in crf: {res}")
            if not (0 <= v <= 51):
                raise ValueError(f"HEVC crf for {res} must be between 0 and 51")

@dataclass
class LibAomAV1Config:
    """libaom-AV1 encoder configuration defaults."""

    crf: Dict[str, int] = field(
        default_factory=lambda: {
            "4k": 28,
            "2k": 27,
            "1080p": 27,
            "720p": 24,
            "480p": 21,
            "360p": 19,
        }
    )  # CRF values for libaom-AV1 (lower = better quality).
    preset: Dict[str, int] = field(
        default_factory=lambda: {
            "4k": 4,
            "2k": 4,
            "1080p": 4,
            "720p": 4,
            "480p": 4,
            "360p": 4,
        }
    )  # Preset levels for libaom-AV1 by resolution.

    def validate(self):
        for res, val in self.crf.items():
            if res not in RESOLUTION:
                raise ValueError(f"Unsupported resolution in crf: {res}")
            if not (0 <= val <= 63):
                raise ValueError(f"libaom-AV1 crf for {res} must be between 0 and 63")

        for res, val in self.preset.items():
            if res not in RESOLUTION:
                raise ValueError(f"Unsupported resolution in preset: {res}")
            if not (0 <= val <= 8):
                raise ValueError(f"libaom-AV1 preset for {res} must be between 0 and 8")

@dataclass
class Config:
    """Root config combining all encoder and system configuration."""

    general: GeneralConfig = field(default_factory=GeneralConfig)
    verify: VerificationConfig = field(default_factory=VerificationConfig)
    svt_av1: SVTAV1Config = field(default_factory=SVTAV1Config)
    hevc: HEVCConfig = field(default_factory=HEVCConfig)
    libaom_av1: LibAomAV1Config = field(default_factory=LibAomAV1Config)

    def validate(self):
        self.general.validate()
        self.verify.validate()
        self.svt_av1.validate()
        self.hevc.validate()
        self.libaom_av1.validate()