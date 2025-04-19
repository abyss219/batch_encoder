from typing import Optional, List, Dict, Set, Union
from abc import ABC
from config import load_config
from .encoder import PresetCRFEncoder
from ..media import MediaFile, VideoStream

config = load_config()


class AV1Encoder(PresetCRFEncoder, ABC):
    """
    Base class for AV1 encoding, inheriting from `PresetCRFEncoder`.

    This class serves as a foundation for specific AV1 encoders such as SVT-AV1 and libaom-AV1.
    It provides AV1-specific encoding logic, including keyframe interval calculations.

    Key Features:
    - Supports AV1 encoding with customizable presets and CRF values.
    - Provides a method for calculating optimal keyframe intervals based on frame rate.
    - Serves as a base for encoder-specific implementations (e.g., SVT-AV1, libaom-AV1).
    """

    def get_keyframe_interval(self, video_stream: VideoStream, multiplier: int) -> str:
        """
        Computes the keyframe interval based on the video frame rate.

        The keyframe interval is determined using a multiplier, where:
        - A higher multiplier results in fewer keyframes (better compression).
        - A lower multiplier results in more keyframes (better seekability and fast scrubbing).

        If the frame rate is unknown, a default value (`DEFAULT_FRAME_RATE`) is used.

        Args:
            video_stream (VideoStream): The video stream being processed.
            multiplier (int): The multiplier to determine the keyframe interval.

        Returns:
            str: The computed keyframe interval as a string.
        """
        frame_rate = (
            video_stream.frame_rate
            if video_stream.frame_rate
            else config.general.default_frame_rate
        )
        interval = round(frame_rate * multiplier)
        return str(interval)


