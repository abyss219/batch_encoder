from __future__ import annotations
import os
import subprocess
import sys

from typing import List, Optional
from .utils.logger import setup_logger
from .config import *
from .media import MediaFile, VideoStream



class Encoder:
    """Base class for video encoding."""

    DEFAULT_PRESET:dict = None

    DEFAULT_CRF:dict = None

    def __init__(self, media_file: MediaFile, codec: str, preset: str, crf: int, delete_original: bool=DEFAULT_DELETE_ORIGIN, 
                 verify:bool=DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None):
        self.logger = setup_logger("Encoding", "logs/encoding.log")
        self.media_file = media_file
        self.codec = codec
        self.preset = preset
        self.crf = crf
        self.delete_original = delete_original
        self.delete_threshold = delete_threshold
        self.verify = verify
        self.output_dir = output_dir or os.path.dirname(media_file.file_path)

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

        self.output_tmp_file = self.generate_tmp_output_filename()
        self.new_file_path = self.get_new_file_path()
        self.logger.debug(f"🎬 Encoding initialized for {self.media_file.file_path}")

    def get_new_file_path(self) -> str:
        """
        Generate a unique file path by checking if the file already exists.
        If the file exists, append a number suffix until a unique name is found.
        
        Example:
            - "video.mp4"  → (exists) → "video_1.mp4"
            - "video_1.mp4" → (exists) → "video_2.mp4"
        """
        base_name = os.path.splitext(os.path.basename(self.media_file.file_path))[0]
        new_path = os.path.join(self.output_dir, f"{base_name}.mp4")
        
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(self.output_dir, f"{base_name}_{counter}.mp4")
            counter += 1

        return new_path
    

    def generate_tmp_output_filename(self) -> str:
        """Generate a unique output filename based on encoding parameters."""
        base_name = os.path.splitext(os.path.basename(self.media_file.file_path))[0]

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

    def get_preset(self, video_stream:VideoStream) -> str:
        return self.preset if self.preset is not None else self.DEFAULT_PRESET[video_stream.get_readable_resolution_or_default()]
    
    def get_crf(self, video_stream:VideoStream) -> str:
        crf = self.crf if self.crf is not None else self.DEFAULT_CRF[video_stream.get_readable_resolution_or_default()]
        return str(crf)

    def _get_filename_suffix(self) -> str:
        """This method should be overridden by subclasses to define the filename format."""
        raise NotImplementedError("Subclasses must implement _get_filename_suffix()")

    def prepare_cmd(self) -> Optional[List[str]]:
        """Prepare FFmpeg command for HEVC encoding."""
        video_args = self.prepare_video_args()
        audio_args = self.prepare_audio_args()

        if not video_args:
            return None
        elif self.codec not in video_args:
            return None
        
        cmd = ["ffmpeg", "-y", "-i", self.media_file.file_path,
                *video_args,
                *audio_args,
                "-movflags", "+faststart",
                "-c:s", "copy",
                self.output_tmp_file
                 ]
        return cmd

    def prepare_video_args(self, copy_codec={}) -> List[str]:
        raise NotImplementedError("This method should be implemented in child classes.")

    def prepare_audio_args(self) -> List[str]:
        """Prepare audio conversion arguments."""
        compatible_codecs = {"aac", "mp3", "ac3"}
        audio_args = []

        for index, audio_stream in enumerate(self.media_file.audio_info):
            audio_args.extend(audio_stream.map_prefix(index))
            if audio_stream.codec in compatible_codecs:
                audio_args.extend(["copy"])
            else:
                target_bitrate = f"{audio_stream.bit_rate}k" if audio_stream.bit_rate else DEFAULT_AUDIO_BIT_RATE
                audio_args.extend([f"-c:a:{audio_stream.index}", "aac", f"-b:a:{audio_stream.index}", target_bitrate])
                # ffmpeg preserves sample rate by default
        
        self.logger.debug(f"🎵 Prepared audio arguments: {audio_args}")
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
                return
            else:
                vmaf_score = self.media_file.compare(tmp_media)
                if vmaf_score is not None:
                    self.logger.info(f"✅ VMAF Score: {vmaf_score:.2f}")
                else:
                    self.logger.warning("⚠️ VMAF comparison failed. The original file will not be deleted.")
                    return
        
            if vmaf_score < self.delete_threshold:
                self.logger.warning(f"⚠️ VMAF comparison below threshold {self.delete_threshold}. The original file will not be deleted.")
                return


        if self.delete_original:
            try:
                self.logger.debug(f"🗑️ Deleting original file: {self.media_file.file_path}")
                new_file_name = self.new_file_path
                os.remove(self.media_file.file_path)
                os.rename(self.output_tmp_file, new_file_name)
                self.logger.info(f"📁 Successfully replaced {os.path.basename(self.media_file.file_path)} with {os.path.basename(new_file_name)}")
            except OSError as e:
                self.logger.error(f"❌ Failed to delete original file: {e}")

    def _encode(self) -> EncodingStatus:
        ffmpeg_cmd = self.prepare_cmd()

        if not ffmpeg_cmd:
            self.logger.warning(f"⚠️ Skipping encoding: {self.media_file.file_path} (Already in desired format).")
            return EncodingStatus.SKIPPED

        self.logger.debug(f"🎬 Starting encoding: {self.media_file.file_path}")
        result = subprocess.run(ffmpeg_cmd, check=True)
        
        
        self.clean_up()
        return EncodingStatus.SUCCESS

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

