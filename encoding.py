import argparse
import os
import sys
from encoder import *
from encoder.config import *

def parse_arguments():
    """
    Parses command-line arguments using argparse.

    This function sets up command-line options to control video encoding 
    for HEVC (H.265) and AV1 using FFmpeg.

    Available options:
    - Input file path
    - Codec selection (HEVC or AV1)
    - CRF (Constant Rate Factor) value for quality control
    - Preset for encoding speed vs efficiency
    - CPU usage tuning (only for AV1)
    - Option to delete the original video after encoding
    - Output directory selection
    - Verify encoded file quality using VMAF before deleting the original.
    """
    parser = argparse.ArgumentParser(
        description="Convert video to HEVC (H.265) or AV1 using FFmpeg."
    )

    # Required argument: input video file
    parser.add_argument(
        "input_file", 
        help="Path to the input video file that needs to be encoded."
    )

    # Optional argument: Codec selection (default: HEVC)
    parser.add_argument(
        "--codec", 
        choices=["hevc", "av1"], 
        default=DEFAULT_CODEC, 
        help=(
            "Specify the codec to use for encoding.\n"
            "Options:\n"
            "  hevc - High Efficiency Video Coding (H.265) [default]\n"
            "  av1  - AV1 codec for better compression at lower bitrates\n"
            "Note: AV1 encoding is significantly slower than HEVC."
        )
    )

    # Optional argument: CRF (Constant Rate Factor) for quality control
    parser.add_argument(
        "--crf", 
        type=int, 
        help=(
            "Set the CRF (Constant Rate Factor) value for controlling video quality.\n"
            "Lower values give better quality but larger file sizes.\n"
            "Typical ranges:\n"
            "  HEVC: 0-51 (default: 24, good quality: 18-28)\n"
            "  AV1:  0-63 (default: 28, good quality: 20-35)\n"
            "Note: 0 means lossless, but file size will be huge."
        )
    )

    # Optional argument: Encoding preset for speed vs compression efficiency
    parser.add_argument(
        "--preset", 
        help=(
            "Set the encoding speed preset.\n"
            "Faster presets encode quickly but result in larger file sizes.\n"
            "Slower presets optimize compression for better quality at the same bitrate.\n"
            "Defaults:\n"
            "  HEVC: slow (use medium, slow, slower, veryslow, etc.)\n"
            "  AV1:  slow (use veryslow, slow, medium, fast, etc.)\n"
        )
    )

    # Optional argument: CPU usage tuning for AV1 encoding
    parser.add_argument(
        "--cpu-used", 
        type=int, 
        help=(
            "Set the AV1 encoder CPU usage level (only applies to AV1 encoding).\n"
            "Higher values result in faster encoding but worse compression efficiency.\n"
            "Typical range: 0-8 (default: 4)\n"
            "  0  - Best compression, extremely slow encoding\n"
            "  4  - Balanced (default)\n"
            "  8  - Fastest, least efficient compression"
        )
    )

    # Optional flag: Delete original file after encoding
    parser.add_argument(
        "--delete-video", 
        action="store_true", 
        help=(
            "Delete the original video file after encoding.\n"
            "Warning: This action is irreversible."
        )
    )

    # Optional argument: Output directory for the encoded file
    parser.add_argument(
        "--output-path", 
        help=(
            "Specify the directory to save the encoded video.\n"
            "If not provided, the output will be saved in the same directory as the input file."
        )
    )
    
    parser.add_argument(
        "--verify", 
        action="store_true", 
        help=(
            "Verify the encoded file quality using VMAF before deleting the original video.\n"
            "If enabled, the script will calculate a VMAF score and only delete the original\n"
            "if the quality is above the delete threshold."
        )
    )

    # Optional argument: Set VMAF threshold for deletion (default: 90)
    parser.add_argument(
        "--delete-threshold",
        type=float,
        default=DEFAULT_DELETE_THRESHOLD,
        help=(
            "Set the minimum VMAF score required to delete the original video.\n"
            "If VMAF verification is enabled and the encoded video's score is below\n"
            "this threshold, the original video will not be deleted.\n"
            f"Default: {DEFAULT_DELETE_THRESHOLD} (High-quality retention)."
        )
    )

    return parser.parse_args()

if __name__ == "__main__":
    if not check_ffmpeg_installed():
        print("Error: ffmpeg not installed.")
        sys.exit(1)

    args = parse_arguments()
    
    if not os.path.exists(args.input_file):
        print("Error: Input file does not exist.", file=sys.stderr)
        sys.exit(1)
    
    media = MediaFile(args.input_file)
    output_dir = args.output_path if args.output_path else os.path.dirname(args.input_file)
    
    if args.codec == "hevc":
        encoder = HevcEncoder(media, preset=args.preset, crf=args.crf, 
                               verify=args.verify, delete_original=args.delete_video, delete_threshold=args.delete_threshold, 
                               output_dir=output_dir)
    else:
        encoder = LibaomAV1Encoder(media, preset=args.preset, crf=args.crf, cpu_used=args.cpu_used, 
                              verify=args.verify, delete_original=args.delete_video, delete_threshold=args.delete_threshold,
                              output_dir=output_dir)
    
    encoder.encode_wrapper()