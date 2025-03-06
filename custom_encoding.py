from encoding import EncodingStatus, Encoding, Av1Encoding, HevcEncoding, MediaFile
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

        NLMEANS_SETTINGS = {
            "light": "nlmeans=s=1.0:p=3:r=7",      # Ultra-Light Denoising (Almost No Detail Loss)
            "mild": "nlmeans=s=1.5:p=5:r=9",       # Balanced Denoising (Mild but Effective) - Recommended
            "moderate": "nlmeans=s=2.5:p=7:r=11",  # Moderate Denoising (Good for Noisy Night Videos)
            "heavy": "nlmeans=s=4.0:p=9:r=15"      # Heavy Denoising (For Strong Noise & Film Restoration)
        }

        def __init__(self, media_file:MediaFile, denoise=None, delete_original=True):
            super().__init__(media_file, delete_original=delete_original)

            self.denoise = denoise

        def prepare_cmd(self) -> Optional[List[str]]:
            """Prepare FFmpeg command for HEVC encoding."""
            efficient_codecs = {"av1", "hevc", "vp9", "vvc", "theora"}
            video_args = self.prepare_video_args(efficient_codecs)
            audio_args = self.prepare_audio_args()

            if not video_args:
                return None
            elif self.codec not in video_args:
                return None
            
            
            denoise_args = self.NLMEANS_SETTINGS.get(self.denoise, "")
            if denoise_args:
                self.logger.info(f"Applied denoise: level {self.denoise}, arg: {denoise_args}")
                denoise_args = ["-vf", denoise_args]


            cmd = ["ffmpeg", "-y", "-i", self.media_file.file_path,
                    *video_args,
                    *audio_args,
                    "-movflags", "+faststart",
                    "-c:s", "copy",
                    "-progress", "pipe:1", "-nostats",
                    *denoise_args,
                    self.output_tmp_file
                    ]
            return cmd

        def get_duration(self) -> Optional[float]:
            """Retrieve video duration in seconds."""
            return float(self.media_file.video_info[0].duration)

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
