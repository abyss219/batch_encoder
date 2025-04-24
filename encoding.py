import argparse
import os
import sys
from encoder import *
from config import load_config

config = load_config()

DEFAULT_CODEC = "hevc"
VALID_HEVC_PRESETS = {
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
    "placebo",
}


def preset_preset_type(value):
    """
    Validates and processes the preset type for HEVC and AV1.

    - If the input is an integer (0-13), it is treated as an AV1 preset.
    - If the input is a string, it is validated against the set of valid HEVC presets.

    Args:
        value (str): The user-specified preset value.

    Returns:
        Union[int, str]: The processed preset value, either as an integer (AV1) or a lowercase string (HEVC).

    Raises:
        argparse.ArgumentTypeError: If the preset value is invalid.
    """
    # Check if value is an integer (for AV1)
    if value.isdigit():
        ivalue = int(value)
        if 0 <= ivalue <= 13:
            return ivalue
        else:
            raise argparse.ArgumentTypeError(
                "AV1 preset must be an integer between 0 and 13."
            )

    # Check if value is a valid HEVC preset
    if value.lower() in VALID_HEVC_PRESETS:
        return value.lower()

    # If neither, raise an error
    raise argparse.ArgumentTypeError(
        "Invalid preset value. Use a string (HEVC: ultrafast, superfast, etc.) or an integer (AV1: 0-13)."
    )


