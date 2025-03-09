import os
import subprocess
import sys
from abc import ABC
from typing import List, Dict, Optional, Set, Union
from ..utils.logger import setup_logger
from ..config import *
from ..media import MediaFile, VideoStream, AudioStream

class CRFEncoder(ABC):
    """
    Base class for Constant Rate Factor (CRF) video encoding to MP4 files.

    This class provides a flexible and automated way to encode video files using FFmpeg
    with CRF-based compression. The CRF method ensures that video quality is maintained
    while achieving optimal file size reduction. The encoder supports multiple codecs,
    handles resolution-based CRF selection, and ensures smooth encoding with various
    post-processing features like verification, cleanup, and temporary file management.

    Key Features:
    - Supports CRF encoding for efficient video compression.
    - Dynamically selects CRF values based on video resolution.
    - Automatically generates unique output filenames to prevent overwriting.
    - Provides verification through Video Multi-Method Assessment Fusion (VMAF).
    - Deletes original files post-encoding if enabled.
    - Preserves audio and subtitle streams while optimizing video quality.
    - Offers codec-based skipping to avoid redundant re-encoding.

    Usage:
    - Subclass this base encoder to implement specific encoders like `HevcEncoder` or `AV1Encoder`.
    - Override methods for codec-specific encoding strategies.
    """

    DEFAULT_CRF:dict = None

    SUPPORTED_PIXEL_FORMATS:list = None

    def __init__(self, media_file: MediaFile, encoder: str, 
                 crf: Union[str, int, None] = None, delete_original: bool=DEFAULT_DELETE_ORIGIN, 
                 verify:bool=DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, 
                 check_size:bool=DEFAULT_CHECK_SIZE, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={}):
        """
        Initializes the CRFEncoder instance.
        
        Args:
            media_file (MediaFile): The media file to be encoded.
            encoder (str): The encoder to use (e.g., 'libx265').
            crf (Union[str, int, None], optional): The Constant Rate Factor (CRF) value. Defaults to None.
            delete_original (bool, optional): Whether to delete the original file after encoding. Defaults to DEFAULT_DELETE_ORIGIN.
            verify (bool, optional): Whether to verify encoding quality with VMAF. Defaults to DEFAULT_VERIFY.
            delete_threshold (float, optional): Minimum acceptable VMAF score for deletion. Defaults to DEFAULT_DELETE_THRESHOLD.
            output_dir (Optional[str], optional): Directory for output files. Defaults to None (same directory as media_file).
            ignore_codec (Set[str], optional): Set of codecs such that streams with that codecs will not be encoded. Defaults to an empty set.
        """

        self.logger = setup_logger("Encoding", os.path.join(LOG_DIR, "encoder.log"))
        self.media_file = media_file
        self.encoder = encoder
        self.crf = int(crf) if crf else crf # Convert CRF to an integer if provided
        self.delete_original = delete_original
        self.delete_threshold = delete_threshold
        self.check_size = check_size
        self.verify = verify
        self.output_dir = output_dir or os.path.dirname(media_file.file_path) # Set output directory
        self.ignore_codec = ignore_codec

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

        self.output_tmp_file = self.generate_tmp_output_path()
        self.new_file_path = self.generate_new_file_path()
        self.logger.debug(f'🔹 {self.__class__.__name__} initialized for "{media_file.file_path}"')

    def generate_new_file_path(self) -> str:
        """
        Generates a unique file path for the encoded video.
        
        If the file already exists, a numeric suffix is appended to create a unique name.
        If the original file has the same name and extension as the target, it is overwritten.
        
        Returns:
            str: The new file path.
        """
        if self.delete_original is False:
            return self.output_tmp_file

        base_name = os.path.splitext(self.media_file.file_name)[0]
        new_path = os.path.join(self.output_dir, f"{base_name}.mp4")
        
         # If input file is already an MP4, we are going to overwrite the input file
        if new_path == self.media_file.file_path:
            return new_path
        
        counter = 1
        while os.path.exists(new_path): # Ensure uniqueness
            new_path = os.path.join(self.output_dir, f"{base_name}_{counter}.mp4")
            counter += 1

        return new_path
    

    def generate_tmp_output_path(self) -> str:
        """
        Generates a temporary output file path based on encoding parameters.
        Ensures the filename is unique to avoid overwriting existing files.
        
        Returns:
            str: The temporary output file path.
        """
        base_name = os.path.splitext(self.media_file.file_name)[0]

        # Get the suffix from the subclass
        suffix = self._get_filename_suffix()
        
        output_filename = os.path.join(self.output_dir, f"{base_name}{suffix}.mp4")

        counter = 1
        while os.path.exists(output_filename): # Ensure unique filename
            output_filename = os.path.join(self.output_dir, f"{base_name}{suffix}_{counter}.mp4")
            counter += 1

        self.logger.debug(f"📂 Generated output filename: {output_filename}")
        return output_filename


    
    def get_crf(self, video_stream:VideoStream) -> str:
        """
        Retrieves the appropriate CRF (Constant Rate Factor) value for a given video stream.
        
        If `self.crf` is set, it is returned as the CRF value. Otherwise, the default CRF value 
        is retrieved from `DEFAULT_CRF` based on the video's resolution.
        
        Args:
            video_stream (VideoStream): The video stream to encode.
        
        Returns:
            str: The CRF value as a string.
        """
        crf = self.crf if self.crf is not None else self.DEFAULT_CRF[video_stream.get_readable_resolution_or_default()]
        return str(crf)

    def get_pix_fmt(self, video_stream:VideoStream, supported_fmts:list) -> str:
        if video_stream.pix_fmt in supported_fmts:
            return video_stream.pix_fmt
        else:
            option = ""
            for fmt in supported_fmts:
                if video_stream.pix_fmt and video_stream.pix_fmt.startswith(fmt):
                    option = fmt
                    break
            if not option:
                option = supported_fmts[0]
            self.logger.warning(f"⚠️ The encoder/filter does not support source pixel format {video_stream.pix_fmt}. "
                                f"Falling back to the first format it supports: {supported_fmts[0]}")
            return option

    def _get_filename_suffix(self) -> str:
        """
        Generates a filename suffix based on encoding settings.
        
        The suffix contains the encoder class name and CRF value.
        
        Returns:
            str: The filename suffix.
        """
        first_video = self.media_file.video_info[0]
        return f"_{self.__class__.__name__}_crf-{self.get_crf(first_video)}"

    def prepare_cmd(self) -> Optional[List[str]]:
        """
        Prepares the FFmpeg command for encoding the video.
        
        If the video does not require encoding (e.g., codec of all streams is already in the desired format), 
        the function returns None to skip processing.
        
        Returns:
            Optional[List[str]]: The FFmpeg command arguments, or None if encoding is skipped.
        """
        video_args = self.prepare_video_args().values()
        audio_args = self.prepare_audio_args().values()

        audio_args_flatten = [item for sublist in audio_args for item in sublist]
        video_args_flatten = [item for sublist in video_args for item in sublist]

        if not video_args_flatten:
            self.logger.debug(f"⚠️ No valid stream exists for file: {self.media_file.file_path}.")
            return None
        elif self.encoder not in video_args_flatten and 'hvc1' not in video_args_flatten: # if we copy all streams, just ignore it
            self.logger.debug(f"⚠️ Nothing to encode for file: {self.media_file.file_path} is already in the desired format.")
            return None
        
        cmd = ["ffmpeg", "-y", "-i", self.media_file.file_path,
                *video_args_flatten,
                *audio_args_flatten,
                "-c:s", "copy",
                "-movflags", "+faststart",
                self.output_tmp_file
                 ]
        
        return cmd

    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """
        Prepares video encoding arguments for FFmpeg.
        
        If the video codec is already compatible and present in `ignore_codec`, it will be copied instead of re-encoded.
        Otherwise, the specified CRF value is used for encoding.
        
        Returns:
            Dict[VideoStream, List[str]]: Mapping of video streams to their respective FFmpeg arguments.
        """
        video_args = {}
        
        crf_log = []

        for counter, video_stream in enumerate(self.media_file.video_info):
            sub_args = []
            sub_args.extend(video_stream.map_prefix(counter))
            if video_stream.codec in self.ignore_codec:
                self.logger.info(f"⚠️ Skipping encoding: The input video '{self.media_file.file_name}' is already in {video_stream.codec} format.")
                sub_args.extend(["copy"])
                crf_log.append('copy')
            else:
                crf = self.get_crf(video_stream)
                sub_args.extend([self.encoder,
                                   "-crf", crf,
                                   "-pix_fmt", self.get_pix_fmt(video_stream, self.SUPPORTED_PIXEL_FORMATS)
                                   ])
                crf_log.append(crf)

            video_args[video_stream] = sub_args
        
        self.logger.debug(f"🎬 Prepared video arguments: {video_args.values()}")
        self.logger.info(f'🔹 {self.__class__.__name__} encoding initialized for "{self.media_file.file_name}" | CRF: {", ".join(crf_log)}')
        return video_args

    def prepare_audio_args(self) -> Dict[AudioStream, List[str]]:
        """
        Prepares audio encoding arguments for FFmpeg.
        
        Compatible audio codecs (AAC, MP3, AC3) are copied directly, while others are re-encoded at a target bitrate.
        
        Returns:
            Dict[AudioStream, List[str]]: Mapping of audio streams to their respective FFmpeg arguments.
        """
        compatible_codecs = {"aac", "mp3", "ac3"}
        audio_args = {}

        
        for index, audio_stream in enumerate(self.media_file.audio_info):
            sub_arg = []
            sub_arg.extend(audio_stream.map_prefix(index))
            if audio_stream.codec in compatible_codecs:
                sub_arg.extend(["copy"])
            else:
                target_bitrate = f"{audio_stream.bit_rate}k" if audio_stream.bit_rate else DEFAULT_AUDIO_BIT_RATE
                sub_arg.extend([target_bitrate])
                # ffmpeg preserves sample rate by default
            audio_args[audio_stream] = sub_arg
        
        self.logger.debug(f"🎵 Prepared audio arguments: {audio_args.values()}")
        return audio_args

    def _verify(self):
        if self.verify:
            self.logger.info("🔍 Verifying encoded file integrity with VMAF...")
            try:
                tmp_media = MediaFile(self.output_tmp_file)
            except ValueError:
                self.logger.warning("⚠️ The encoded media is corrupted. The original media will not be deleted.")
                self.new_file_path = self.output_tmp_file
                return EncodingStatus.FAILED
            else:
                vmaf_score = self.media_file.compare(tmp_media)
                if vmaf_score is not None:
                    self.logger.info(f"✅ VMAF Score: {vmaf_score:.2f}")
                else:
                    self.logger.warning("⚠️ VMAF comparison failed. The original file will not be deleted.")
                    self.new_file_path = self.output_tmp_file
                    return EncodingStatus.FAILED
        return EncodingStatus.SUCCESS

    def _replace_original(self):
        try:
            self.logger.debug(f"🗑️ Deleting original file: {self.media_file.file_path}")
            os.remove(self.media_file.file_path)
            os.rename(self.output_tmp_file, self.new_file_path)
            self.logger.info(f"📁 Successfully replaced {self.media_file.file_name} with {os.path.basename(self.new_file_path)}")
        except OSError as e:
            self.logger.error(f"❌ Failed to delete original file: {e}")
            return EncodingStatus.FAILED
        return EncodingStatus.SUCCESS

    def clean_up(self):
        """
        Performs post-encoding cleanup.
        
        - If verification is enabled, compares encoded file quality using VMAF.
        - If the encoded file meets the quality threshold, the original file is deleted.
        - If verification fails or quality is too low, the original file is retained.
        
        Returns:
            EncodingStatus: The status of encoding cleanup (SUCCESS, FAILED, LOWQUALITY, etc.).
        """
        self.logger.info("🔄 Cleaning up...")
        
        status = EncodingStatus.SUCCESS
        if self.verify:
            status = self._verify()
        
        if self.check_size:
            if os.path.getsize(self.output_tmp_file) >= os.path.getsize(self.media_file.file_path):
                self.logger.warning("⚠️ The encoded video has a larger size than the original. The original file will not be deleted.")
                return EncodingStatus.LARGESIZE

        if self.delete_original:
            status = self._replace_original()
        
        return status

    def _encode(self) -> EncodingStatus:
        """
        Executes the encoding process.
        
        - Calls `prepare_cmd()` to generate the FFmpeg command.
        - Runs the FFmpeg command to encode the video.
        - Calls `clean_up()` to finalize the process.
        
        Returns:
            EncodingStatus: The status of encoding.
        """
        ffmpeg_cmd = self.prepare_cmd()
        self.logger.info(f"🚀 Final ffmpeg arg: {" ".join(ffmpeg_cmd)}")

        if not ffmpeg_cmd:
            self.logger.warning(f"⚠️ Skipping encoding: {self.media_file.file_path} (Already in desired format).")
            return EncodingStatus.SKIPPED

        self.logger.debug(f"🎬 Starting encoding: {self.media_file.file_path}")
        result = subprocess.run(ffmpeg_cmd, check=True, encoding='utf-8')

        # check size reduction
        encoded_size = os.path.getsize(self.output_tmp_file)
        original_size = os.path.getsize(self.media_file.file_path)
        size_reduction = 100 * (1 - (encoded_size / original_size))
        self.logger.info(f"✅ Encoding completed: {self.media_file.file_name} ({self.human_readable_size(original_size)} → {self.human_readable_size(encoded_size)}, Reduction: {size_reduction:.2f}%)")
        
        status = EncodingStatus.SUCCESS
        status = self.clean_up()
        return status

    def encode_wrapper(self) -> EncodingStatus:
        """
        Wrapper function to handle encoding with error handling.
        
        - Calls `_encode()` to perform encoding.
        - Handles errors such as FFmpeg failures, missing files, or user interruptions.
        - Cleans up temporary files if encoding fails.
        
        Returns:
            EncodingStatus: The final encoding status.
        """
        try:
            ret = self._encode()
            self.logger.debug(f"✅ Encoding successful: {self.media_file.file_path}")
            return ret
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else "Unknown FFmpeg error"
            self.logger.error(f"❌ Encoding failed for {self.media_file.file_path}: {error_msg}")
            if os.path.isfile(self.output_tmp_file):
                os.remove(self.output_tmp_file)
            return EncodingStatus.FAILED

        except FileNotFoundError:
            self.logger.error(f"❌ FFmpeg not found. Make sure it is installed and accessible.")
            return EncodingStatus.FAILED

        except KeyboardInterrupt:
            self.logger.warning(f"🔴 Encoding interrupted manually (Ctrl+C). Cleaning up temp files {self.output_tmp_file}...")
            if os.path.isfile(self.output_tmp_file):
                os.remove(self.output_tmp_file)
            sys.exit(1)
            return EncodingStatus.FAILED
        except Exception as e:
            self.logger.exception(e)
            return EncodingStatus.FAILED

    @staticmethod
    def human_readable_size(size_in_bytes):
        """Convert bytes into a human-readable format (GB, MB, KB) using binary (1024-based) system."""
        if size_in_bytes >= 1_073_741_824:  # 1024 ** 3
            return f"{size_in_bytes / 1_073_741_824:.2f} GB"
        elif size_in_bytes >= 1_048_576:  # 1024 ** 2
            return f"{size_in_bytes / 1_048_576:.2f} MB"
        elif size_in_bytes >= 1024:
            return f"{size_in_bytes / 1024:.2f} KB"
        else:
            return f"{size_in_bytes} B"

