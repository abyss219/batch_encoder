from ..config import *
from .encoder import PresetCRFEncoder
from ..media import MediaFile, VideoStream
from typing import Type, Optional, List, Dict, Set, Union
from abc import ABC, abstractmethod

class AV1Encode(PresetCRFEncoder, ABC):
    """
    Base class for AV1 encoding, inheriting from PresetCRFEncoder.
    This class serves as a foundation for specific AV1 encoders such as SVT-AV1 and libaom-AV1.
    """
    def get_keyframe_interval(self, video_stream:VideoStream, multiplier:int) -> str:
        """
        Computes the keyframe interval based on the video frame rate.
        
        Args:
            video_stream (VideoStream): The video stream being processed.
            multiplier (int): The multiplier to determine the keyframe interval.
        
        Returns:
            str: The computed keyframe interval as a string.
        """
        frame_rate = video_stream.frame_rate if video_stream.frame_rate else DEFAULT_FRAME_RATE
        interval = round(frame_rate * multiplier)
        return str(interval)
    
class SVTAV1Encoder(AV1Encode):
    """
    Handles encoding using the SVT-AV1 encoder.
    SVT-AV1 is an efficient and scalable AV1 encoder developed by Intel and Netflix,
    providing a balance between speed and compression efficiency.
    """
    DEFAULT_CRF = DEFAULT_CRF_AV1

    DEFAULT_PRESET = DEFAULT_PRESET_AV1

    def __init__(self, media_file: MediaFile, preset: Union[str, int, None] = None, crf: Union[str, int, None] = None,
                 tune:int = 0, fast_decode: int = 1, film_grain: int = 0, film_grain_denoise: bool = True,
                 delete_original: bool = False, verify: bool = False, 
                 delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={'av1'}, **kwargs):
        """
        Initializes the SVT-AV1 Encoder with user-defined encoding parameters.
        
        - SVT-AV1 supports high-performance encoding with various presets.
        - Uses film grain synthesis to enhance the perceived quality of grainy videos.
        - Supports tuning for visual quality (sharpness) and decoding speed optimizations.
        
        Args:
            media_file (MediaFile): The media file to be encoded.
            preset (Optional[int]): Encoding speed vs. efficiency (0-13). Lower values mean better compression but slower encoding.
            crf (Optional[int]): Constant Rate Factor (0-63). Lower values produce higher quality but larger file sizes.
            tune (int): Quality tuning mode (0 = sharpness, 1 = PSNR). Default is 0 (sharpness).
            fast_decode (int): Optimize for decoding speed (0-3). Higher values make playback easier at the cost of efficiency.
            film_grain (int): Film Grain Synthesis level (0-50). Higher values add more grain to the video.
            film_grain_denoise (bool): Enables or disables film grain denoising before encoding.
            delete_original (bool): Whether to delete the original media file after encoding.
            verify (bool): Whether to verify encoding quality with VMAF.
            delete_threshold (float): Threshold for deciding whether to delete the original file.
            output_dir (Optional[str]): Directory for the output files.
            ignore_codec (Set[str]): Codecs to be ignored for re-encoding (defaults to skipping AV1 re-encoding).
        """
        if crf:
            crf = max(0, min(int(crf), 63)) # Clamp between 0-63
        if preset:
            preset = max(0, min(int(preset), 13)) # Note that preset 13 is only meant for debugging and running fast convex-hull encoding.
        
        super().__init__(media_file, encoder="libsvtav1", preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, 
                         output_dir=output_dir, ignore_codec=ignore_codec)
        
        self.tune = 0 if tune == 0 else 1  # Only 0 or 1 allowed
        self.fast_decode = max(0, min(fast_decode, 3))  # Clamp between 0-3
        self.film_grain = max(0, min(film_grain, 50))  # Clamp between 0-50
        self.film_grain_denoise = 0 if film_grain_denoise == 0 else 1  # Only 0 or 1 allowed
        self.logger.debug(f'🔹 {self.__class__.__name__} initialized for "{media_file.file_path}"')

    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """
        Prepares FFmpeg video encoding arguments specific to SVT-AV1.
        Adds film grain synthesis, fast decoding, and keyframe placement options.
        """
        video_args = super().prepare_video_args('-preset')

        append_args = ["-svtav1-params", f"tune={self.tune}:fast-decode={self.fast_decode}:film-grain={self.film_grain}:film-grain-denoise={self.film_grain_denoise}"]

        

        for stream, arg in video_args.items():
            if 'copy' not in arg:
                keyframe_interval = self.get_keyframe_interval(stream, 5)
                keyframe_interval_args = ["-g", keyframe_interval]
                arg.extend(keyframe_interval_args)
                arg.extend(append_args)
        
        self.logger.info(f'🔹 Tune: {self.tune} | Fast Decode: {self.fast_decode} | Film Grain: {self.film_grain} | Film Grain Denoise: {self.film_grain_denoise}')

        return video_args


class LibaomAV1Encoder(AV1Encode):
    """
    Handles AV1 encoding using the libaom-av1 encoder.
    libaom is the reference implementation of AV1, providing a variety of rate-control options.
    """

    # 8-10% quality loss
    DEFAULT_CRF = DEFAULT_CRF_AV1

    DEFAULT_PRESET = DEFAULT_PRESET_AV1

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 delete_original: bool = False, verify: bool = False, 
                 delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None, 
                 ignore_codec:Set[str]={'av1'}, **kwargs):
        """
        Initializes the libaom-AV1 encoder.
        
        - Supports constant quality (CRF) encoding for optimal visual fidelity.
        - Enables row-based multi-threading for improved CPU utilization.
        - Uses constrained quality (CQ) mode if -b:v is set.
        """
        super().__init__(media_file, encoder="libaom-av1", preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, 
                         output_dir=output_dir, ignore_codec=ignore_codec)


    def get_keyint_min(self, video_stream:VideoStream, multiplier:int) -> str:
        """
        Returns the minimum keyframe interval for libaom-AV1.
        
        In libaom, the `-keyint_min` parameter should be set equal to the `-g` parameter for best performance.
        """
        return self.get_keyframe_interval(video_stream, multiplier)

    def prepare_video_args(self) -> List[List[str]]:
        """
        Prepares FFmpeg video encoding arguments specific to libaom-AV1.
        """
        video_args = super().prepare_video_args('-cpu-used')

        keyint_min_log = []

        append_args = ["-row-mt", "1", "-b:v", "0"]

        for stream, arg in video_args.items():
            if 'copy' not in arg:
                keyint_min = self.get_keyint_min(stream, 10)
                key_int_args = ["-g", self.get_keyframe_interval(stream, 10), "-keyint_min", keyint_min]
                arg.extend(key_int_args)
                arg.extend(append_args)

                keyint_min_log.append(keyint_min)
            else:
                keyint_min_log.append("copy")
        
        self.logger.info(f'🔹 Keyint Min: {", ".join(keyint_min_log)}')

        return video_args