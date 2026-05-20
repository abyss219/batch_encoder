from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


VIDEO_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".flv",
    ".webm",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".m4v",
    ".3gp",
    ".3g2",
    ".ts",
    ".m2ts",
    ".mts",
    ".vob",
    ".ogv",
    ".rm",
    ".rmvb",
    ".divx",
    ".f4v",
    ".swf",
    ".amv",
    ".asf",
    ".mxf",
    ".dv",
    ".qt",
    ".yuv",
    ".mpe",
    ".mpv",
    ".m1v",
    ".m2v",
    ".svi",
    ".drc",
    ".ivf",
    ".nsv",
    ".fli",
    ".flc",
    ".gxf",
    ".roq",
    ".smi",
    ".smil",
    ".wm",
    ".wtv",
)

EFFICIENT_CODECS = frozenset({"av1", "hevc", "vp9", "vvc", "theora"})


@dataclass(frozen=True)
class BatchInput:
    source_path: Path
    kind: str
    video_paths: tuple[Path, ...]
    label: str
    target_hash: str


def normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def short_hash(value: str, length: int = 8) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()[:length]


def slugify(value: str, max_length: int = 40) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    if not slug:
        slug = "input"
    if len(slug) <= max_length:
        return slug
    keep = max_length - 9
    return f"{slug[:keep]}-{short_hash(slug)}"


def resolve_skip_codecs(raw_value: str | Sequence[str] | None) -> set[str]:
    if raw_value is None:
        return set(EFFICIENT_CODECS)

    if isinstance(raw_value, str):
        raw_items: Iterable[str] = [raw_value]
    else:
        raw_items = raw_value

    codecs: list[str] = []
    for item in raw_items:
        codecs.extend(part.strip().lower() for part in str(item).split(","))

    codecs = [codec for codec in codecs if codec]
    if not codecs or codecs == ["efficient"]:
        return set(EFFICIENT_CODECS)
    if codecs == ["none"]:
        return set()
    if "efficient" in codecs or "none" in codecs:
        raise ValueError(
            "--skip-codecs accepts either 'efficient', 'none', or a codec list, not a mix."
        )
    return set(codecs)


def format_skip_codecs(skip_codecs: set[str]) -> str:
    if skip_codecs == set(EFFICIENT_CODECS):
        return "efficient"
    if not skip_codecs:
        return "none"
    return ",".join(sorted(skip_codecs))


def discover_batch_input(raw_input: str | Path) -> BatchInput:
    source_path = normalize_path(raw_input)
    if not source_path.exists():
        raise ValueError(f"Input path does not exist: {source_path}")

    if source_path.is_dir():
        kind = "directory"
        video_paths = tuple(_iter_directory_videos(source_path))
    elif source_path.is_file() and source_path.suffix.lower() in VIDEO_EXTENSIONS:
        kind = "file"
        video_paths = (source_path,)
    elif source_path.is_file():
        kind = "list"
        video_paths = tuple(_iter_list_file_videos(source_path))
    else:
        raise ValueError(f"Input path is not a directory or file: {source_path}")

    target_hash = short_hash(str(source_path))
    label_source = source_path.name or source_path.parent.name or "input"
    return BatchInput(
        source_path=source_path,
        kind=kind,
        video_paths=_dedupe_paths(video_paths),
        label=slugify(label_source),
        target_hash=target_hash,
    )


def make_run_id(batch_input: BatchInput) -> str:
    now_ns = time.time_ns()
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now_ns / 1_000_000_000))
    nonce = short_hash(str(now_ns), length=6)
    return f"{timestamp}_{batch_input.label}_{batch_input.target_hash}_{nonce}"


def make_state_id(
    batch_input: BatchInput,
    codec: str,
    min_size: str,
    min_resolution: str | None,
    skip_codecs: set[str],
) -> str:
    raw_state_key = "|".join(
        [
            batch_input.kind,
            str(batch_input.source_path),
            codec,
            str(min_size),
            str(min_resolution),
            format_skip_codecs(skip_codecs),
        ]
    )
    return short_hash(raw_state_key, length=12)


def _iter_directory_videos(directory: Path) -> list[Path]:
    video_paths: list[Path] = []
    for dirpath, _, filenames in os.walk(directory):
        for name in filenames:
            if name.lower().endswith(VIDEO_EXTENSIONS):
                video_paths.append(normalize_path(Path(dirpath) / name))
    return sorted(video_paths)


def _iter_list_file_videos(list_file: Path) -> list[Path]:
    base_dir = list_file.parent
    video_paths: list[Path] = []
    with list_file.open("r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if not value or value.startswith("#"):
                continue

            path = Path(value).expanduser()
            if not path.is_absolute():
                path = base_dir / path
            video_paths.append(normalize_path(path))
    return video_paths


def _dedupe_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return tuple(deduped)
