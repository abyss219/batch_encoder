from .av1_encoder import SVTAV1Encoder
from .hevc_encoder import HevcEncoder
from .encoder import PresetCRFEncoder
from ..media import MediaFile, VideoStream
from ..config import EncodingStatus
from typing import Type, Optional, List, Dict
import subprocess
import time
import re
import os
from tqdm import tqdm

def get_custom_encoding_class(codec: str) -> Type[PresetCRFEncoder]:
    """
    Dynamically creates a custom encoding class that inherits from either HevcEncoder or AV1Encoder,
    based on the specified codec type.
    
    Args:
        codec (str): The codec type to use ("hevc" or "av1").
    
    Returns:
        Type[PresetCRFEncoder]: A dynamically generated class inheriting from the appropriate encoder.
    
    Raises:
        ValueError: If an unsupported codec is provided.
    """
    if codec not in {"hevc", "av1"}:
        raise ValueError(f"❌ Invalid codec: '{codec}'. Supported codecs: 'hevc', 'av1'.")

    # Selects the parent class based on the codec type
    parent_class: Type[PresetCRFEncoder] = HevcEncoder if codec == "hevc" else SVTAV1Encoder

    class CustomEncoding(parent_class):
        """
        A dynamically created encoding class that inherits from either HevcEncoder or AV1Encoder.
        Provides additional features like denoising and efficient codec handling.
        """

        # Dictionary of denoising presets
        NLMEANS_SETTINGS = {
            "light": "nlmeans=s=1.0:p=3:r=7",      # Ultra-Light Denoising (Almost No Detail Loss)
            "mild": "nlmeans=s=1.5:p=5:r=9",       # Balanced Denoising (Mild but Effective) - Recommended
            "moderate": "nlmeans=s=2.5:p=7:r=11",  # Moderate Denoising (Good for Noisy Night Videos)
            "heavy": "nlmeans=s=4.0:p=9:r=15"      # Heavy Denoising (For Strong Noise & Film Restoration)
        }

        NLMEANS_PIXEL_FORMATS = [
            "yuv420p",  # 4:2:0 chroma subsampling, 8-bit, YUV
            "yuv422p",  # 4:2:2 chroma subsampling, 8-bit, YUV
            "yuv410p",  # 4:1:0 chroma subsampling, 8-bit, YUV
            "yuv411p",  # 4:1:1 chroma subsampling, 8-bit, YUV
            "yuv440p",  # 4:4:0 chroma subsampling, 8-bit, YUV
            "yuv444p",  # 4:4:4 chroma subsampling, 8-bit, YUV
            "yuvj444p", # 4:4:4 full-range chroma subsampling, 8-bit, YUV
            "yuvj440p", # 4:4:0 full-range chroma subsampling, 8-bit, YUV
            "yuvj422p", # 4:2:2 full-range chroma subsampling, 8-bit, YUV
            "yuvj420p", # 4:2:0 full-range chroma subsampling, 8-bit, YUV
            "yuvj411p", # 4:1:1 full-range chroma subsampling, 8-bit, YUV
            "gray8",    # Grayscale, 8-bit
            "gbrp"      # Planar RGB, 8-bit
        ]


        # List of efficient codecs that do not require re-encoding
        EFFICIENT_CODEC = {"av1", "hevc", "vp9", "vvc", "theora"}

        def __init__(self, media_file:MediaFile, denoise:Optional[str]=None, delete_original:bool=True, check_size:bool=True, verify:bool=False, **kwargs):
            """
            Initializes the custom encoding class.
            
            Args:
                media_file (MediaFile): The media file to be encoded.
                denoise (Optional[str]): Denoising level ("light", "mild", "moderate", "heavy"), default is None.
                delete_original (bool): If True, deletes the original file after encoding. Default is True.
                verify (bool): If True, performs a verification check after encoding. Default is False.
            """
            super().__init__(media_file, delete_original=delete_original, check_size=check_size,
                             verify=verify, 
                             ignore_codec=self.EFFICIENT_CODEC, **kwargs)

            self.denoise = denoise # Stores the selected denoising level

        def prepare_cmd(self) -> Optional[List[str]]:
            """
            Prepares the FFmpeg command for encoding, including optional denoising and progress tracking.
            
            Returns:
                Optional[List[str]]: The FFmpeg command arguments, or None if encoding is skipped.
            """
            cmd = super().prepare_cmd()
            
            if cmd:
                pipeline_args = ["-progress", "pipe:1", "-nostats"] # Progress tracking

                # Modify the command by inserting denoise and progress args before the output file
                cmd = cmd[:-1] + pipeline_args + cmd[-1:]
            return cmd

        def get_duration(self) -> Optional[float]:
            """
            Retrieves the duration of the video file in seconds.
            
            Returns:
                Optional[float]: Duration of the video file.
            """
            return float(self.media_file.video_info[0].duration)
            
        def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
            """
            Prepares FFmpeg video encoding arguments specific to libaom-AV1.
            """
            video_args = super().prepare_video_args()

            denoise_args = self.NLMEANS_SETTINGS.get(self.denoise, "") # Retrieve denoise settings
            
            if denoise_args:
                for stream, arg in video_args.items():
                    if 'copy' not in arg:
                        vf_format = self.get_pix_fmt(stream, self.NLMEANS_PIXEL_FORMATS)
                        
                        vf_format_args = ["-vf", f"format={vf_format},{denoise_args}"]
                        
                        arg.extend(vf_format_args)
                self.logger.info(f"Applied denoise. level: {denoise_args}")

            return video_args



        def _encode(self) -> EncodingStatus:
            """
            Performs the encoding process with real-time progress tracking.
            
            Returns:
                EncodingStatus: The final encoding status (SUCCESS, FAILED, or SKIPPED).
            """
            ffmpeg_cmd = self.prepare_cmd()
            if not ffmpeg_cmd:
                self.logger.warning(f"⚠️ Skipping encoding: {self.media_file.file_path} (Already in desired format).")
                return EncodingStatus.SKIPPED
            
            self.logger.info(f"🚀 Final ffmpeg arg: {" ".join(ffmpeg_cmd)}")
            self.logger.debug(f"🎬 Starting encoding: {self.media_file.file_path}")

            # Get video duration
            duration = self.get_duration()
            pbar = tqdm(
                total=round(duration, 2),  # Total duration of the video
                unit="s",  # Unit is seconds since we're tracking time
                position=0,
                leave=True,
                dynamic_ncols=True,
                bar_format="{l_bar}{bar} | {n:.2f}/{total:.2f}s [{elapsed}<{remaining}{postfix}]"
            ) if duration else None

            start_time = time.time()
            
            # Start FFmpeg encoding process
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, # Suppress stderr output
                text=True,
                bufsize=1,  # Line-buffered
                universal_newlines=True,
                encoding='utf-8'
            )

            # Track encoding progress in real-time
            for line in process.stdout:
                self.logger.debug(f"FFmpeg: {line.strip()}")
                match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
                

                if match and duration:
                    hours, minutes, seconds = map(float, match.groups())
                    elapsed_time = hours * 3600 + minutes * 60 + seconds
                    if pbar:
                        progress_update = max(0, elapsed_time - pbar.n)
                        pbar.update(progress_update)

                        # Compute Encoding Speed (n / elapsed_s)
                        elapsed_real_time = time.time() - start_time
                        encoding_speed = elapsed_time / elapsed_real_time if elapsed_real_time > 0 else 0

                        # Update tqdm with correct speed
                        pbar.set_postfix_str(f"{encoding_speed:.4f}x")
                        # pbar.update(elapsed_time - pbar.n)  # Update tqdm progress

            process.wait()  # Ensure FFmpeg process completes
            if pbar:
                pbar.close()  # Close tqdm progress bar

            if process.returncode == 0:
                status = self.clean_up()
                self.logger.debug(f"✅ Encoding successful: {self.media_file.file_path}")
                return status
            else:
                self.logger.error(f"❌ Encoding failed: FFmpeg returned {process.returncode}")
                return EncodingStatus.FAILED

        def _get_filename_suffix(self) -> str:
            """
            Generates a filename suffix based on encoding settings.
            
            The suffix contains the encoder class name and CRF value.
            
            Returns:
                str: The filename suffix.
            """
            suffix = super()._get_filename_suffix()
            suffix = suffix.replace(self.__class__.__name__, self.__class__.__bases__[0].__name__)
            return suffix

    return CustomEncoding
