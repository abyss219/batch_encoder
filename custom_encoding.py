from encoding import EncodingStatus, Encoding, Av1Encoding, HevcEncoding
from typing import Type, Optional, List
import subprocess
import time
import re
from tqdm import tqdm

def get_custom_encoding_class(codec: str) -> Type[Encoding]:
    """
    Dynamically create a CustomEncoding class that inherits from HevcEncoding or Av1Encoding.
    
    :param codec: The codec type ("hevc" or "av1").
    :return: A dynamically created class that inherits from Encoding.
    :raises ValueError: If an unknown codec is provided.
    """
    if codec not in {"hevc", "av1"}:
        raise ValueError(f"❌ Invalid codec: '{codec}'. Supported codecs: 'hevc', 'av1'.")

    parent_class: Type[Encoding] = HevcEncoding if codec == "hevc" else Av1Encoding

    class CustomEncoding(parent_class):
        """
        Dynamically create a CustomEncoding class that inherits from HevcEncoding or Av1Encoding.

        :param codec: The codec type ("hevc" or "av1").
        :return: A dynamically created class that inherits from Encoding.
        """
        def is_efficient_codec(self, codec: Optional[str]) -> bool:
            """
            Check if the given codec is an efficient encoding.
            Efficient codecs include AV1, HEVC, VP9, and other modern codecs such as VVC and Theora.
            
            :param codec: The codec name as a string.
            :return: True if the codec is efficient, False otherwise.
            """
            efficient_codecs = {"av1", "hevc", "vp9", "vvc", "theora"}
            return codec in efficient_codecs


        def prepare_cmd(self) -> Optional[List[str]]:
            
            if self.media_file.video_codec == "hevc" and self.media_file.tag_string == "hev1":
                super_cmd =  super().prepare_cmd()
            
            if self.is_efficient_codec(self.media_file.video_codec):
                return None

            super_cmd =  super().prepare_cmd()
            super_cmd += ["-progress", "pipe:1", "-nostats"] # Enables FFmpeg progress output
            return super_cmd

        def get_duration(self) -> Optional[float]:
            """Retrieve video duration in seconds using FFprobe."""
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                    self.media_file.file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                duration = result.stdout.strip()
                
                return float(duration) if duration else None
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"⚠️ FFprobe failed to get duration for {self.media_file.file_path}: {e}")
            except ValueError:
                self.logger.warning(f"⚠️ Duration output could not be parsed for {self.media_file.file_path}.")
            except Exception as e:
                self.logger.error(f"❌ Unexpected error while getting duration: {e}")
            return None



        def _encode(self) -> EncodingStatus:
            ffmpeg_cmd = self.prepare_cmd()
            if not ffmpeg_cmd:
                self.logger.warning(f"⚠️ Skipping encoding: {self.media_file.file_path} (Already in desired format).")
                return EncodingStatus.SKIPPED

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
            
            # Start FFmpeg process
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, # discard stderr
                text=True,
                bufsize=1,  # Line-buffered
                universal_newlines=True
            )

            # Track progress by reading FFmpeg output
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

            process.wait()  # Ensure FFmpeg completes
            if pbar:
                pbar.close()  # Close tqdm progress bar

            if process.returncode == 0:
                self.delete_original_file()
                self.logger.debug(f"✅ Encoding successful: {self.media_file.file_path}")
                return EncodingStatus.SUCCESS
            else:
                self.logger.error(f"❌ Encoding failed: FFmpeg returned {process.returncode}")
                return EncodingStatus.FAILED
    
    return CustomEncoding
