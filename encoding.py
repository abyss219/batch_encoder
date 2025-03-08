import argparse
import os
import sys
from encoder import *
from encoder.config import *

DEFAULT_CODEC = 'hevc'
VALID_HEVC_PRESETS = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo"}

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
    - Option to delete the original video after encoding
    - Output directory selection
    - Verify encoded file quality using VMAF before deleting the original.
    - Fast decode optimization for AV1
    - Quality tuning mode for AV1
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
            "  HEVC: 0-51\n"
            "  AV1:  0-63\n"
            "Note: 0 means lossless, but file size will be huge."
        )
    )

    # Optional argument: Encoding preset for speed vs compression efficiency
    parser.add_argument(
        "--preset", 
        help=(
            "Set the encoding speed preset.\n"
            "For HEVC: A string value (ultrafast, superfast, veryfast, etc.).\n"
            "For AV1: An integer (0-13), where lower values mean slower but better compression."
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

    parser.add_argument(
        "--fast-decode", 
        type=int, 
        choices=[0, 1, 2], 
        default=DEFAULT_SVTAV1_FAST_DECODE, 
        help="Optimize for decoding speed (0-3). Applies only to AV1 encoding."
    )
    
    parser.add_argument(
        "--tune", 
        type=int, 
        choices=[0, 1, 2], 
        default=DEFAULT_SVTAV1_TUNE, 
        help="Quality tuning mode for AV1 (0 = sharpness, 1 = PSNR optimization)."
    )
    
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    
    try:
        media = MediaFile(args.input_file)
    except ValueError:
        sys.exit(1)
    output_dir = args.output_path if args.output_path else os.path.dirname(args.input_file)

    if args.codec == "hevc":
        if not isinstance(args.preset, str) or args.preset not in VALID_HEVC_PRESETS:
            print("Error: --preset must be one of the valid HEVC presets.", file=sys.stderr)
            sys.exit(1)
        encoder = HevcEncoder(media, preset=args.preset, crf=args.crf, verify=args.verify, 
                              delete_original=args.delete_video, delete_threshold=args.delete_threshold, 
                              output_dir=output_dir)
    else:
        try:
            av1_preset = int(args.preset)
            if av1_preset < 0 or av1_preset > 13:
                raise ValueError
        except (ValueError, TypeError):
            print("Error: --preset must be an integer between 0 and 13 for AV1.", file=sys.stderr)
            sys.exit(1)
        
        encoder = SVTAV1Encoder(media, preset=av1_preset, crf=args.crf, fast_decode=args.fast_decode, tune=args.tune, 
                                   verify=args.verify, delete_original=args.delete_video, delete_threshold=args.delete_threshold, 
                                   output_dir=output_dir)
    
    encoder.encode_wrapper()