class SVTAV1Encoder(AV1Encoder):
    """
    Handles encoding using the SVT-AV1 encoder.

    SVT-AV1 (Scalable Video Technology for AV1) is a high-performance AV1 encoder
    developed by Intel and Netflix. It provides a balance between speed and quality
    through various encoding parameters, including presets, CRF, tuning metrics,
    and fast decode optimizations.

    Key Features:
    - Uses `libsvtav1` for AV1 encoding.
    - Supports CRF-based encoding (1-63) for efficient compression.
    - Provides configurable presets (1 to 13) for speed vs. quality trade-offs.
    - Includes tuning modes for Visual Quality (VQ), PSNR, and SSIM optimization.
    - Supports fast decode optimizations to reduce CPU load at the cost of compression efficiency.
    - Defaults to a 5 temporal layer structure but may override with hierarchical levels.
    """

    DEFAULT_CRF = config.svt_av1.crf

    DEFAULT_PRESET = config.svt_av1.preset

    SUPPORTED_PIXEL_FORMATS = ["yuv420p", "yuv420p10le"]

    def __init__(
        self,
        media_file: MediaFile,
        preset: Optional[int] = None,
        crf: Optional[int] = None,
        tune: int = config.svt_av1.tune,
        fast_decode: int = config.svt_av1.fast_decode,
        delete_original: bool = config.verify.delete_origin,
        check_size: bool = config.verify.check_size,
        verify: bool = config.verify.verify,
        delete_threshold: float = config.verify.delete_threshold,
        output_dir: Optional[str] = None,
        ignore_codec: Set[str] = {"av1"},
        debug=False,
        **kwargs,
    ):
        """
        Initializes the SVT-AV1 Encoder with user-defined encoding parameters.

        This constructor sets up SVT-AV1 encoding with options for tuning visual quality,
        controlling encoding speed, and optimizing playback performance.

        Args:
            media_file (MediaFile): The media file to be encoded.
            preset (Optional[Union[str, int]], optional): Encoding speed/efficiency preset (1 to 13).
                - Lower values provide better compression but slower encoding.
                - Higher values prioritize speed over compression.
            crf (Optional[Union[str, int]], optional): Constant Rate Factor (1-63).
                - Controls the tradeoff between quality and file size.
                - Lower values mean higher quality but larger file sizes.
                - CRF 35 is the default balanced setting.
            tune (int): Quality tuning metric (0-2).
                - 0: Optimized for perceptual visual quality (VQ).
                - 1: Optimized for PSNR (Peak Signal-to-Noise Ratio).
                - 2: Optimized for SSIM (Structural Similarity Index).
            fast_decode (int): Enables decoding speed optimizations (0-2).
                - 0: No optimization (maximum compression efficiency, slower decoding).
                - 1-2: Increasing levels of optimization for faster decoding.
            delete_original (bool): Whether to delete the original media file after encoding.
                - True: Removes original file if encoding is successful.
                - False (default): Keeps original file.
            check_size (bool, optional): Whether to check if the encoded file is smaller than the original before deletion.
            verify (bool): Whether to verify encoding quality using VMAF.
            delete_threshold (float): Minimum acceptable VMAF score to allow deletion of the original file.
            output_dir (Optional[str]): Directory for storing encoded files.
                - Defaults to the same directory as the input file.
            ignore_codec (Set[str]): Codecs that should be skipped for re-encoding.
                - Defaults to ignoring AV1 streams to prevent redundant encoding.
        """
        if crf:
            crf = max(1, min(int(crf), 63))  # Clamp between 1-63
        if preset:
            preset = max(
                1, min(int(preset), 13)
            )  # Note that preset 13 is only meant for debugging and running fast convex-hull encoding.

        self.tune = str(tune)  # Only 0, 1, 2 allowed. [0 = VQ, 1 = PSNR, 2 = SSIM]

        super().__init__(
            media_file,
            encoder="libsvtav1",
            preset=preset,
            crf=crf,
            delete_original=delete_original,
            verify=verify,
            delete_threshold=delete_threshold,
            check_size=check_size,
            output_dir=output_dir,
            ignore_codec=ignore_codec,
            debug=debug,
        )

        if int(tune) < 0 or int(tune) > 2:
            raise ValueError("Tune values must be between 0 and 2.")

        self.fast_decode = max(0, min(int(fast_decode), 2))  # Clamp between 0-2
        self.logger.debug(
            f'🔹 {self.__class__.__name__} initialized for "{media_file.file_path}"'
        )

    def get_fast_decode(self, video_stream: VideoStream) -> str:
        """
        Retrieves the fast decode setting for the given video stream.

        Fast decode is an SVT-AV1 feature that optimizes playback performance at the cost of compression efficiency.

        Args:
            video_stream (VideoStream): The video stream to encode.

        Returns:
            str: The fast decode setting as a string.
        """
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

        This function ensures:
        - Streams already encoded in AV1 are copied instead of re-encoded.
        - Encoding parameters are optimized for speed, quality, and decoding efficiency.
        - Fast decode and tuning options are applied if specified.
        - Proper keyframe intervals are set for better seeking performance.

        Steps:
        1. Calls `prepare_video_args()` from `PresetCRFEncoder` to get the base encoding arguments.
        2. If the stream is being encoded, applies SVT-AV1-specific parameters.
        3. Adds fast decode settings, tune parameters, and keyframe intervals.
        4. Logs the selected encoding settings.

        Returns:
            Dict[VideoStream, List[str]]: A dictionary mapping video streams to their FFmpeg encoding arguments.
        """
        video_args = super().prepare_video_args("-preset")

        for stream, arg in video_args.items():
            if "copy" not in arg:
                fast_decode = self.get_fast_decode(
                    stream
                )  # fast decode is only availiable for presets from 5 to 10
                if fast_decode:
                    fast_decode_args = f":fast-decode={self.fast_decode}"
                else:
                    fast_decode_args = ""

                append_args = ["-svtav1-params", f"tune={self.tune}{fast_decode_args}"]

                keyframe_interval = self.get_keyframe_interval(stream, 5)
                keyframe_interval_args = ["-g", keyframe_interval]
                arg.extend(keyframe_interval_args)
                arg.extend(append_args)

        self.logger.info(f"🔹 Tune: {self.tune} | Fast Decode: {self.fast_decode}")

        return video_args

    def _get_filename_suffix(self) -> str:
        """
        Generates a filename suffix based on encoding settings.

        The suffix contains the encoder class name, CRF value, and tune mode,
        ensuring that encoded files are properly labeled and distinguishable.

        Returns:
            str: The filename suffix reflecting the encoding parameters.
        """
        suffix = super()._get_filename_suffix()
        return f"{suffix}_tune-{self.tune}"


class LibaomAV1Encoder(AV1Encoder):
    """
    Handles AV1 encoding using the libaom-AV1 encoder.

    libaom-AV1 is the reference implementation of AV1 developed by AOMedia. It provides
    extensive rate-control options, multi-threading support, and high-quality encoding
    at the cost of slower performance compared to other AV1 encoders like SVT-AV1.

    Key Features:
    - Uses `libaom-av1` for AV1 encoding.
    - Supports CRF-based encoding for constant quality control.
    - Implements row-based multi-threading to optimize CPU utilization.
    - Enables constrained quality (CQ) mode when bitrate (`-b:v`) is set.
    - Adjusts keyframe intervals dynamically for better compression efficiency.
    """

    SUPPORTED_PIXEL_FORMATS = [
        "yuv420p",
        "yuv422p",
        "yuv444p",
        "gbrp",
        "yuv420p10le",
        "yuv422p10le",
        "yuv444p10le",
        "yuv420p12le",
        "yuv422p12le",
        "yuv444p12le",
        "gbrp10le",
        "gbrp12le",
        "gray",
        "gray10le",
        "gray12le",
    ]

    DEFAULT_CRF = config.libaom_av1.crf

    DEFAULT_PRESET = config.libaom_av1.preset

    def __init__(
        self,
        media_file: MediaFile,
        preset: Optional[int] = None,
        crf: Optional[int] = None,
        delete_original: bool = config.verify.delete_origin,
        verify: bool = config.verify.verify,
        delete_threshold: float = config.verify.delete_threshold,
        check_size: bool = config.verify.check_size,
        output_dir: Optional[str] = None,
        ignore_codec: Set[str] = {"av1"},
        debug=False,
        **kwargs,
    ):
        """
        Initializes the libaom-AV1 encoder.

        This constructor configures libaom-AV1 with appropriate encoding parameters,
        supporting multiple rate-control modes, keyframe placement adjustments, and
        multi-threading enhancements.

        Args:
            media_file (MediaFile): The media file to be encoded.
            preset (Optional[str], optional): Determines encoding speed vs. compression efficiency (`-cpu-used`).
                - Lower values provide better compression but slower encoding.
                - Higher values prioritize speed over compression.
                - Valid range: 0-8.
            crf (Optional[int], optional): Constant Rate Factor (1-63).
                - Controls the tradeoff between quality and file size.
                - Lower values result in higher quality and larger files.
                - CRF 0 enables **lossless encoding**.
            delete_original (bool, optional): Whether to delete the original file after encoding.
            verify (bool, optional): Whether to verify encoding quality using VMAF.
            delete_threshold (float, optional): Minimum VMAF score required to allow deletion of the original file.
            check_size (bool, optional): Whether to check if the encoded file is smaller than the original before deletion.
            output_dir (Optional[str], optional): Directory for storing encoded files.
            ignore_codec (Set[str], optional): Codecs that should be skipped for re-encoding.
                - Defaults to ignoring AV1 streams to prevent redundant encoding.

        Raises:
            ValueError: If `preset` is out of the valid range (0-8).
            ValueError: If `crf` is out of the valid range (1-63).
            ValueError: If `delete_threshold` is not between 0 and 100.

        """
        if crf:
            crf = max(1, min(int(crf), 63))  # Clamp between 0-63
        if preset:
            preset = max(0, min(int(preset), 8))

        delete_threshold = max(0, min(delete_threshold, 100))

        super().__init__(
            media_file,
            encoder="libaom-av1",
            preset=preset,
            crf=crf,
            delete_original=delete_original,
            verify=verify,
            delete_threshold=delete_threshold,
            check_size=check_size,
            output_dir=output_dir,
            ignore_codec=ignore_codec,
            debug=debug,
        )

    def get_keyint_min(self, video_stream: VideoStream, multiplier: int) -> str:
        """
        Returns the minimum keyframe interval for libaom-AV1.

        In libaom-AV1, the `-keyint_min` parameter should be set equal to the `-g` (max keyframe interval)
        parameter for optimal performance. This ensures consistent keyframe placement, improving compression
        efficiency and seekability.

        Args:
            video_stream (VideoStream): The video stream being processed.
            multiplier (int): The multiplier used to compute the keyframe interval.

        Returns:
            str: The computed minimum keyframe interval as a string.
        """
        return self.get_keyframe_interval(video_stream, multiplier)

    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """
        Prepares FFmpeg video encoding arguments specific to libaom-AV1.

        This method configures encoding parameters such as:
        - Row-based multi-threading (`-row-mt 1`) for better CPU utilization.
        - Constrained quality mode (`-b:v 0`) to enable CRF-based rate control.
        - Keyframe interval settings (`-g` and `-keyint_min`) to optimize compression.

        Steps:
        1. Calls `prepare_video_args()` from `PresetCRFEncoder` to get the base encoding arguments.
        2. If the stream is being encoded, applies libaom-AV1-specific parameters:
           - Sets `-g` (max keyframe interval) based on frame rate.
           - Ensures `-keyint_min` matches `-g` for optimal keyframe spacing.
           - Enables row-based multi-threading.
           - Activates constrained quality mode (`-b:v 0`).
        3. Logs the selected keyframe interval settings.

        Returns:
            Dict[VideoStream, List[str]]: A dictionary mapping video streams to their FFmpeg encoding arguments.
        """
        video_args = super().prepare_video_args("-cpu-used")

        keyint_min_log = []

        append_args = ["-row-mt", "1", "-b:v", "0"]

        for stream, arg in video_args.items():
            if "copy" not in arg:
                keyint_min = self.get_keyint_min(stream, 10)
                key_int_args = [
                    "-g",
                    self.get_keyframe_interval(stream, 10),
                    "-keyint_min",
                    keyint_min,
                ]
                arg.extend(key_int_args)
                arg.extend(append_args)

                keyint_min_log.append(keyint_min)
            else:
                keyint_min_log.append("copy")

        self.logger.info(f'🔹 Keyint Min: {", ".join(keyint_min_log)}')

        return video_args
