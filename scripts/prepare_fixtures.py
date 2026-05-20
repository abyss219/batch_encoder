#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "manifest.yaml"
LOCK_PATH = REPO_ROOT / "tests" / "fixtures" / "fixture_hashes.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate, download, and verify media fixtures.")
    parser.add_argument(
        "command",
        choices=["generate", "download", "verify", "list", "clean"],
        help="Fixture action to run.",
    )
    parser.add_argument("--profile", default="small", help="Manifest profile to use.")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override fixture media root. Defaults to manifest default_media_root.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate or redownload existing files.")
    parser.add_argument(
        "--write-lock",
        action="store_true",
        help="Write sha256/size lock data for selected fixtures.",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    root = resolve_media_root(manifest, args.root)
    selected = select_entries(manifest, args.profile)

    check_tools()

    if args.command == "list":
        list_entries(selected, root)
    elif args.command == "generate":
        generate_entries(selected["generated"], root, force=args.force)
    elif args.command == "download":
        download_entries(selected["external"], root, force=args.force)
    elif args.command == "verify":
        verify_entries(selected, root, write_lock=args.write_lock)
    elif args.command == "clean":
        clean_root(root)

    return 0


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_media_root(manifest: dict[str, Any], override: Path | None) -> Path:
    root = override or Path(manifest["default_media_root"])
    if not root.is_absolute():
        root = REPO_ROOT / root
    return root


def select_entries(manifest: dict[str, Any], profile: str) -> dict[str, list[dict[str, Any]]]:
    profiles = manifest.get("profiles", {})
    if profile not in profiles:
        raise SystemExit(f"Unknown profile '{profile}'. Available: {', '.join(sorted(profiles))}")

    include_tags = set(profiles[profile].get("include_tags", []))
    generated = [
        entry
        for entry in manifest.get("generated", [])
        if include_tags.intersection(entry.get("tags", []))
    ]
    external = [
        entry
        for entry in manifest.get("external", [])
        if include_tags.intersection(entry.get("tags", []))
    ]
    return {"generated": generated, "external": external}


def check_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise SystemExit(f"Missing required tool: {tool}")


def list_entries(selected: dict[str, list[dict[str, Any]]], root: Path) -> None:
    print(f"Fixture root: {root}")
    for kind, entries in selected.items():
        print(f"\n{kind}:")
        for entry in entries:
            path = root / entry["path"]
            exists = "yes" if path.exists() else "no"
            print(f"  {entry['id']}: {path} (exists: {exists})")


def generate_entries(entries: list[dict[str, Any]], root: Path, force: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        output = root / entry["path"]
        if output.exists() and not force:
            print(f"exists: {entry['id']} -> {output}")
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()

        recipe_name = entry["recipe"]
        recipe = RECIPES.get(recipe_name)
        if recipe is None:
            raise SystemExit(f"Unknown recipe '{recipe_name}' for fixture {entry['id']}")
        print(f"generate: {entry['id']} -> {output}")
        recipe(output)


def download_entries(entries: list[dict[str, Any]], root: Path, force: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        output = root / entry["path"]
        if output.exists() and not force:
            print(f"exists: {entry['id']} -> {output}")
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        print(f"download: {entry['id']} <- {entry['url']}")
        download_file(entry["url"], output, max_bytes=entry.get("max_bytes"))


def download_file(url: str, output: Path, max_bytes: int | None) -> None:
    try:
        _download_file(url, output, max_bytes=max_bytes)
    except urllib.error.URLError:
        if url.startswith("https://samples.ffmpeg.org/"):
            fallback_url = "http://" + url.removeprefix("https://")
            _download_file(fallback_url, output, max_bytes=max_bytes)
        else:
            raise


def _download_file(url: str, output: Path, max_bytes: int | None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "batch-encoder-fixtures/1.0"})
    downloaded = 0
    with urllib.request.urlopen(request, timeout=60) as response:
        with output.open("wb") as f:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if max_bytes is not None and downloaded > max_bytes:
                    raise SystemExit(f"Download exceeds max_bytes for {url}")
                f.write(chunk)


def verify_entries(
    selected: dict[str, list[dict[str, Any]]], root: Path, write_lock: bool
) -> None:
    lock: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for kind in ("generated", "external"):
        for entry in selected[kind]:
            path = root / entry["path"]
            try:
                verify_entry(entry, path)
                lock[entry["id"]] = {
                    "path": entry["path"],
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "streams": ffprobe_summary(path),
                }
                print(f"ok: {entry['id']} -> {path}")
            except Exception as exc:
                failures.append(f"{entry['id']}: {exc}")

    if write_lock:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_PATH.open("w", encoding="utf-8") as f:
            json.dump(lock, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote lock: {LOCK_PATH}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)


def verify_entry(entry: dict[str, Any], path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    max_bytes = entry.get("max_bytes")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ValueError(f"{path} exceeds max_bytes={max_bytes}")

    summary = ffprobe_summary(path)
    expect = entry.get("expect", {})
    if "video_streams" in expect and summary["video_streams"] != expect["video_streams"]:
        raise ValueError(
            f"expected {expect['video_streams']} video streams, got {summary['video_streams']}"
        )
    if "audio_streams" in expect and summary["audio_streams"] != expect["audio_streams"]:
        raise ValueError(
            f"expected {expect['audio_streams']} audio streams, got {summary['audio_streams']}"
        )
    if "video_codecs" in expect:
        missing = set(expect["video_codecs"]) - set(summary["video_codecs"])
        if missing:
            raise ValueError(f"missing video codecs: {sorted(missing)}")
    if "audio_codecs" in expect:
        missing = set(expect["audio_codecs"]) - set(summary["audio_codecs"])
        if missing:
            raise ValueError(f"missing audio codecs: {sorted(missing)}")

    for key in (
        "video_profiles",
        "video_pix_fmts",
        "color_primaries",
        "color_transfers",
        "color_spaces",
        "field_orders",
        "sample_aspect_ratios",
    ):
        if key in expect:
            missing = set(expect[key]) - set(summary.get(key, []))
            if missing:
                raise ValueError(f"missing {key}: {sorted(missing)}")


def ffprobe_summary(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    subtitles = [stream for stream in streams if stream.get("codec_type") == "subtitle"]
    return {
        "video_streams": len(video),
        "audio_streams": len(audio),
        "subtitle_streams": len(subtitles),
        "video_codecs": sorted({stream.get("codec_name") for stream in video if stream.get("codec_name")}),
        "audio_codecs": sorted({stream.get("codec_name") for stream in audio if stream.get("codec_name")}),
        "subtitle_codecs": sorted(
            {stream.get("codec_name") for stream in subtitles if stream.get("codec_name")}
        ),
        "video_profiles": sorted({stream.get("profile") for stream in video if stream.get("profile")}),
        "video_pix_fmts": sorted({stream.get("pix_fmt") for stream in video if stream.get("pix_fmt")}),
        "color_primaries": sorted(
            {stream.get("color_primaries") for stream in video if stream.get("color_primaries")}
        ),
        "color_transfers": sorted(
            {stream.get("color_transfer") for stream in video if stream.get("color_transfer")}
        ),
        "color_spaces": sorted({stream.get("color_space") for stream in video if stream.get("color_space")}),
        "field_orders": sorted({stream.get("field_order") for stream in video if stream.get("field_order")}),
        "sample_aspect_ratios": sorted(
            {stream.get("sample_aspect_ratio") for stream in video if stream.get("sample_aspect_ratio")}
        ),
        "duration": info.get("format", {}).get("duration"),
        "size": info.get("format", {}).get("size"),
    }


def clean_root(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
        print(f"removed: {root}")
    else:
        print(f"not found: {root}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True)


def lavfi_video(duration: int = 2, size: str = "320x180", rate: int = 24) -> list[str]:
    return ["-f", "lavfi", "-i", f"testsrc2=duration={duration}:size={size}:rate={rate}"]


def sine_input(frequency: int = 440, duration: int = 2, sample_rate: int | None = None) -> list[str]:
    source = f"sine=frequency={frequency}:duration={duration}"
    if sample_rate is not None:
        source += f":sample_rate={sample_rate}"
    return ["-f", "lavfi", "-i", source]


def h264_aac_mp4(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(),
            *sine_input(),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-metadata",
            "title=batch_encoder_h264_aac",
            str(output),
        ]
    )


def hevc_aac_mp4(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(),
            *sine_input(550),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-crf",
            "34",
            "-pix_fmt",
            "yuv420p",
            "-tag:v",
            "hvc1",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(output),
        ]
    )


def av1_opus_mkv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="160x90", rate=12),
            *sine_input(660, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libsvtav1",
            "-preset",
            "12",
            "-crf",
            "45",
            "-c:a",
            "libopus",
            "-b:a",
            "48k",
            str(output),
        ]
    )


def vp9_opus_webm(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="240x136"),
            *sine_input(770),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libvpx-vp9",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-b:v",
            "0",
            "-crf",
            "40",
            "-c:a",
            "libopus",
            "-b:a",
            "48k",
            str(output),
        ]
    )


