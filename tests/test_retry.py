from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from encoder.batch import normalize_path
from encoder.retry import (
    failed_entries_from_report,
    failed_paths_from_report,
    find_summary_reports,
    load_summary_report,
    make_retry_batch_input,
    make_retry_context,
    resolve_retry_report,
)


def write_report(path: Path, report: dict, mtime: float | None = None) -> Path:
    path.write_text(json.dumps(report), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


SAMPLE_REPORT = {
    "run_id": "20260101-000000_videos_deadbeef_abc123",
    "input": {"path": "/data/videos", "label": "videos"},
    "counts": {"FAILED": 2, "LARGESIZE": 1},
    "results": {
        "FAILED": [
            {
                "path": "/data/videos/a.mkv",
                "reason": "Encoding failed.",
                "temp_output_path": "/data/videos/a_HevcEncoder_crf-20.mp4",
            },
            {"path": "/data/videos/b.mp4", "reason": "ffmpeg"},
            {"path": "/data/videos/a.mkv", "reason": "duplicate"},
            {"reason": "no path key"},
        ],
        "LARGESIZE": [{"path": "/data/videos/c.mp4", "reason": "larger"}],
    },
}


def test_failed_paths_selects_only_failed_deduped():
    paths = failed_paths_from_report(SAMPLE_REPORT)

    assert paths == (
        normalize_path("/data/videos/a.mkv"),
        normalize_path("/data/videos/b.mp4"),
    )
    assert all("c.mp4" not in str(p) for p in paths)


def test_failed_paths_supports_dict_shape():
    report = {
        "results": {
            "FAILED": {
                "/x/1.mp4": {"path": "/x/1.mp4"},
                "/x/2.mp4": {"path": "/x/2.mp4"},
            }
        }
    }
    assert len(failed_paths_from_report(report)) == 2


def test_failed_paths_empty_when_no_failed_bucket():
    assert failed_paths_from_report({"results": {}}) == ()
    assert failed_paths_from_report({}) == ()


def test_failed_entries_keyed_by_normalized_path():
    entries = failed_entries_from_report(SAMPLE_REPORT)

    key = str(normalize_path("/data/videos/a.mkv"))
    assert key in entries
    assert entries[key]["temp_output_path"].endswith("a_HevcEncoder_crf-20.mp4")
    # The first occurrence wins on duplicates.
    assert entries[key]["reason"] == "Encoding failed."


def test_make_retry_batch_input():
    batch_input = make_retry_batch_input("/tmp/fake_summary.json", SAMPLE_REPORT)

    assert batch_input.kind == "retry"
    assert batch_input.label == "retry-videos"
    assert len(batch_input.video_paths) == 2
    assert batch_input.source_path == Path("/tmp/fake_summary.json").resolve(strict=False)
    assert batch_input.target_hash


def test_make_retry_context_documents_failed_selection():
    batch_input = make_retry_batch_input("/tmp/fake_summary.json", SAMPLE_REPORT)
    ctx = make_retry_context("/tmp/fake_summary.json", SAMPLE_REPORT, batch_input)

    assert ctx["source_run_id"] == "20260101-000000_videos_deadbeef_abc123"
    assert ctx["source_input"] == "/data/videos"
    assert ctx["selected_status"] == "FAILED"
    assert ctx["selected_failed_count"] == 2
    assert set(ctx["_failed_entries"]) == {
        str(normalize_path("/data/videos/a.mkv")),
        str(normalize_path("/data/videos/b.mp4")),
    }


def test_find_summary_reports_newest_first(tmp_path: Path):
    old = write_report(
        tmp_path / "batch_encoder_old_summary.json", {"results": {}}, mtime=1000
    )
    new = write_report(
        tmp_path / "batch_encoder_new_summary.json", {"results": {}}, mtime=2000
    )
    # A non-summary file must be ignored.
    (tmp_path / "batch_encoder_old.log").write_text("log", encoding="utf-8")

    reports = find_summary_reports(tmp_path)

    assert reports == [new, old]


def test_find_summary_reports_missing_dir(tmp_path: Path):
    assert find_summary_reports(tmp_path / "nope") == []


def test_resolve_retry_report_latest(tmp_path: Path):
    write_report(tmp_path / "batch_encoder_a_summary.json", {"results": {}}, mtime=1000)
    newest = write_report(
        tmp_path / "batch_encoder_b_summary.json", {"results": {}}, mtime=2000
    )

    assert resolve_retry_report("latest", tmp_path) == newest


def test_resolve_retry_report_latest_without_reports(tmp_path: Path):
    with pytest.raises(ValueError):
        resolve_retry_report("latest", tmp_path)


def test_resolve_retry_report_explicit_path(tmp_path: Path):
    report = write_report(tmp_path / "batch_encoder_x_summary.json", SAMPLE_REPORT)

    assert resolve_retry_report(str(report), tmp_path) == report


def test_resolve_retry_report_explicit_missing(tmp_path: Path):
    with pytest.raises(ValueError):
        resolve_retry_report(str(tmp_path / "missing_summary.json"), tmp_path)


def test_resolve_retry_report_interactive(tmp_path: Path, monkeypatch):
    write_report(tmp_path / "batch_encoder_a_summary.json", {"results": {}}, mtime=1000)
    newest = write_report(
        tmp_path / "batch_encoder_b_summary.json", {"results": {}}, mtime=2000
    )

    # Reject an out-of-range value, then accept the first (newest) entry.
    answers = iter(["9", "1"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))

    assert resolve_retry_report(None, tmp_path) == newest


def test_resolve_retry_report_interactive_cancel(tmp_path: Path, monkeypatch):
    write_report(tmp_path / "batch_encoder_a_summary.json", {"results": {}})
    monkeypatch.setattr("builtins.input", lambda *_: "q")

    with pytest.raises(SystemExit):
        resolve_retry_report(None, tmp_path)


def test_load_summary_report_rejects_bad_json(tmp_path: Path):
    bad = tmp_path / "batch_encoder_bad_summary.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_summary_report(bad)
