from typing import List, Dict, Optional, Set, Union
from utils import color_text
from pathlib import Path
from ..media import MediaFile, VideoStream
from .encoder import PresetCRFEncoder
from config import load_config

config = load_config()


class HevcEncoder(PresetCRFEncoder):
    """
    Handles HEVC (H.265) encoding with resolution-based parameter selection.

    This class extends `PresetCRFEncoder` and applies HEVC-specific settings,
    ensuring efficient encoding with the x265 encoder (`libx265`). It also handles
    proper stream tagging for compatibility.

    Key Features:
    - Uses `libx265` for HEVC encoding.
    - Supports resolution-based CRF and preset selection.
    - Ensures proper HEVC tagging (`hvc1`) for playback compatibility.
    - Avoids redundant re-encoding for already HEVC-encoded streams.
    """

    SUPPORTED_PIXEL_FORMATS = [
        "yuv420p",
        "yuvj420p",
        "yuv422p",
        "yuvj422p",
        "yuv444p",
        "yuvj444p",
        "gbrp",
        "yuv420p10le",
        "yuv422p10le",
        "yuv444p10le",
        "gbrp10le",
        "yuv420p12le",
        "yuv422p12le",
        "yuv444p12le",
        "gbrp12le",
        "gray",
        "gray10le",
        "gray12le",
    ]

    DEFAULT_PRESET = config.hevc.preset

    DEFAULT_CRF = config.hevc.crf

    def __init__(
        self,
        media_file: MediaFile,
        preset: Optional[str] = None,
        crf: Optional[Union[str, int]] = None,
        delete_original: bool = config.verify.delete_origin,
        verify: bool = config.verify.verify,
        delete_threshold: float = config.verify.delete_threshold,
        check_size: bool = config.verify.check_size,
        output_dir: Optional[Union[str, Path]] = None,
        ignore_codec: Set[str] = {"hevc"},
        debug=False,
        **kwargs,
    ):
        """
        Initializes the HEVC encoder with default settings for x265 encoding.

        This constructor sets the encoder to `libx265`, applies HEVC-specific defaults, and
        ensures existing HEVC streams are copied rather than re-encoded.

        Args:
            media_file (MediaFile): The media file to be encoded.
            preset (Optional[str], optional): The preset setting for encoding speed. Defaults to None.
            crf (Optional[Union[str, int]], optional): The CRF value for quality control. Defaults to None.
            delete_original (bool, optional): Whether to delete the original file. Defaults to DEFAULT_DELETE_ORIGIN.
            verify (bool, optional): Whether to verify encoding quality with VMAF. Defaults to DEFAULT_VERIFY.
            delete_threshold (float, optional): Minimum VMAF score required for deletion. Defaults to DEFAULT_DELETE_THRESHOLD.
            check_size (bool, optional): Whether to check if the encoded file is smaller than the original. Defaults to DEFAULT_CHECK_SIZE.
            output_dir (Optional[str], optional): The directory for output files. Defaults to None (same as input file).
            ignore_codec (Set[str], optional): Set of codecs that should not be re-encoded. Defaults to {"hevc"}.
            **kwargs: Additional keyword arguments passed to the superclass.
        """
        # Calls the parent class constructor with 'libx265' as the encoder
        super().__init__(
            media_file,
            encoder="libx265",
            preset=preset,
            crf=crf,
            delete_original=delete_original,
            check_size=check_size,
            verify=verify,
            delete_threshold=delete_threshold,
            output_dir=output_dir,
            ignore_codec=ignore_codec,
            debug=debug,
        )

    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """
        Prepares video encoding arguments specific to HEVC encoding.

        This method ensures:
        - Streams already encoded in HEVC are copied instead of re-encoded.
        - If re-encoding is required, the correct preset and CRF values are applied.
        - HEVC tagging (`hvc1`) is enforced for compatibility.

        Steps:
        1. Iterates through video streams in the media file.
        2. If the stream is already HEVC, copies it instead of re-encoding.
        3. If encoding is needed, applies `libx265`, preset, CRF, and `hvc1` tagging.
        4. Logs the selected presets and CRF values.

        Returns:
            Dict[VideoStream, List[str]]: A mapping of video streams to their respective FFmpeg arguments.
        """
        video_args = {}  # Dictionary to store encoding arguments

        preset_log = []  # Logs the presets used
        crf_log = []  # Logs the CRF values used
        resolution_log = []

        for counter, video_stream in enumerate(self.media_file.video_info):
            resolution_log.append(video_stream.get_readable_resolution_or_default())
            
            sub_args = []
            if video_stream.codec in self.ignore_codec:
                # If the codec is already HEVC, copy the stream instead of encoding
                sub_args.extend(video_stream.map_prefix(counter))
                if video_stream.tag == "hev1":
                    # Convert hev1 to hvc1 for better compatibility
                    self.logger.debug(
                        f"🔄 Remuxing '{self.media_file.file_path.name}' from hev1 to hvc1 (no re-encoding)."
                    )
                    sub_args.extend(["copy", "-tag:v", "hvc1"])
                else:
                    # Otherwise, encode using HEVC with preset and CRF settings
                    sub_args.extend(["copy"])
                    self.logger.warning(
                        f"⚠️ Skipping encoding for stream {video_stream.index}: {color_text(self.media_file.file_path, dim=True)} is already in the desired format."
                    )
                preset_log.append("copy")
                crf_log.append("copy")
            else:
                sub_args.extend(video_stream.map_prefix(counter))
                sub_args.extend(
                    [
                        self.encoder,  # Use libx265 encoder
                        "-preset",
                        self.get_preset(video_stream),  # Apply preset
                        "-tag:v",
                        "hvc1",  # Ensure proper stream tagging
                        "-crf",
                        self.get_crf(video_stream),
                    ]
                )  # Apply CRF

                # Log preset and CRF values
                preset_log.append(self.get_preset(video_stream))
                crf_log.append(self.get_crf(video_stream))

            video_args[video_stream] = sub_args

        self.logger.debug(f"🎬 Prepared video arguments: {video_args.values()}")
        self.logger.info(
            f'🔹 HEVC encoding initialized for "{color_text(self.media_file.file_path.name, dim=True)}" | Resolution: {color_text(", ".join(resolution_log), 'cyan')} | Preset: {color_text(", ".join(preset_log), 'cyan')} | CRF: {color_text(", ".join(crf_log), 'cyan')}'
        )
        return video_args