def theora_vorbis_ogv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="240x136"),
            *sine_input(880),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libtheora",
            "-q:v",
            "4",
            "-c:a",
            "libvorbis",
            "-q:a",
            "3",
            str(output),
        ]
    )


def mpeg4_mp3_avi(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="240x136"),
            *sine_input(330),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "mpeg4",
            "-q:v",
            "8",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "6",
            str(output),
        ]
    )


def mpeg2_ac3_ts(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="320x180"),
            *sine_input(220),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "mpeg2video",
            "-q:v",
            "5",
            "-c:a",
            "ac3",
            "-b:a",
            "96k",
            "-f",
            "mpegts",
            str(output),
        ]
    )


def multi_audio_mkv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(),
            *sine_input(440),
            *sine_input(550),
            *sine_input(660),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-map",
            "3:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a:0",
            "aac",
            "-b:a:0",
            "80k",
            "-c:a:1",
            "libopus",
            "-b:a:1",
            "48k",
            "-c:a:2",
            "ac3",
            "-b:a:2",
            "96k",
            "-metadata:s:a:0",
            "language=eng",
            "-metadata:s:a:1",
            "language=jpn",
            "-metadata:s:a:2",
            "language=spa",
            str(output),
        ]
    )


def multi_video_mkv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="320x180"),
            *lavfi_video(size="160x90", rate=12),
            *sine_input(990),
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-map",
            "2:a",
            "-c:v:0",
            "libx264",
            "-preset:v:0",
            "ultrafast",
            "-crf:v:0",
            "30",
            "-pix_fmt:v:0",
            "yuv420p",
            "-c:v:1",
            "mpeg4",
            "-q:v:1",
            "8",
            "-c:a",
            "aac",
            "-b:a",
            "80k",
            str(output),
        ]
    )


