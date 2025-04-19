from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

class EncodingStatus(Enum):
    SKIPPED = "skipped"  # Encoding was not necessary (e.g., already in the correct format).
    SUCCESS = "success"  # Encoding completed successfully.
    FAILED = "failed"    # Encoding process encountered an error.
    LOWQUALITY = "low quality"  # The encoded video did not meet quality expectations.
    LARGESIZE = "large size"    # The encoded video has larger size than original video.

@dataclass
class GeneralConfig:
    """General logging and default video metadata assumptions."""
    log_dir: str = "logs"  # Directory path where log files will be stored for encoding logs.
    resolution_tolerance: float = 0.05  # Allows minor differences in resolution before deciding to re-encode.
    default_resolution: str = "1080p"  # Default resolution to assume if video resolution is unknown.
    default_frame_rate: int = 30  # Default frame rate used when a video's frame rate is not available.

@dataclass
class VerificationConfig:
    """Settings controlling deletion, quality verification, and size checks."""
    delete_threshold: float = 90.0  # Minimum VMAF score required to delete the original file.
    delete_origin: bool = False  # If True, deletes the original file after encoding to save space.
    verify: bool = False  # If True, performs a verification check using VMAF before deleting the original file.
    check_size: bool = True  # If True, checks if encoded file is smaller than original.

@dataclass
class SVTAV1Config:
    """SVT-AV1 encoder configuration defaults."""
    tune: int = 0  # Tuning mode: 0 = sharpness (VA), 1 = PSNR, 2 = SSIM.
    fast_decode: int = 1  # Fast decode setting (0-2), 0 means off.
    preset: Dict[str, int] = field(default_factory=lambda: {
        "4k": 4, "2k": 4, "1080p": 5, "720p": 5, "480p": 6, "360p": 6
    })  # Preset levels for SVT-AV1 by resolution (lower = slower, better compression).
    crf: Dict[str, int] = field(default_factory=lambda: {
        "4k": 30, "2k": 29, "1080p": 28, "720p": 27, "480p": 25, "360p": 24
    })  # CRF values for SVT-AV1 by resolution (lower = better quality, larger size).

@dataclass
class HEVCConfig:
    """HEVC (H.265) encoder configuration defaults."""
    preset: Dict[str, str] = field(default_factory=lambda: {
        "4k": "slow", "2k": "slow", "1080p": "medium", "720p": "medium", "480p": "fast", "360p": "fast"
    })  # Preset settings (speed vs. compression efficiency).
    crf: Dict[str, int] = field(default_factory=lambda: {
        "4k": 25, "2k": 24, "1080p": 23, "720p": 22, "480p": 20, "360p": 19
    })  # CRF values for HEVC (lower = higher quality).

@dataclass
class LibAomAV1Config:
    """libaom-AV1 encoder configuration defaults."""
    crf: Dict[str, int] = field(default_factory=lambda: {
        "4k": 28, "2k": 27, "1080p": 27, "720p": 24, "480p": 21, "360p": 19
    })  # CRF values for libaom-AV1 (lower = better quality).
    preset: Dict[str, int] = field(default_factory=lambda: {
        "4k": 4, "2k": 4, "1080p": 4, "720p": 4, "480p": 4, "360p": 4
    })  # Preset levels for libaom-AV1 by resolution.

@dataclass
class ResolutionConfig:
    """Mapping from resolution labels to pixel counts."""
    mapping: Dict[str, int] = field(default_factory=lambda: {
        "4k": 3840 * 2160,
        "2k": 2560 * 1440,
        "1080p": 1920 * 1080,
        "720p": 1280 * 720,
        "480p": 640 * 480,
        "360p": 480 * 360
    })  # Resolution label to pixel area mapping.

@dataclass
class Config:
    """Root config combining all encoder and system configuration."""
    general: GeneralConfig = field(default_factory=GeneralConfig)
    verify: VerificationConfig = field(default_factory=VerificationConfig)
    svt_av1: SVTAV1Config = field(default_factory=SVTAV1Config)
    hevc: HEVCConfig = field(default_factory=HEVCConfig)
    libaom_av1: LibAomAV1Config = field(default_factory=LibAomAV1Config)
    resolution: ResolutionConfig = field(default_factory=ResolutionConfig)  # always fixed

