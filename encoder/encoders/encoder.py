import os
import subprocess
import sys
from abc import ABC
from typing import List, Dict, Optional, Set, Union
from ..utils.logger import setup_logger, color_text
from ..config import *
from ..media import MediaFile, VideoStream, AudioStream

class CRFEncoder(ABC):
    """
    Base class for Constant Rate Factor (CRF) video encoding to MP4 files.

    This class automates video encoding using FFmpeg with CRF-based compression. 
    The CRF method ensures that video quality is maintained while optimizing file size. 
    The encoder supports multiple codecs, resolution-based CRF selection, and post-processing 
    options such as verification and cleanup.

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
            ignore_codec (Set[str], optional): Set of codecs to be copied without re-encoding. Defaults to an empty set.
        """

        self.logger = setup_logger(self.__class__.__name__, os.path.join(LOG_DIR, "encoder.log"))
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
        """
        Selects the appropriate pixel format for the encoder.

        If the source pixel format is not supported by the encoder, it falls back to a compatible format.

        Args:
            video_stream (VideoStream): The video stream being encoded.
            supported_fmts (list): A list of pixel formats supported by the encoder.

        Returns:
            str: The selected pixel format.
        """
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

        - If the video codec is already compatible and present in `ignore_codec`, it will be copied instead of re-encoded.
        - Otherwise, the specified CRF value is used for encoding along with the appropriate pixel format.

        Steps:
        1. Iterates over video streams in the media file.
        2. Determines whether to copy or encode based on codec compatibility.
        3. Constructs FFmpeg arguments for each video stream.

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
        self.logger.info(f'🔹 {self.__class__.__name__} encoding initialized for "{color_text(self.media_file.file_name, dim=True)}" | CRF: {", ".join(crf_log)}')
        return video_args

    def prepare_audio_args(self) -> Dict[AudioStream, List[str]]:
        """
        Prepares audio encoding arguments for FFmpeg.

        - Audio streams with compatible codecs (AAC, MP3, AC3) are copied directly without re-encoding.
        - Other audio codecs are re-encoded at a specified bitrate.
        - Preserves the sample rate as FFmpeg maintains it by default.

        Steps:
        1. Iterates over all audio streams in the media file.
        2. Determines whether to copy or re-encode based on codec compatibility.
        3. Constructs FFmpeg arguments for each audio stream.

        Returns:
            Dict[AudioStream, List[str]]: A mapping of audio streams to their respective FFmpeg arguments.
        """
        compatible_codecs = {"aac", "mp3", "ac3"}
        audio_args = {}

        
        for index, audio_stream in enumerate(self.media_file.audio_info):
            sub_arg = []
            if audio_stream.codec in compatible_codecs:
                sub_arg.extend(audio_stream.map_prefix(index, 'copy'))
                sub_arg.extend(["copy"])
            else:
                sub_arg.extend(audio_stream.map_prefix('aac'))
                target_bitrate = f"{audio_stream.bit_rate}k" if audio_stream.bit_rate else DEFAULT_AUDIO_BIT_RATE
                sub_arg.extend([target_bitrate])
                # ffmpeg preserves sample rate by default
            audio_args[audio_stream] = sub_arg
        
        self.logger.debug(f"🎵 Prepared audio arguments: {audio_args.values()}")
        return audio_args

    def _verify(self) -> EncodingStatus:
        """
        Verifies the quality of the encoded video using VMAF.

        If verification is enabled, this method compares the original and encoded videos using
        Video Multi-Method Assessment Fusion (VMAF). If the quality score is too low, the original file is retained.

        Steps:
        1. Loads the newly encoded media file.
        2. Runs VMAF comparison between the original and encoded files.
        3. Logs VMAF score or error messages.
        4. If the encoded file is corrupt or VMAF is too low, the original file is retained.

        Returns:
            EncodingStatus: SUCCESS if the verification passes, LOWQUALITY is quality threshold is not met, FAILED otherwise.
        """
        if self.verify:
            self.logger.info("🔍 Verifying encoded file integrity with VMAF...")
            try:
                tmp_media = MediaFile(self.output_tmp_file)
            except ValueError:
                self.logger.warning("⚠️ The encoded media is corrupted. The original media will not be deleted.")
                return EncodingStatus.FAILED
            else:
                vmaf_score = self.media_file.compare(tmp_media)
                if vmaf_score is not None:
                    self.logger.info(f"✅ VMAF Score: {vmaf_score:.2f}")
                    if vmaf_score < self.delete_threshold:
                        return EncodingStatus.LOWQUALITY
                else:
                    self.logger.warning("⚠️ VMAF comparison failed. The original file will not be deleted.")
                    return EncodingStatus.FAILED
        return EncodingStatus.SUCCESS

    def _delete_encoded(self):
        if os.path.isfile(self.output_tmp_file):
            os.remove(self.output_tmp_file)

    def _replace_original(self) -> EncodingStatus:
        """
        Replaces the original file with the newly encoded video.

        - Deletes the original file.
        - Renames the temporary output file to match the original filename.
        - Logs success or failure.

        Returns:
            EncodingStatus: SUCCESS if replacement was successful, FAILED otherwise.
        """
        try:
            self.logger.debug(f"🗑️ Deleting original file: {self.media_file.file_path}")
            if os.path.isfile(self.media_file.file_path):
                os.remove(self.media_file.file_path)
                if os.path.isfile(self.output_tmp_file) and not os.path.isfile(self.new_file_path):
                    os.rename(self.output_tmp_file, self.new_file_path)
                else:
                    self.logger.error(f"❌ Failed to rename encoded file {self.output_tmp_file} into {self.new_file_path}. Encoded file has been deleted.")
                    return EncodingStatus.FAILED
            else:
                self.logger.error(f"❌ Failed to delete original file {self.media_file.file_path}. Encoded file and original file will not be deleted.")
            self.logger.debug(f"📁 Successfully replaced {color_text(self.media_file.file_name, dim=True)} with {color_text(os.path.basename(self.new_file_path), dim=True)}")
        except OSError as e:
            self.logger.error(f"❌ Failed to delete original file: {e}")
            return EncodingStatus.FAILED
        return EncodingStatus.SUCCESS

    def clean_up(self, status:EncodingStatus):
        """
        Performs post-encoding cleanup.

        - If verification is enabled, compares encoded file quality using VMAF.
        - If the encoded file meets the quality threshold, the original file is deleted.
        - If verification fails or the file size is too large, the original file is retained.

        Steps:
        1. Verifies the encoding quality if verification is enabled.
        2. Checks whether the encoded file is smaller than the original (if `check_size` is enabled).
        3. If the encoding meets the criteria, replaces the original file.
        4. Returns the final encoding status.

        Returns:
            EncodingStatus: The final cleanup status (SUCCESS, FAILED, LOWQUALITY, LARGESIZE, etc.).
        """
        self.logger.info("🔄 Cleaning up...")
        
        replace_file = self.delete_original

        if status == EncodingStatus.SUCCESS:
            if self.verify:
                status = self._verify()
                if status == EncodingStatus.LOWQUALITY:
                    self.logger.warning(f"⚠️ The encoded media does not reach VMAF score threshold of {self.delete_threshold}.")
                    replace_file = False
                elif status == EncodingStatus.FAILED:
                    replace_file = False

            if self.check_size and status == EncodingStatus.SUCCESS:
                if os.path.getsize(self.output_tmp_file) >= os.path.getsize(self.media_file.file_path):
                    self.logger.warning("⚠️ The encoded video has a larger size than the original.")
                    replace_file = False
                    status = EncodingStatus.LARGESIZE

            if replace_file and status == EncodingStatus.SUCCESS:
                status = self._replace_original()
        elif status == EncodingStatus.FAILED: # encoding has failed
            self._delete_encoded()


        return status

    def _encode(self) -> EncodingStatus:
        """
        Executes the encoding process.

        This function prepares the FFmpeg command and executes the video encoding.
        After encoding, it verifies quality, checks file size, and performs cleanup.

        Steps:
        1. Calls `prepare_cmd()` to generate the FFmpeg command.
        2. Runs the FFmpeg command to encode the video.

        Returns:
            EncodingStatus: The status of encoding (SUCCESS, SKIPPED).
        """
        ffmpeg_cmd = self.prepare_cmd()

        if not ffmpeg_cmd:
            return EncodingStatus.SKIPPED
        self.logger.info(f"🚀 Final ffmpeg arg: {color_text(" ".join(ffmpeg_cmd), 'reset', dim=True)}")

        subprocess.run(ffmpeg_cmd, check=True, encoding='utf-8')
        
        return EncodingStatus.SUCCESS

    def encode_wrapper(self) -> EncodingStatus:
        """
        Handles encoding with error management and cleanup.

        This method serves as a wrapper around `_encode()` to ensure error handling and cleanup.
        It catches various exceptions such as FFmpeg failures, missing files, or user interruptions.
        If encoding fails, it cleans up temporary files and logs appropriate error messages.

        Steps:
        1. Calls `_encode()` to perform the encoding.
        2. If encoding is successful, logs success.
        3. Handles FFmpeg errors, missing files, or user interruptions.
        4. Calls `clean_up()` to finalize the process (quality verification, deletion, or file replacement).

        Returns:
            EncodingStatus: The final encoding status (SUCCESS, FAILED, SKIPPED, etc.).
        """
        ret_state = EncodingStatus.FAILED
        try:
            self.logger.debug(f"🎬 Starting encoding: {self.media_file.file_path}")
            ret_state = self._encode()
            if ret_state == EncodingStatus.SUCCESS:
                # check size reduction
                encoded_size = os.path.getsize(self.output_tmp_file)
                original_size = os.path.getsize(self.media_file.file_path)
                size_reduction = 100 * (1 - (encoded_size / original_size))
                self.logger.info(
                    f"✅ Encoding completed: {color_text(self.media_file.file_name, dim=True)} "
                    f"({color_text(f'{self.human_readable_size(original_size)} → {self.human_readable_size(encoded_size)}', 'cyan', bold=True)}, "
                    f"Reduction: {color_text(f'{size_reduction:.2f}%', 'magenta')})"
                )

            elif ret_state == EncodingStatus.SKIPPED:
                self.logger.warning(f"⚠️ Skipping encoding: {color_text(self.media_file.file_path, dim=True)} (Already in desired format).")
        except subprocess.CalledProcessError as e:
            error_msg = f"❌ Encoding failed for {self.media_file.file_path}:\n"
            if e.stderr:
                error_msg += f"Stderr: {color_text(e.stderr.decode(), color='reset', dim=True)}\n"
            if e.stdout:
                error_msg += f"Stdout: {color_text(e.stderr.decode(), color='reset', dim=True)}\n"
            
            error_msg += f"Return code: {color_text(e.returncode, bold=True)}"
            self.logger.error(error_msg)
            ret_state = EncodingStatus.FAILED
        except KeyboardInterrupt:
            self.logger.warning(f"🔴 Encoding interrupted manually (Ctrl+C). Cleaning up temp files {self.output_tmp_file}...")
            self._delete_encoded()
            sys.exit(1)
            return EncodingStatus.FAILED
        except Exception as e:
            self.logger.exception(e)
            ret_state = EncodingStatus.FAILED
        
        ret_state = self.clean_up(ret_state)
        return ret_state

    @staticmethod
    def human_readable_size(size_in_bytes:int) -> str:
        """
        Converts a file size in bytes to a human-readable format.

        Supports automatic conversion to KB, MB, or GB using a binary (1024-based) system.

        Args:
            size_in_bytes (int): The file size in bytes.

        Returns:
            str: A string representing the size in a human-readable format (e.g., '12.5 MB').
        """
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
    A subclass of CRFEncoder that supports encoding presets in addition to CRF-based compression.

    This class extends `CRFEncoder` by introducing configurable encoding presets such as `-preset` 
    (for encoders like x264/x265) or `-cpu-used` (for encoders like AV1). The preset setting 
    allows balancing between encoding speed and compression efficiency.

    Key Features:
    - Supports FFmpeg presets for fine-tuning encoding speed.
    - Retains all features of `CRFEncoder` while adding preset-based tuning.
    - Ensures filename suffix reflects both CRF and preset settings.
    """

    DEFAULT_PRESET:dict = None

    def __init__(self, media_file: MediaFile, encoder: str, preset: Optional[Union[str, int]] = None, 
                 crf: Union[str, int, None] = None, delete_original: bool=DEFAULT_DELETE_ORIGIN, check_size:bool=DEFAULT_CHECK_SIZE,
                 verify:bool=DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={}):
        """
        Initializes the PresetCRFEncoder instance with additional preset options.

        This class extends CRF-based encoding by allowing preset tuning, which influences encoding speed and efficiency.

        Args:
            media_file (MediaFile): The media file to be encoded.
            encoder (str): The encoder to use (e.g., 'libx265').
            preset (Optional[Union[str, int]], optional): The encoding preset for speed control. Defaults to None.
            crf (Optional[Union[str, int]], optional): The CRF value for quality control. Defaults to None.
            delete_original (bool, optional): Whether to delete the original file. Defaults to DEFAULT_DELETE_ORIGIN.
            check_size (bool, optional): Whether to check if the encoded file is smaller than the original. Defaults to DEFAULT_CHECK_SIZE.
            verify (bool, optional): Whether to verify encoding quality with VMAF. Defaults to DEFAULT_VERIFY.
            delete_threshold (float, optional): Minimum VMAF score required to allow deletion of the original file. Defaults to DEFAULT_DELETE_THRESHOLD.
            output_dir (Optional[str], optional): The directory for output files. Defaults to None (same as the input file).
            ignore_codec (Set[str], optional): Set of codecs that should not be re-encoded. Defaults to an empty set.
        """
        self.preset = str(preset) if preset else preset
        self.crf = str(crf) if crf else crf

        # Call parent constructor to initialize common encoding parameters
        super().__init__(media_file, encoder, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, check_size=check_size, 
                         output_dir=output_dir, ignore_codec=ignore_codec)
        
        

    def _get_filename_suffix(self) -> str:
        """
        Generates a filename suffix for encoded files, including both CRF and preset settings.

        This ensures that output filenames clearly reflect encoding parameters, 
        preventing overwriting and aiding in file identification.

        Returns:
            str: The filename suffix containing encoding settings.
        """
        name = super()._get_filename_suffix() # Get base suffix from parent class
        first_video = self.media_file.video_info[0]
        return name + f"_preset-{self.get_preset(first_video)}"

    def get_preset(self, video_stream:VideoStream) -> str:
        """
        Retrieves the appropriate encoding preset for a given video stream.

        If a specific preset is provided, it is returned. Otherwise, the preset is selected 
        from `DEFAULT_PRESET` based on the video's resolution.

        Args:
            video_stream (VideoStream): The video stream being encoded.

        Returns:
            str: The encoding preset as a string.
        """
        preset = self.preset if self.preset is not None else self.DEFAULT_PRESET[video_stream.get_readable_resolution_or_default()]
        return str(preset)

    def prepare_video_args(self, preset_cmd:str) -> Dict[VideoStream, List[str]]:
        """
        Prepares video encoding arguments for FFmpeg, including CRF and preset settings.

        - If the video codec is in `ignore_codec`, it is copied without re-encoding.
        - Otherwise, encoding is performed using CRF and the specified preset.

        Steps:
        1. Calls `prepare_video_args()` from `CRFEncoder` to get basic encoding arguments.
        2. If the video stream is being encoded, appends the preset setting.
        3. Logs the selected presets.

        Args:
            preset_cmd (str): The FFmpeg command flag for setting presets (e.g., '-preset' or '-cpu-used').

        Returns:
            Dict[VideoStream, List[str]]: A dictionary mapping video streams to their FFmpeg encoding arguments.
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