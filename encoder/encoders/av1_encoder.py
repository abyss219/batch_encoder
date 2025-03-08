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
    providing a balance between speed and compression efficiency. It allows for a wide
    range of encoding optimizations, including tuning for perceptual quality and decoding
    speed.
    """
    DEFAULT_CRF = DEFAULT_CRF_SVTAV1

    DEFAULT_PRESET = DEFAULT_PRESET_SVTAV1

    def __init__(self, media_file: MediaFile, preset: Union[str, int, None] = None, crf: Union[str, int, None] = None,
                 tune:int = DEFAULT_SVTAV1_TUNE, fast_decode: int = DEFAULT_SVTAV1_FAST_DECODE,
                 delete_original: bool = DEFAULT_DELETE_ORIGIN, verify: bool = DEFAULT_VERIFY, 
                 delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={'av1'}, **kwargs):
        """
        Initializes the SVT-AV1 Encoder with user-defined encoding parameters.
        
        - SVT-AV1 supports high-performance encoding with various presets.
        - Supports tuning for visual quality (sharpness) and decoding speed optimizations.
        
        Args:
            media_file (MediaFile): The media file to be encoded.
            preset (Optional[int]): Determines encoding speed vs. efficiency (0-13).
                Lower values provide better compression at the cost of slower encoding.
                Higher values prioritize speed over compression.
                Preset 13 is mainly for debugging and not recommended for normal usage.
            crf (Optional[int]): Constant Rate Factor (0-63). Controls the tradeoff between quality and file size.
                Lower values mean higher quality but larger file sizes.
                CRF 35 is considered a good default for balanced quality.
                CRF 0 is currently unsupported for lossless encoding in SVT-AV1.
            tune (int): Quality tuning mode (0 or 1).
                0 (default): Optimized for perceptual sharpness.
                1: Optimized for PSNR (Peak Signal-to-Noise Ratio).
            fast_decode (int): Controls decoding speed optimizations (0-3).
                0: No optimization (max efficiency, slow decode).
                1-2: Increasing levels of optimization, reducing CPU load at the cost of compression efficiency.        
            delete_original (bool): Whether to delete the original media file after encoding.
                True: Removes original file if encoding is successful.
                False (default): Keeps original file.
            verify (bool): Whether to verify encoding quality using VMAF (Video Multi-Method Assessment Fusion).
                True: Runs a quality check before deleting the original file.
                False (default): Skips verification.
            delete_threshold (float): Minimum acceptable VMAF score to allow deletion of the original file.
            output_dir (Optional[str]): Directory for storing encoded files.
                Defaults to the same directory as the input file.
            ignore_codec (Set[str]): Codecs that should be skipped for re-encoding.
                Defaults to ignoring AV1 streams to prevent redundant encoding.
        """
        if crf:
            crf = max(0, min(int(crf), 63)) # Clamp between 0-63
        if preset:
            preset = max(0, min(int(preset), 13)) # Note that preset 13 is only meant for debugging and running fast convex-hull encoding.
        
        super().__init__(media_file, encoder="libsvtav1", preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, 
                         output_dir=output_dir, ignore_codec=ignore_codec)
        
        if tune < 0 or tune > 2:
            raise ValueError("Tune values must be between 0 and 2.")
        
        self.tune = str(tune) # Only 0, 1, 2 allowed. [0 = VQ, 1 = PSNR, 2 = SSIM]
        self.fast_decode = max(0, min(int(fast_decode), 2))  # Clamp between 0-2
        self.logger.debug(f'🔹 {self.__class__.__name__} initialized for "{media_file.file_path}"')
            
        

    def get_fast_decode(self, video_stream:VideoStream) -> str:
        # preset = int(self.get_preset(video_stream))
        # if preset >= 5 and preset <= 10:
        #     return str(self.fast_decode)
        # else:
        #     self.logger.warning(f"⚠️ Fast decode is only supported for preset between 0 and 5. "
        #                         "Fast decode will not be applied for stream {video_stream.index}.")
            
        #     return ""
        return str(self.fast_decode)

    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """
        Prepares FFmpeg video encoding arguments specific to SVT-AV1.
        Adds film grain synthesis, fast decoding, and keyframe placement options.
        """
        video_args = super().prepare_video_args('-preset')

        for stream, arg in video_args.items():
            if 'copy' not in arg:
                fast_decode = self.get_fast_decode(stream) # fast decode is only availiable for presets from 5 to 10
                if fast_decode:
                    fast_decode_args = f":fast-decode={self.fast_decode}"
                else:
                    fast_decode_args = ""
                
                append_args = ["-svtav1-params", f"tune={self.tune}{fast_decode_args}"]
                
                keyframe_interval = self.get_keyframe_interval(stream, 5)
                keyframe_interval_args = ["-g", keyframe_interval]
                arg.extend(keyframe_interval_args)
                arg.extend(append_args)
        
        self.logger.info(f'🔹 Tune: {self.tune} | Fast Decode: {self.fast_decode}')

        return video_args


class LibaomAV1Encoder(AV1Encode):
    """
    Handles AV1 encoding using the libaom-av1 encoder.
    libaom is the reference implementation of AV1, providing a variety of rate-control options.
    """

    # 8-10% quality loss
    DEFAULT_CRF = DEFAULT_CRF_LIBAMOAV1

    DEFAULT_PRESET = DEFAULT_PRESET_LIBAMOAV1

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 delete_original: bool = DEFAULT_DELETE_ORIGIN, verify: bool = DEFAULT_VERIFY, 
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

    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
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