class PresetCRFEncoder(CRFEncoder, ABC):
    """
    A subclass of CRFEncoder that also includes preset settings for video encoding.
    
    This class allows setting and managing FFmpeg encoding presets such as `-preset` or `-cpu-used`
    alongside the CRF value for efficient video compression.
    """
    DEFAULT_PRESET:dict = None

    def __init__(self, media_file: MediaFile, encoder: str, preset: Union[str, int, None] = None, 
                 crf: Union[str, int, None] = None, delete_original: bool=DEFAULT_DELETE_ORIGIN, check_size:bool=DEFAULT_CHECK_SIZE,
                 verify:bool=DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={}):
        """
        Initializes the PresetCRFEncoder instance with additional preset options.
        
        Args:
            media_file (MediaFile): The media file to be encoded.
            encoder (str): The encoder to use (e.g., 'libx265').
            preset (Union[str, int, None], optional): The preset setting for encoding speed. Defaults to None.
            crf (Union[str, int, None], optional): The CRF value for quality control. Defaults to None.
            delete_original (bool, optional): Whether to delete the original file. Defaults to DEFAULT_DELETE_ORIGIN.
            verify (bool, optional): Whether to verify encoding quality with VMAF. Defaults to DEFAULT_VERIFY.
            delete_threshold (float, optional): Minimum VMAF score for deletion. Defaults to DEFAULT_DELETE_THRESHOLD.
            output_dir (Optional[str], optional): Directory for output files. Defaults to None (same as input file).
            ignore_codec (Set[str], optional): Set of codecs that should not be re-encoded. Defaults to an empty set.
        """
        self.preset = str(preset) if preset else preset

        # Call parent constructor to initialize common encoding parameters
        super().__init__(media_file, encoder, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, check_size=check_size, 
                         output_dir=output_dir, ignore_codec=ignore_codec)
        
        

    def _get_filename_suffix(self) -> str:
        """
        Generates a filename suffix for encoded files including the preset setting.
        
        Returns:
            str: The filename suffix containing encoding settings.
        """
        name = super()._get_filename_suffix() # Get base suffix from parent class
        first_video = self.media_file.video_info[0]
        return name + f"_preset-{self.get_preset(first_video)}"

    def get_preset(self, video_stream:VideoStream) -> str:
        """
        Retrieves the appropriate encoding preset for a given video stream.
        
        If `self.preset` is set, it is returned. Otherwise, the default preset value 
        is retrieved from `DEFAULT_PRESET` based on the video's resolution.
        
        Args:
            video_stream (VideoStream): The video stream to encode.
        
        Returns:
            str: The preset value as a string.
        """
        preset = self.preset if self.preset is not None else self.DEFAULT_PRESET[video_stream.get_readable_resolution_or_default()]
        return str(preset)

    def prepare_video_args(self, preset_cmd:str) -> Dict[VideoStream, List[str]]:
        """
        Prepares video conversion arguments with an additional preset setting.
        
        Args:
            preset_cmd (str): The FFmpeg command flag for setting preset (e.g., '-preset' or '-cpu-used').
        
        Returns:
            Dict[VideoStream, List[str]]: A mapping of video streams to their respective FFmpeg arguments.
        """
        video_args = super().prepare_video_args() # Get base video arguments

        preset_log = []

        for stream, arg in video_args.items():
            if 'copy' not in arg: # Only add preset if the stream is being encoded
                preset = self.get_preset(stream)
                arg.extend([preset_cmd, preset]) # Append preset option to FFmpeg arguments
                preset_log.append(preset)
            else:
                preset_log.append('copy')
        
        self.logger.info(f'🔹 Preset: {", ".join(preset_log)}')

        return video_args