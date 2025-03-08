from ..media import MediaFile, VideoStream
from .encoder import PresetCRFEncoder
from ..config import *
from typing import List, Dict, Optional, Set, Union

class HevcEncoder(PresetCRFEncoder):
    """
    Handles HEVC (H.265) encoding with resolution-based parameter selection.
    
    This class extends PresetCRFEncoder and applies HEVC-specific settings, 
    such as selecting the x265 encoder (`libx265`) and ensuring proper stream tagging.
    """

    SUPPORTED_PIXEL_FORMATS = [
        "yuv420p", "yuvj420p", "yuv422p", "yuvj422p", "yuv444p", "yuvj444p", "gbrp",
        "yuv420p10le", "yuv422p10le", "yuv444p10le", "gbrp10le",
        "yuv420p12le", "yuv422p12le", "yuv444p12le", "gbrp12le",
        "gray", "gray10le", "gray12le"
    ]

    DEFAULT_PRESET = DEFAULT_PRESET_HEVC

    DEFAULT_CRF = DEFAULT_CRF_HEVC

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Union[str, int, None] = None,
                 delete_original: bool = DEFAULT_DELETE_ORIGIN, verify: bool = DEFAULT_VERIFY,
                  delete_threshold:float=DEFAULT_DELETE_THRESHOLD, check_size:bool=DEFAULT_CHECK_SIZE,
                  output_dir: Optional[str] = None, ignore_codec:Set[str]={'hevc'}, **kwargs):
        """
        Initializes the HEVC encoder with default settings for x265 encoding.
        
        Args:
            media_file (MediaFile): The media file to be encoded.
            preset (Optional[str], optional): The preset setting for encoding speed. Defaults to None.
            crf (Union[str, int, None], optional): The CRF value for quality control. Defaults to None.
            delete_original (bool, optional): Whether to delete the original file. Defaults to DEFAULT_DELETE_ORIGIN.
            verify (bool, optional): Whether to verify encoding quality with VMAF. Defaults to DEFAULT_VERIFY.
            delete_threshold (float, optional): Minimum VMAF score for deletion. Defaults to DEFAULT_DELETE_THRESHOLD.
            output_dir (Optional[str], optional): Directory for output files. Defaults to None.
            ignore_codec (Set[str], optional): Set of codecs that should not be re-encoded. Defaults to {"hevc"}.
            **kwargs: Additional keyword arguments passed to the superclass.
        """
        # Calls the parent class constructor with 'libx265' as the encoder
        super().__init__(media_file, encoder="libx265", preset=preset, crf=crf,
                         delete_original=delete_original, check_size=check_size, verify=verify, 
                         delete_threshold=delete_threshold, output_dir=output_dir,
                         ignore_codec=ignore_codec)
    
    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """
        Prepares video conversion arguments specific to HEVC encoding.
        
        This function ensures that:
        - Streams already encoded in HEVC are copied instead of re-encoded.
        - If re-encoding is required, the appropriate preset and CRF values are applied.
        - Proper HEVC tagging (hvc1) is enforced.
        
        Returns:
            Dict[VideoStream, List[str]]: A mapping of video streams to their respective FFmpeg arguments.
        """
        video_args = {} # Dictionary to store encoding arguments
        
        preset_log = [] # Logs the presets used
        crf_log = [] # Logs the CRF values used

        counter = 0 # FFmpeg stream index counter
        for video_stream in self.media_file.video_info:
            sub_args = []
            if video_stream.codec in self.ignore_codec:
                # If the codec is already HEVC, copy the stream instead of encoding
                sub_args.extend(video_stream.map_prefix(counter))
                if video_stream.tag == "hev1":
                    # Convert hev1 to hvc1 for better compatibility
                    self.logger.info(f"🔄 Remuxing '{self.media_file.file_path}' from hev1 to hvc1 (no re-encoding).")
                    sub_args.extend(["copy", "-tag:v", "hvc1"])
                else:
                    # Otherwise, encode using HEVC with preset and CRF settings
                    sub_args.extend(["copy"])
                    self.logger.warning(f"⚠️ Skipping HEVC encoding: {self.media_file.file_path} is already in the desired format.")
                counter += 1
                preset_log.append("copy")
                crf_log.append("copy")
            else:
                sub_args.extend(video_stream.map_prefix(counter))
                sub_args.extend([self.encoder, # Use libx265 encoder
                                 "-preset", self.get_preset(video_stream), # Apply preset
                                 "-tag:v", "hvc1", # Ensure proper stream tagging
                                 "-crf", self.get_crf(video_stream)]) # Apply CRF
                counter += 1

                # Log preset and CRF values
                preset_log.append(self.get_preset(video_stream))
                crf_log.append(self.get_crf(video_stream))
            
            video_args[video_stream] = sub_args
        
        self.logger.debug(f"🎬 Prepared video arguments: {video_args.values()}")
        self.logger.info(f'🔹 HEVC encoding initialized for "{self.media_file.file_name}" | Preset: {", ".join(preset_log)} | CRF: {", ".join(crf_log)}')
        return video_args