def subtitles_mkv(output: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        subtitle = Path(tmp) / "fixture.srt"
        subtitle.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nBatch encoder subtitle fixture\n",
            encoding="utf-8",
        )
        run_ffmpeg(
            [
                *lavfi_video(),
                *sine_input(440),
                "-i",
                str(subtitle),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-map",
                "2:s",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "30",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-c:s",
                "srt",
                str(output),
            ]
        )


def attached_pic_mp4(output: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cover = Path(tmp) / "cover.jpg"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:size=128x128:duration=0.1",
                "-frames:v",
                "1",
                str(cover),
            ]
        )
        run_ffmpeg(
            [
                *lavfi_video(),
                *sine_input(440),
                "-i",
                str(cover),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-map",
                "2:v",
                "-c:v:0",
                "libx264",
                "-preset:v:0",
                "ultrafast",
                "-crf:v:0",
                "30",
                "-pix_fmt:v:0",
                "yuv420p",
                "-c:a",
                "aac",
                "-c:v:1",
                "mjpeg",
                "-disposition:v:1",
                "attached_pic",
                "-metadata:s:v:1",
                "title=cover",
                str(output),
            ]
        )


def no_audio_mp4(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(),
            "-map",
            "0:v",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output),
        ]
    )


def ten_bit_hevc_mkv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="240x136"),
            *sine_input(500),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-vf",
            "format=yuv420p10le",
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-crf",
            "36",
            "-pix_fmt",
            "yuv420p10le",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(output),
        ]
    )


def odd_rgb_mkv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="127x95"),
            *sine_input(700),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264rgb",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "rgb24",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(output),
        ]
    )


def rotation_metadata_mov(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="180x320"),
            *sine_input(440),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-metadata:s:v:0",
            "rotate=90",
            str(output),
        ]
    )


def lowres_h264_mp4(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(size="96x54", rate=12),
            *sine_input(440),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            str(output),
        ]
    )


def hdr10_hevc_mkv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="320x180", rate=24),
            *sine_input(440, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-vf",
            (
                "format=yuv420p10le,"
                "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc"
            ),
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-crf",
            "36",
            "-pix_fmt",
            "yuv420p10le",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "smpte2084",
            "-colorspace",
            "bt2020nc",
            "-color_range",
            "tv",
            "-x265-params",
            (
                "hdr10=1:repeat-headers=1:colorprim=bt2020:transfer=smpte2084:"
                "colormatrix=bt2020nc:max-cll=1000,400:"
                "master-display=G(13250,34500)B(7500,3000)"
                "R(34000,16000)WP(15635,16450)L(10000000,1)"
            ),
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(output),
        ]
    )


