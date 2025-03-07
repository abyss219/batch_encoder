import os
import subprocess
import sys
from abc import ABC
from typing import List, Dict, Optional, Set, Union
from ..utils.logger import setup_logger
from ..config import *
from ..media import MediaFile, VideoStream, AudioStream


class CRFEncoder(ABC):
    """Base class for video encoding."""

    DEFAULT_CRF:dict = None

    def __init__(self, media_file: MediaFile, encoder: str, 
                 crf: Union[str, int, None] = None, delete_original: bool=DEFAULT_DELETE_ORIGIN, 
                 verify:bool=DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={}):
        
        self.logger = setup_logger("Encoding", "logs/encoding.log")
        self.media_file = media_file
        self.encoder = encoder
        self.crf = int(crf) if crf else crf
        self.delete_original = delete_original
        self.delete_threshold = delete_threshold
        self.verify = verify
        self.output_dir = output_dir or os.path.dirname(media_file.file_path)
        self.ignore_codec = ignore_codec

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

        self.output_tmp_file = self.generate_tmp_output_path()
        self.new_file_path = self.generate_new_file_path()
        self.logger.debug(f'🔹 {self.__class__.__name__} initialized for "{media_file.file_path}"')

    def generate_new_file_path(self) -> str:
        """
        Generate a unique file path by checking if the file already exists.
        If the file exists, append a number suffix until a unique name is found.
        
        Example:
            - "video.mp4"  → (exists) → "video_1.mp4"
            - "video_1.mp4" → (exists) → "video_2.mp4"
        """
        if self.delete_original is False:
            return self.output_tmp_file

        base_name = os.path.splitext(self.media_file.file_name)[0]
        new_path = os.path.join(self.output_dir, f"{base_name}.mp4")
        
        
        if new_path == self.media_file.file_path: # if the input media file already has the extension mp4, just replace it
            return new_path
        
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(self.output_dir, f"{base_name}_{counter}.mp4")
            counter += 1

        return new_path
    

    def generate_tmp_output_path(self) -> str:
        """Generate a unique output filename based on encoding parameters."""
        base_name = os.path.splitext(self.media_file.file_name)[0]

        # Get the suffix from the subclass
        suffix = self._get_filename_suffix()
        
        output_filename = os.path.join(self.output_dir, f"{base_name}{suffix}.mp4")

        # Ensure the filename is unique
        counter = 1
        while os.path.exists(output_filename):
            output_filename = os.path.join(self.output_dir, f"{base_name}{suffix}_{counter}.mp4")
            counter += 1

        self.logger.debug(f"📂 Generated output filename: {output_filename}")
        return output_filename


    
    def get_crf(self, video_stream:VideoStream) -> str:
        crf = self.crf if self.crf is not None else self.DEFAULT_CRF[video_stream.get_readable_resolution_or_default()]
        return str(crf)

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for HEVC encoding."""
        first_video = self.media_file.video_info[0]
        return f"_{self.__class__.__name__}_crf-{self.get_crf(first_video)}"

    def prepare_cmd(self) -> Optional[List[str]]:
        """Prepare FFmpeg command for HEVC encoding."""
        video_args = self.prepare_video_args().values()
        audio_args = self.prepare_audio_args().values()

        audio_args_flatten = [item for sublist in audio_args for item in sublist]
        video_args_flatten = [item for sublist in video_args for item in sublist]

        if not video_args_flatten:
            return None
        elif self.encoder not in video_args_flatten: # if we copy all streams, just ignore it
            return None
        
        cmd = ["ffmpeg", "-y", "-i", self.media_file.file_path,
                *video_args_flatten,
                *audio_args_flatten,
                "-movflags", "+faststart",
                "-c:s", "copy",
                self.output_tmp_file
                 ]
        
        return cmd

    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """Prepare video conversion arguments."""
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
                                   "-crf", crf
                                   ])
                crf_log.append(crf)

            video_args[video_stream] = sub_args
        
        self.logger.debug(f"🎬 Prepared video arguments: {video_args.values()}")
        self.logger.info(f'🔹 {self.__class__.__name__} encoding initialized for "{self.media_file.file_name}" | CRF: {", ".join(crf_log)}')
        return video_args

    def prepare_audio_args(self) -> Dict[AudioStream, List[str]]:
        """Prepare audio conversion arguments."""
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

    def clean_up(self):
        """
        Deletes the original file after encoding, if required.
        Also performs VMAF verification before deletion if enabled.
        """
        self.logger.debug("🔄 Starting cleanup process...")
        
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
        
            if vmaf_score < self.delete_threshold:
                self.logger.warning(f"⚠️ VMAF comparison below threshold {self.delete_threshold}. The original file will not be deleted.")
                self.new_file_path = self.output_tmp_file
                return EncodingStatus.LOWQUALITY

        if self.delete_original:
            try:
                self.logger.debug(f"🗑️ Deleting original file: {self.media_file.file_path}")
                os.remove(self.media_file.file_path)
                os.rename(self.output_tmp_file, self.new_file_path)
                self.logger.info(f"📁 Successfully replaced {self.media_file.file_name} with {os.path.basename(self.new_file_path)}")
            except OSError as e:
                self.logger.error(f"❌ Failed to delete original file: {e}")
                return EncodingStatus.FAILED
        
        return EncodingStatus.SUCCESS

    def _encode(self) -> EncodingStatus:
        ffmpeg_cmd = self.prepare_cmd()
        self.logger.info(f"Final ffmpeg arg: {" ".join(ffmpeg_cmd)}")

        if not ffmpeg_cmd:
            self.logger.warning(f"⚠️ Skipping encoding: {self.media_file.file_path} (Already in desired format).")
            return EncodingStatus.SKIPPED

        self.logger.debug(f"🎬 Starting encoding: {self.media_file.file_path}")
        result = subprocess.run(ffmpeg_cmd, check=True)
        
        status = EncodingStatus.SUCCESS
        status = self.clean_up()
        return status

    def encode_wrapper(self) -> EncodingStatus:
        """Encodes the video and returns its status."""
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


class PresetCRFEncoder(CRFEncoder, ABC):

    DEFAULT_PRESET:dict = None

    def __init__(self, media_file: MediaFile, encoder: str, preset: Union[str, int, None] = None, 
                 crf: Union[str, int, None] = None, delete_original: bool=DEFAULT_DELETE_ORIGIN, 
                 verify:bool=DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None,
                 ignore_codec:Set[str]={}):
        self.preset = str(preset) if preset else preset

        super().__init__(media_file, encoder, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, 
                         output_dir=output_dir, ignore_codec=ignore_codec)
        
        

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for HEVC encoding."""
        name = super()._get_filename_suffix()
        first_video = self.media_file.video_info[0]
        return name + f"_preset-{self.get_preset(first_video)}"

    def get_preset(self, video_stream:VideoStream) -> str:
        preset = self.preset if self.preset is not None else self.DEFAULT_PRESET[video_stream.get_readable_resolution_or_default()]
        return str(preset)

    def prepare_video_args(self, preset_cmd:str) -> Dict[VideoStream, List[str]]:
        """Prepare video conversion arguments.
        preset_cmd = "-preset" or "-cpu-used"
        """
        video_args = super().prepare_video_args()

        preset_log = []

        for stream, arg in video_args.items():
            if 'copy' not in arg:
                preset = self.get_preset(stream)
                arg.extend([preset_cmd, preset])
                preset_log.append(preset)
            else:
                preset_log.append('copy')
        
        self.logger.info(f'🔹 Preset: {", ".join(preset_log)}')

        return video_args