def parse_arguments():
    """
    Parses command-line arguments using argparse.

    This function defines the available command-line options to control video encoding
    for HEVC (H.265) and AV1 using FFmpeg.

    Options include:
    - Input file path
    - Codec selection (HEVC or AV1)
    - CRF (Constant Rate Factor) for controlling quality vs. file size
    - Encoding preset for speed vs. compression efficiency
    - Option to delete the original video after encoding
    - Output directory selection
    - Verification of encoded file quality using VMAF
    - AV1-specific options such as fast decode optimization and quality tuning

    Returns:
        argparse.Namespace: Parsed arguments containing user-specified values.
    """
    parser = argparse.ArgumentParser(
        description="Convert video to HEVC (H.265) or AV1 using FFmpeg."
    )

    # Required argument: input video file
    parser.add_argument(
        "input_file", help="Path to the input video file that needs to be encoded."
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
        ),
    )

    # Optional argument: CRF (Constant Rate Factor) for quality control
    parser.add_argument(
        "--crf",
        type=int,
        choices=range(0, 64),
        help=(
            "Set the CRF (Constant Rate Factor) value to control video quality.\n"
            "Lower CRF values result in better quality and larger file sizes.\n"
            "Typical ranges:\n"
            "  HEVC: 0-51\n"
            "  AV1:  1-63 \n"
        ),
    )

    # Optional argument: Encoding preset for speed vs compression efficiency
    parser.add_argument(
        "--preset",
        type=preset_preset_type,
        help=(
            "Set the encoding speed preset.\n"
            "For HEVC, use one of the following: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow, placebo.\n"
            "For AV1, use an integer (1-13), where lower values mean slower encoding but better compression.\n"
            "Example: --preset fast (HEVC) or --preset 8 (AV1)."
        ),
    )

    # Optional flag: Delete original file after encoding
    parser.add_argument(
        "--delete-video",
        action="store_true",
        help=(
            "Delete the original video file after encoding.\n"
            "Warning: This action is irreversible."
        ),
    )

    # Optional argument: Output directory for the encoded file
    parser.add_argument(
        "--output-path",
        help=(
            "Specify the directory to save the encoded video.\n"
            "If not provided, the output will be saved in the same directory as the input file."
        ),
    )

    parser.add_argument(
        "--verify",
        action="store_true",
        default=config.verify.verify,
        help=(
            "Verify the encoded file quality using VMAF before deleting the original video.\n"
            "If enabled, the script calculates a VMAF score and only deletes the original\n"
            "if the quality score is above the specified threshold."
        ),
    )

    parser.add_argument(
        "--check-size",
        action="store_true",
        default=config.verify.check_size,
        help=(
            "Enable file size check after encoding.\n"
            "If the encoded video is larger than the original, it will be deleted.\n"
            "Useful for ensuring that encoding results in actual space savings."
        ),
    )

    parser.add_argument(
        "--delete-origin",
        action="store_true",
        default=config.verify.delete_origin,
        help=(
            "Replace the original video with the encoded version.\n"
            "The original file will be deleted only if encoding is successful and passes checks.\n"
            "Use this to save space after verifying the new file is acceptable."
        ),
    )

    # Optional argument: Set VMAF threshold for deletion (default: 90)
    parser.add_argument(
        "--delete-threshold",
        type=lambda x: (
            float(x)
            if 0 <= float(x) <= 100
            else argparse.ArgumentTypeError("Threshold must be between 0 and 100.")
        ),
        default=config.verify.delete_threshold,
        help=(
            "Set the minimum VMAF score required to delete the original video.\n"
            "If the score falls below this threshold, the original video will be retained.\n"
            "Recommended values:\n"
            "  90-100: High-quality retention (default: 90)\n"
            "  80-89: Acceptable quality\n"
            "  <80: Risk of noticeable degradation"
        ),
    )

    parser.add_argument(
        "--fast-decode",
        type=int,
        choices=[0, 1, 2],
        default=config.svt_av1.fast_decode,
        help=(
            "Optimize for decoding speed when using AV1 encoding.\n"
            "0 - No optimization (best compression, slowest decoding)\n"
            "1 - Moderate optimization (balance between size and speed)\n"
            "2 - Maximum optimization (smallest size reduction, fastest decoding)"
        ),
    )

    parser.add_argument(
        "--tune",
        type=int,
        choices=[0, 1, 2],
        default=config.svt_av1.tune,
        help=(
            "Select the quality tuning mode for AV1 encoding.\n"
            "0 - Optimized for visual sharpness\n"
            "1 - Optimized for PSNR (Peak Signal-to-Noise Ratio)\n"
            "2 - Optimized for SSIM (Structural Similarity Index Measure)"
        ),
    )

    parser.add_argument(
        "--debug", action="store_true", help="Enable verbose debug logging."
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    try:
        media = MediaFile(args.input_file, args.debug)
    except ValueError:
        sys.exit(1)
    output_dir = (
        args.output_path if args.output_path else os.path.dirname(args.input_file)
    )

    if args.preset is not None:
        if args.codec == "hevc":
            if (
                not isinstance(args.preset, str)
                or args.preset not in VALID_HEVC_PRESETS
            ):
                print(
                    "Error: --preset must be one of the valid HEVC presets.",
                    file=sys.stderr,
                )
                sys.exit(1)
            else:
                args.preset = args.preset.lower()
        else:
            try:
                av1_preset = int(args.preset)
                if av1_preset < 0 or av1_preset > 13:
                    raise ValueError
                else:
                    args.preset = av1_preset
            except (ValueError, TypeError):
                print(
                    "Error: --preset must be an integer between 0 and 13 for AV1.",
                    file=sys.stderr,
                )
                sys.exit(1)

    if args.codec == "hevc":
        encoder = HevcEncoder(
            media,
            preset=args.preset,
            crf=args.crf,
            verify=args.verify,
            delete_original=args.delete_video,
            delete_threshold=args.delete_threshold,
            output_dir=output_dir,
            check_size = args.check_size,
            debug=args.debug,
        )
    else:
        encoder = SVTAV1Encoder(
            media,
            preset=args.preset,
            crf=args.crf,
            fast_decode=args.fast_decode,
            tune=args.tune,
            verify=args.verify,
            delete_original=args.delete_video,
            delete_threshold=args.delete_threshold,
            output_dir=output_dir,
            check_size = args.check_size,
            debug=args.debug,
        )

    encoder.encode_wrapper()
