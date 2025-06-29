from __future__ import annotations
from typing import Type, Optional, List, Dict, Set
import subprocess
import time
import re
from tqdm import tqdm
from utils import color_text
from .av1_encoder import SVTAV1Encoder
from .hevc_encoder import HevcEncoder
from .encoder import PresetCRFEncoder
from ..media import MediaFile, VideoStream
from config import EncodingStatus


def get_custom_encoding_class(codec: str) -> Type[PresetCRFEncoder]:
    """
    Dynamically creates a custom encoding class that inherits from either HevcEncoder or AV1Encoder,
    based on the specified codec type.

    This function generates a subclass of the appropriate encoder type (`HevcEncoder` for HEVC encoding
    or `SVTAV1Encoder` for AV1 encoding). The generated class includes additional features such as:
    - Denoising filters (NLMeans).
    - Real-time encoding progress tracking.
    - Enhanced filename suffix handling.

    Args:
        codec (str): The codec type to use ("hevc" for H.265 or "av1" for AV1).

    Returns:
        Type[PresetCRFEncoder]: A dynamically generated class inheriting from the appropriate encoder.

    Raises:
        ValueError: If an unsupported codec is provided.
    """
    if codec not in {"hevc", "av1"}:
        raise ValueError(
            f"❌ Invalid codec: '{codec}'. Supported codecs: 'hevc', 'av1'."
        )

    # Selects the parent class based on the codec type
    parent_class: Type[PresetCRFEncoder] = (
        HevcEncoder if codec == "hevc" else SVTAV1Encoder
    )

    class CustomEncoder(parent_class):
        """
        A dynamically created encoding class that inherits from either HevcEncoder or AV1Encoder.

        This class extends the base encoder by adding:
        - **Denoising filters** using NLMeans.
        - **Real-time encoding progress tracking** with tqdm.
        - **Improved output filename handling** to reflect encoding settings.

        Supports both HEVC and AV1 encoding, with codec-specific optimizations.
        """

        # Dictionary of NLMeans denoising presets
        NLMEANS_SETTINGS = {
            "light": "nlmeans=s=1.0:p=3:r=7",  # Ultra-Light Denoising (Almost No Detail Loss)
            "mild": "nlmeans=s=1.5:p=5:r=9",  # Balanced Denoising (Mild but Effective) - Recommended
            "moderate": "nlmeans=s=2.5:p=7:r=11",  # Moderate Denoising (Good for Noisy Night Videos)
            "heavy": "nlmeans=s=4.0:p=9:r=15",  # Heavy Denoising (For Strong Noise & Film Restoration)
        }

        # Supported pixel formats for NLMeans filtering
        NLMEANS_PIXEL_FORMATS = [
            "yuv420p",  # 4:2:0 chroma subsampling, 8-bit, YUV
            "yuv422p",  # 4:2:2 chroma subsampling, 8-bit, YUV
            "yuv410p",  # 4:1:0 chroma subsampling, 8-bit, YUV
            "yuv411p",  # 4:1:1 chroma subsampling, 8-bit, YUV
            "yuv440p",  # 4:4:0 chroma subsampling, 8-bit, YUV
            "yuv444p",  # 4:4:4 chroma subsampling, 8-bit, YUV
            "yuvj444p",  # 4:4:4 full-range chroma subsampling, 8-bit, YUV
            "yuvj440p",  # 4:4:0 full-range chroma subsampling, 8-bit, YUV
            "yuvj422p",  # 4:2:2 full-range chroma subsampling, 8-bit, YUV
            "yuvj420p",  # 4:2:0 full-range chroma subsampling, 8-bit, YUV
            "yuvj411p",  # 4:1:1 full-range chroma subsampling, 8-bit, YUV
            "gray8",  # Grayscale, 8-bit
            "gbrp",  # Planar RGB, 8-bit
        ]

        def __init__(
            self,
            media_file: MediaFile,
            denoise: Optional[str] = None,
            delete_original: bool = True,
            check_size: bool = True,
            verify: bool = False,
            ignore_codec: Set = {},
            **kwargs,
        ):
            """
            Initializes the custom encoding class.

            Extends the base encoder class by adding optional denoising support.

            Args:
                media_file (MediaFile): The media file to be encoded.
                denoise (Optional[str]): Denoising level ("light", "mild", "moderate", "heavy"), default is None.
                delete_original (bool): If True, deletes the original file after encoding. Default is True.
                check_size (bool): If True, checks if the encoded file is smaller before deleting the original.
                verify (bool): If True, performs a verification check after encoding. Default is False.
                ignore_codec (Set[str]): Codecs that should not be re-encoded.
                **kwargs: Additional parameters passed to the base encoder class.
            """
            super().__init__(
                media_file,
                delete_original=delete_original,
                check_size=check_size,
                verify=verify,
                ignore_codec=ignore_codec,
                **kwargs,
            )

            self.denoise = denoise  # Stores the selected denoising level

        def prepare_cmd(self) -> Optional[List[str]]:
            """
            Prepares the FFmpeg command for encoding.

            This method extends the base encoder's FFmpeg command by adding:
            - **Progress tracking** (`-progress pipe:1 -nostats`).

            Returns:
                Optional[List[str]]: The FFmpeg command arguments, or None if encoding is skipped.
            """
            cmd = super().prepare_cmd()

            if cmd:
                pipeline_args = ["-progress", "pipe:1", "-nostats"]  # Progress tracking

                # Modify the command by inserting denoise and progress args before the output file
                cmd = cmd[:-1] + pipeline_args + cmd[-1:]
            return cmd

        def get_duration(self) -> Optional[float]:
            """
            Retrieves the duration of the video file in seconds.

            Returns:
                Optional[float]: The total duration of the video file.
                If duration is None or 0, the function returns None.
            """
            duration = self.media_file.video_info[0].duration
            if duration:
                duration = float(duration)
                if duration == 0:
                    return None
                return duration
            return None

        def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
            """
            Prepares FFmpeg video encoding arguments, including optional denoising.

            - If a denoise level is specified, applies NLMeans denoising before encoding.
            - Ensures that the selected pixel format is compatible with NLMeans.

            Returns:
                Dict[VideoStream, List[str]]: The FFmpeg encoding arguments for each video stream.
            """
            video_args = super().prepare_video_args()

            denoise_args = self.NLMEANS_SETTINGS.get(
                self.denoise, ""
            )  # Retrieve denoise settings

            if denoise_args:
                for stream, arg in video_args.items():
                    if "copy" not in arg:
                        vf_format = self.get_pix_fmt(stream, self.NLMEANS_PIXEL_FORMATS)

                        vf_format_args = ["-vf", f"format={vf_format},{denoise_args}"]

                        arg.extend(vf_format_args)
                self.logger.info(f"Applied denoise. level: {denoise_args}")

            return video_args

        def _encode(self) -> EncodingStatus:
            """
            Performs the encoding process with real-time progress tracking.

            - Displays a progress bar using tqdm.
            - Tracks encoding speed (real-time vs. encoded time).
            - Waits for FFmpeg to complete before returning status.

            Returns:
                EncodingStatus: The final encoding status (SUCCESS, FAILED, or SKIPPED).
            """
            ffmpeg_cmd = self.prepare_cmd()
            if not ffmpeg_cmd:
                return EncodingStatus.SKIPPED
            self.logger.debug(f"🎬 Starting encoding: {self.media_file.file_path}")

            # Get video duration
            duration = self.get_duration()
            use_pbar = duration is not None

            if use_pbar:
                self.logger.info(
                    f"🚀 Final ffmpeg arg: {color_text(" ".join(str(arg) for arg in ffmpeg_cmd), 'reset', dim=True)}"
                )
                self.logger.debug(f"⏱️ Video duration: {duration:.2f} seconds")
                pbar = tqdm(
                    total=round(duration, 2),  # Total duration of the video
                    unit="s",  # Unit is seconds since we're tracking time
                    position=0,
                    leave=True,
                    dynamic_ncols=True,
                    bar_format="{l_bar}{bar} | {n:.2f}/{total:.2f}s [{elapsed}<{remaining}{postfix}]",
                )

                start_time = time.time()

                # Start FFmpeg encoding process
                process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,  # Suppress stderr output
                    bufsize=1,  # Line-buffered
                    universal_newlines=True,
                    encoding="utf-8",
                )

                # Track encoding progress in real-time
                for line in process.stdout:
                    if use_pbar:
                        match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)

                        if match and len(match.groups()) == 3:
                            try:
                                hours, minutes, seconds = map(float, match.groups())
                            except ValueError as e:
                                self.logger.warning(
                                    f"⚠️ Invalid time format in FFmpeg output: {match.groups()} ({e}). Progress bar disabled."
                                )
                                use_pbar = False  # disable future tqdm
                                pbar.close()
                                pbar = None
                                continue

                            elapsed_time = hours * 3600 + minutes * 60 + seconds
                            self.logger.debug(f"⏳ Encoded time: {elapsed_time:.2f}s")

                            progress_update = max(0, elapsed_time - pbar.n)
                            self.logger.debug(
                                f"📈 Progress update: +{progress_update:.2f}s"
                            )
                            pbar.update(progress_update)

                            # Compute Encoding Speed (n / elapsed_s)
                            elapsed_real_time = time.time() - start_time
                            encoding_speed = (
                                elapsed_time / elapsed_real_time
                                if elapsed_real_time > 0
                                else 0
                            )

                            # Update tqdm with correct speed
                            pbar.set_postfix_str(f"{encoding_speed:.4f}x")
                            # pbar.update(elapsed_time - pbar.n)  # Update tqdm progress

                process.wait()  # Ensure FFmpeg process completes
                if use_pbar:
                    pbar.close()  # Close tqdm progress bar

                if process.returncode == 0:
                    self.logger.debug(
                        f"✅ Encoding successful: {self.media_file.file_path}"
                    )
                    return EncodingStatus.SUCCESS
                else:
                    raise subprocess.CalledProcessError(
                        returncode=process.returncode, cmd=ffmpeg_cmd
                    )

            else:  # does not use pbar
                self.logger.warning(
                    "⚠️ Progress is not availiable. Fallback to ffmpeg output."
                )
                ffmpeg_cmd = [
                    arg
                    for arg in ffmpeg_cmd
                    if arg not in ("-progress", "pipe:1", "-nostats")
                ]
                self.logger.info(
                    f"🚀 Final ffmpeg arg: {color_text(" ".join(str(arg) for arg in ffmpeg_cmd), 'reset', dim=True)}"
                )
                subprocess.run(ffmpeg_cmd, check=True, encoding="utf-8")

            return EncodingStatus.SUCCESS

        def _get_filename_suffix(self) -> str:
            """
            Generates a filename suffix based on encoding settings.

            Ensures that the dynamically generated class name is replaced with the parent class name.

            Returns:
                str: The filename suffix reflecting the encoding settings.
            """
            suffix = super()._get_filename_suffix()
            suffix = suffix.replace(
                self.__class__.__name__, self.__class__.__bases__[0].__name__
            )
            return suffix

    return CustomEncoder
