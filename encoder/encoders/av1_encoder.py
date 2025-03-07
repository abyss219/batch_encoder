from ..config import *
from .encoder import PresetCRFEncoder
from ..media import MediaFile, VideoStream
from typing import Type, Optional, List, Dict, Set, Union
from abc import ABC, abstractmethod

class AV1Encode(PresetCRFEncoder, ABC):
    def __init__(self, media_file: MediaFile, encoder: str, preset: Union[str, int, None] = None, 
                 crf: Union[str, int, None] = None, delete_original: bool=DEFAULT_DELETE_ORIGIN, 
                 verify:bool=DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={}):

        super().__init__(media_file, encoder=encoder, preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, 
                         output_dir=output_dir, ignore_codec=ignore_codec)

        
    def get_keyframe_interval(self, video_stream:VideoStream, multiplier:int) -> str:
        '''
        Reference: By default, SVT-AV1's keyframe interval is 2-3 seconds, 
        which is quite short for most use cases. 
        Consider changing this up to 5 seconds (or higher) 
        with the -g option (or keyint in svtav1-params); 
        -g 120 for 24 fps content, -g 150 for 30 fps, etc.
        '''
        frame_rate = video_stream.frame_rate if video_stream.frame_rate else DEFAULT_FRAME_RATE
        interval = round(frame_rate * multiplier)
        return str(interval)
    
class SVTAV1Encoder(AV1Encode):

    DEFAULT_CRF = DEFAULT_CRF_AV1

    DEFAULT_PRESET = DEFAULT_PRESET_AV1

    def __init__(self, media_file: MediaFile, preset: Union[str, int, None] = None, crf: Union[str, int, None] = None,
                 tune:int = 0, fast_decode: int = 1, film_grain: int = 0, film_grain_denoise: bool = True,
                 delete_original: bool = False, verify: bool = False, 
                 delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={'av1'}, **kwargs):
        """
        Initializes the SVT-AV1 Encoder with user-defined encoding parameters.
        
        :param media_file: The media file to be encoded.
        :param preset: Encoding speed vs. efficiency (0-13). Lower values mean better compression but slower encoding.
                       Default is None, meaning it falls back to the superclass default.
        :param crf: Constant Rate Factor (0-63). Lower values produce higher quality but larger file sizes.
                    Default is None, meaning it falls back to the superclass default.
        :param tune: Quality tuning mode (0 = sharpness, 1 = PSNR). Default is 1 (PSNR optimization).
        :param fast_decode: Optimize for decoding speed (0-3). Higher values make playback easier at the cost of efficiency.
                            Default is 0 (no fast decode optimizations).
        :param film_grain: Film Grain Synthesis level (0-50). Higher values add more grain back to the video after encoding.
                           Default is 0 (no grain synthesis).
        :param film_grain_denoise: Enables or disables film grain denoising before encoding.
                                   True (1) = Denoising enabled, False (0) = Denoising disabled.
                                   Default is True (denoising enabled).
        :param delete_original: If True, deletes the original media file after successful encoding. Default is False.
        :param verify: If True, performs a verification check after encoding. Default is False.
        :param delete_threshold: Threshold (float) used for deciding whether to delete the original file. Default is defined by DEFAULT_DELETE_THRESHOLD.
        :param output_dir: Optional output directory for the encoded file. If None, the output file is placed in the same directory as the input.
        :param kwargs: Additional arguments to be passed to the superclass.
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
        """Prepare video conversion arguments."""
        video_args = super().prepare_video_args('-preset')

        append_args = ["-g", self.get_keyframe_interval(5), 
                       "-svtav1-params", f"tune={self.tune}:fast-decode={self.fast_decode}:film-grain={self.film_grain}:film-grain-denoise={self.film_grain_denoise}"]

        for arg in video_args.values():
            if 'copy' not in arg:
                arg.extend(append_args)
        
        self.logger.info(f'🔹 Tune: {self.tune} | Fast Decode: {self.fast_decode} | Film Grain: {self.film_grain} | Film Grain Denoise: {self.film_grain_denoise}')

        return video_args


class LibaomAV1Encoder(AV1Encode):
    """Handles AV1 encoding with resolution-based parameter selection."""

    # 8-10% quality loss
    DEFAULT_CRF = DEFAULT_CRF_AV1

    DEFAULT_PRESET = DEFAULT_PRESET_AV1

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 delete_original: bool = False, verify: bool = False, 
                 delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None, 
                 ignore_codec:Set[str]={'av1'}, **kwargs):
        super().__init__(media_file, encoder="libaom-av1", preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, 
                         output_dir=output_dir, ignore_codec=ignore_codec)


    def get_keyint_min(self, video_stream:VideoStream, multiplier:int) -> str:
        return self.get_keyframe_interval(video_stream, multiplier)

    def prepare_video_args(self) -> List[List[str]]:
        """Prepare video conversion arguments."""
        video_args = super().prepare_video_args('-cpu-used')

        keyint_min_log = []

        append_args = ["-row-mt", "1", "-b:v", "0"]

        for stream, arg in video_args.items():
            if 'copy' not in arg:
                keyint_min = self.get_keyint_min(stream, 10)
                key_int_args = ["-g", self.get_keyint_min(stream, 10), "-keyint_min", keyint_min]
                arg.extend(key_int_args)
                arg.extend(append_args)

                keyint_min_log.append(keyint_min)
            else:
                keyint_min_log.append("copy")
        
        self.logger.info(f'🔹 Keyint Min: {", ".join(keyint_min_log)}')

        return video_args