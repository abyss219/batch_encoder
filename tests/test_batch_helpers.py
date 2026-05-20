from __future__ import annotations

from pathlib import Path

import pytest

from encoder.batch import (
    EFFICIENT_CODECS,
    discover_batch_input,
    format_skip_codecs,
    make_run_id,
    resolve_skip_codecs,
)


def test_resolve_skip_codecs_presets():
    assert resolve_skip_codecs("efficient") == set(EFFICIENT_CODECS)
    assert resolve_skip_codecs("none") == set()
    assert resolve_skip_codecs(["hevc", "vp9"]) == {"hevc", "vp9"}
    assert resolve_skip_codecs("hevc,vp9") == {"hevc", "vp9"}


def test_resolve_skip_codecs_rejects_mixed_presets():
    with pytest.raises(ValueError):
        resolve_skip_codecs(["efficient", "hevc"])
    with pytest.raises(ValueError):
        resolve_skip_codecs(["none", "hevc"])


def test_discover_batch_input_list_file(tmp_path: Path):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"not a real video")
    list_file = tmp_path / "videos.txt"
    list_file.write_text("# comment\nsample.mp4\nsample.mp4\n", encoding="utf-8")

    batch_input = discover_batch_input(list_file)

    assert batch_input.kind == "list"
    assert batch_input.video_paths == (video.resolve(strict=False),)
    assert batch_input.label == "videos.txt"
    assert batch_input.target_hash


def test_make_run_id_includes_target_label(tmp_path: Path):
    list_file = tmp_path / "my-video-list.txt"
    list_file.write_text("", encoding="utf-8")
    batch_input = discover_batch_input(list_file)

    run_id = make_run_id(batch_input)

    assert "my-video-list.txt" in run_id
    assert batch_input.target_hash in run_id


def test_format_skip_codecs():
    assert format_skip_codecs(set(EFFICIENT_CODECS)) == "efficient"
    assert format_skip_codecs(set()) == "none"
    assert format_skip_codecs({"vp9", "hevc"}) == "hevc,vp9"