class HevcEncoder(Encoder):
    """Handles HEVC (H.265) encoding with resolution-based parameter selection."""

    DEFAULT_PRESET = DEFAULT_PRESET_HEVC

    DEFAULT_CRF = DEFAULT_CRF_HEVC


    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 delete_original: bool = DEFAULT_DELETE_ORIGIN, verify: bool = DEFAULT_VERIFY, delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None, **kwargs):
        super().__init__(media_file, codec="libx265", preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, output_dir=output_dir)
        
        self.logger.debug(f"🔹 HEVC class initialized for {media_file.file_path}")

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for HEVC encoding."""
        first_video = self.media_file.video_info[0]
        return f"_hevc_preset-{self.get_preset(first_video)}_crf-{self.get_crf(first_video)}"
    
    def prepare_video_args(self, copy_codec={"hevc"}) -> List[str]:
        """Prepare video conversion arguments."""
        video_args = []
        
        preset_log = []
        crf_log = []

        counter = 0
        for video_stream in self.media_file.video_info:
            if video_stream.codec in copy_codec:
                video_args.extend(video_stream.map_prefix(counter))
                if video_stream.tag == "hev1":
                    self.logger.info(f"🔄 Remuxing '{self.media_file.file_path}' from hev1 to hvc1 (no re-encoding).")
                    video_args.extend(["copy", "-tag:v", "hvc1"])
                else:
                    video_args.extend(["copy"])
                    self.logger.warning(f"⚠️ Skipping HEVC encoding: {self.media_file.file_path} is already in the desired format.")
                counter += 1
                preset_log.append("copy")
                crf_log.append("copy")
            else:
                video_args.extend(video_stream.map_prefix(counter))
                video_args.extend(["libx265", "-preset", self.get_preset(video_stream), "-tag:v", "hvc1", "-crf", self.get_crf(video_stream)])
                counter += 1

                preset_log.append(self.get_preset(video_stream))
                crf_log.append(self.get_crf(video_stream))
        
        self.logger.debug(f"🎬 Prepared video arguments: {video_args}")
        self.logger.info(f"🔹 HEVC encoding initialized for {self.media_file.file_path} | Preset: {", ".join(preset_log)} | CRF: {", ".join(crf_log)}")
        return video_args

class Av1Encoder(Encoder):
    """Handles AV1 encoding with resolution-based parameter selection."""

    DEFAULT_PRESET = DEFAULT_PRESET_AV1

    # 8-10% quality loss
    DEFAULT_CRF = DEFAULT_CRF_AV1

    DEFAULT_CPU_USED = DEFAULT_CPU_USED_AV1

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Optional[int] = None,
                 cpu_used: Optional[int] = None, delete_original: bool = False, verify: bool = False, 
                 delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None, **kwargs):
        self.cpu_used = cpu_used
        super().__init__(media_file, codec="libaom-av1", preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, delete_threshold=delete_threshold, output_dir=output_dir)
        
        
        self.logger.debug(f"🔹 AV1 class initialized for {media_file.file_path}")


    def get_cpu_used(self, video_stream:VideoStream) -> str:
        selected_cpu_used = self.cpu_used if self.cpu_used is not None else self.DEFAULT_CPU_USED[video_stream.get_readable_resolution_or_default()]
        if selected_cpu_used > 8:
            selected_cpu_used = 8
        elif selected_cpu_used < 0:
            selected_cpu_used = 0
        
        return str(selected_cpu_used)
    
    def get_maximum_keyframe_interval(self, video_stream:VideoStream) -> str:
        frame_rate = video_stream.frame_rate if video_stream.frame_rate else DEFAULT_FRAME_RATE
        interval = round(frame_rate * 10)
        return str(interval)

    def get_keyint_min(self, video_stream:VideoStream) -> str:
        return self.get_maximum_keyframe_interval(video_stream)

    def prepare_video_args(self, copy_codec={"av1"}) -> List[str]:
        """Prepare video conversion arguments."""
        video_args = []

        preset_log = []
        crf_log = []
        cpu_used_log = []

        counter = 0
        for video_stream in self.media_file.video_info:
            video_args.extend(video_stream.map_prefix(counter))
            if video_stream.codec in copy_codec:
                self.logger.info(f"⚠️ Skipping encoding: The input video '{self.media_file.file_path}' is already in AV1 format.")
                video_args.extend(["copy"])

                preset_log.append("copy")
                crf_log.append("copy")
                cpu_used_log.append("copy")
            else:
                
                preset, crf, cpu_used = self.get_preset(video_stream), self.get_crf(video_stream), self.get_cpu_used(video_stream)
                maximum_keyframe_interval = self.get_maximum_keyframe_interval(video_stream)
                keyint_min = self.get_keyint_min(video_stream)
                video_args.extend(["libaom-av1", "-preset", preset, 
                                   "-cpu-used", cpu_used, "-row-mt", "1", 
                                   "-crf", crf, "-b:v", "0",
                                   "-g", maximum_keyframe_interval,
                                   "-keyint_min", keyint_min,
                                   ])
                # Note that in FFmpeg versions prior to 4.3, triggering the CRF mode also requires setting the bitrate to 0 with -b:v 0. If this is not done, the -crf switch triggers the constrained quality mode with a default bitrate of 256kbps.
                preset_log.append(preset)
                crf_log.append(crf)
                cpu_used_log.append(cpu_used)
            
            counter += 1
        
        self.logger.info(f"🔹 AV1 encoding initialized for {self.media_file.file_path} | Preset: {", ".join(preset_log)} | CRF: {", ".join(crf_log)} | CPU: {", ".join(cpu_used_log)}")
        self.logger.debug(f"🎬 Prepared video arguments: {video_args}")
        return video_args

    def _get_filename_suffix(self) -> str:
        """Create the filename suffix for AV1 encoding, including CPU-used."""
        first_media = self.media_file.video_info[0]
        return f"_av1_preset-{self.get_preset(first_media)}_crf-{self.get_crf(first_media)}_cpu-{self.get_cpu_used(first_media)}"