def hlg_hevc_mov(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="320x180", rate=24),
            *sine_input(523, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-vf",
            (
                "format=yuv420p10le,"
                "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc"
            ),
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-crf",
            "36",
            "-pix_fmt",
            "yuv420p10le",
            "-tag:v",
            "hvc1",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "arib-std-b67",
            "-colorspace",
            "bt2020nc",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(output),
        ]
    )


def prores_422_mov(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="192x108", rate=24),
            *sine_input(440, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-vf",
            "format=yuv422p10le",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "2",
            "-pix_fmt",
            "yuv422p10le",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )


def dnxhr_mxf(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="1280x720", rate=24),
            *sine_input(494, duration=1, sample_rate=48000),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "dnxhd",
            "-profile:v",
            "dnxhr_lb",
            "-pix_fmt",
            "yuv422p",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )


def ffv1_flac_mkv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="160x90", rate=12),
            *sine_input(587, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-g",
            "1",
            "-c:a",
            "flac",
            str(output),
        ]
    )


def huffyuv_pcm_avi(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="160x90", rate=12),
            *sine_input(659, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-vf",
            "format=yuv422p",
            "-c:v",
            "huffyuv",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )


def flv1_mp3_flv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="160x90", rate=12),
            *sine_input(698, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "flv",
            "-q:v",
            "7",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "6",
            str(output),
        ]
    )


def wmv2_wmav2_wmv(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="160x90", rate=12),
            *sine_input(784, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "wmv2",
            "-b:v",
            "300k",
            "-c:a",
            "wmav2",
            "-b:a",
            "64k",
            str(output),
        ]
    )


def interlaced_mpeg2_mpg(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="320x240", rate=24),
            *sine_input(880, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "mpeg2video",
            "-flags",
            "+ildct+ilme",
            "-top",
            "1",
            "-q:v",
            "5",
            "-c:a",
            "mp2",
            "-b:a",
            "96k",
            str(output),
        ]
    )


def anamorphic_h264_mp4(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="320x240", rate=24),
            *sine_input(932, duration=1),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-vf",
            "setsar=4/3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(output),
        ]
    )


def alpha_qtrle_mov(output: Path) -> None:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red@0.5:size=160x90:duration=1:rate=12,format=argb",
            "-c:v",
            "qtrle",
            "-pix_fmt",
            "argb",
            "-an",
            str(output),
        ]
    )


def raw_h264_annexb(output: Path) -> None:
    run_ffmpeg(
        [
            *lavfi_video(duration=1, size="160x90", rate=12),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-f",
            "h264",
            str(output),
        ]
    )


def ntsc_dv(output: Path) -> None:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=1:size=720x480:rate=30000/1001",
            *sine_input(440, duration=1, sample_rate=48000),
            "-target",
            "ntsc-dv",
            str(output),
        ]
    )


RECIPES: dict[str, Callable[[Path], None]] = {
    "h264_aac_mp4": h264_aac_mp4,
    "hevc_aac_mp4": hevc_aac_mp4,
    "av1_opus_mkv": av1_opus_mkv,
    "vp9_opus_webm": vp9_opus_webm,
    "theora_vorbis_ogv": theora_vorbis_ogv,
    "mpeg4_mp3_avi": mpeg4_mp3_avi,
    "mpeg2_ac3_ts": mpeg2_ac3_ts,
    "multi_audio_mkv": multi_audio_mkv,
    "multi_video_mkv": multi_video_mkv,
    "subtitles_mkv": subtitles_mkv,
    "attached_pic_mp4": attached_pic_mp4,
    "no_audio_mp4": no_audio_mp4,
    "ten_bit_hevc_mkv": ten_bit_hevc_mkv,
    "odd_rgb_mkv": odd_rgb_mkv,
    "rotation_metadata_mov": rotation_metadata_mov,
    "lowres_h264_mp4": lowres_h264_mp4,
    "hdr10_hevc_mkv": hdr10_hevc_mkv,
    "hlg_hevc_mov": hlg_hevc_mov,
    "prores_422_mov": prores_422_mov,
    "dnxhr_mxf": dnxhr_mxf,
    "ffv1_flac_mkv": ffv1_flac_mkv,
    "huffyuv_pcm_avi": huffyuv_pcm_avi,
    "flv1_mp3_flv": flv1_mp3_flv,
    "wmv2_wmav2_wmv": wmv2_wmav2_wmv,
    "interlaced_mpeg2_mpg": interlaced_mpeg2_mpg,
    "anamorphic_h264_mp4": anamorphic_h264_mp4,
    "alpha_qtrle_mov": alpha_qtrle_mov,
    "raw_h264_annexb": raw_h264_annexb,
    "ntsc_dv": ntsc_dv,
}


if __name__ == "__main__":
    sys.exit(main())
