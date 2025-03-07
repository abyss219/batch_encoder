from ..media import MediaFile, VideoStream
from .encoder import PresetCRFEncoder
from ..config import *
from typing import List, Dict, Optional, Set, Union

class HevcEncoder(PresetCRFEncoder):
    """Handles HEVC (H.265) encoding with resolution-based parameter selection."""

    DEFAULT_PRESET = DEFAULT_PRESET_HEVC

    DEFAULT_CRF = DEFAULT_CRF_HEVC

    def __init__(self, media_file: MediaFile, preset: Optional[str] = None, crf: Union[str, int, None] = None,
                 delete_original: bool = DEFAULT_DELETE_ORIGIN, verify: bool = DEFAULT_VERIFY,
                  delete_threshold:float=DEFAULT_DELETE_THRESHOLD, output_dir: Optional[str] = None, 
                  ignore_codec:Set[str]={'hevc'}, **kwargs):
        
        super().__init__(media_file, encoder="libx265", preset=preset, crf=crf,
                         delete_original=delete_original, verify=verify, 
                         delete_threshold=delete_threshold, output_dir=output_dir,
                         ignore_code=ignore_codec)
    
    def prepare_video_args(self) -> Dict[VideoStream, List[str]]:
        """Prepare video conversion arguments."""
        video_args = {}
        
        preset_log = []
        crf_log = []

        counter = 0
        for video_stream in self.media_file.video_info:
            sub_args = []
            if video_stream.codec in self.ignore_codec:
                sub_args.extend(video_stream.map_prefix(counter))
                if video_stream.tag == "hev1":
                    self.logger.info(f"🔄 Remuxing '{self.media_file.file_path}' from hev1 to hvc1 (no re-encoding).")
                    sub_args.extend(["copy", "-tag:v", "hvc1"])
                else:
                    sub_args.extend(["copy"])
                    self.logger.warning(f"⚠️ Skipping HEVC encoding: {self.media_file.file_path} is already in the desired format.")
                counter += 1
                preset_log.append("copy")
                crf_log.append("copy")
            else:
                sub_args.extend(video_stream.map_prefix(counter))
                sub_args.extend([self.encoder, "-preset", self.get_preset(video_stream), "-tag:v", "hvc1", "-crf", self.get_crf(video_stream)])
                counter += 1

                preset_log.append(self.get_preset(video_stream))
                crf_log.append(self.get_crf(video_stream))
            
            video_args[video_stream] = sub_args
        
        self.logger.debug(f"🎬 Prepared video arguments: {video_args.values()}")
        self.logger.info(f'🔹 HEVC encoding initialized for "{self.media_file.file_name}" | Preset: {", ".join(preset_log)} | CRF: {", ".join(crf_log)}')
        return video_args
