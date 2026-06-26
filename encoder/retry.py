from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

from encoder.batch import BatchInput, normalize_path, short_hash, slugify


SUMMARY_GLOB = "batch_encoder_*_summary.json"


def find_summary_reports(log_dir: Path) -> list[Path]:
    """Return summary JSON reports under ``log_dir``, newest first."""
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return []
    reports = [p for p in log_dir.glob(SUMMARY_GLOB) if p.is_file()]
    reports.sort(key=lambda p: _safe_mtime(p), reverse=True)
    return reports


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def load_summary_report(report_path: Path) -> dict[str, Any]:
    """Load and parse a summary JSON report."""
    report_path = Path(report_path)
    if not report_path.is_file():
        raise ValueError(f"Summary report does not exist: {report_path}")
    try:
        with report_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Could not read summary report {report_path}: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"Summary report is not a JSON object: {report_path}")
    return data


def _iter_failed_entries(report: dict[str, Any]):
    """Yield FAILED result entries, supporting both list and dict shapes."""
    results = report.get("results") or {}
    failed = results.get("FAILED")
    if isinstance(failed, list):
        entries = failed
    elif isinstance(failed, dict):
        entries = list(failed.values())
    else:
        entries = []
    for entry in entries:
        if isinstance(entry, dict):
            yield entry


def failed_entries_from_report(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map normalized failed path -> its report entry, order preserved."""
    entries: dict[str, dict[str, Any]] = {}
    for entry in _iter_failed_entries(report):
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        key = str(normalize_path(path))
        entries.setdefault(key, entry)
    return entries


def failed_paths_from_report(report: dict[str, Any]) -> tuple[Path, ...]:
    """Return the deduplicated, order-preserving list of failed paths."""
    seen: set[str] = set()
    paths: list[Path] = []
    for entry in _iter_failed_entries(report):
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        normalized = normalize_path(path)
        key = str(normalized)
        if key in seen:
            continue
        seen.add(key)
        paths.append(normalized)
    return tuple(paths)


def _report_counts(report: dict[str, Any]) -> dict[str, int]:
    counts = report.get("counts")
    if isinstance(counts, dict):
        return counts
    # Fall back to counting the result buckets directly.
    derived: dict[str, int] = {}
    results = report.get("results") or {}
    for status, bucket in results.items():
        if isinstance(bucket, list):
            derived[status] = len(bucket)
        elif isinstance(bucket, dict):
            derived[status] = len(bucket)
    return derived


def _report_input_label(report: dict[str, Any], report_path: Path) -> str:
    info = report.get("input") or {}
    label = info.get("label")
    if isinstance(label, str) and label.strip():
        return label
    path = info.get("path")
    if isinstance(path, str) and path.strip():
        name = Path(path).name
        if name:
            return name
    return report_path.stem


def select_retry_report_interactively(log_dir: Path) -> Path:
    """Show a newest-first terminal menu and return the chosen report."""
    reports = find_summary_reports(log_dir)
    if not reports:
        raise ValueError(f"No summary reports found in {log_dir}.")

    print("Select summary report to retry:\n")
    for index, report_path in enumerate(reports, start=1):
        line = _format_menu_line(index, report_path)
        print(line)

    while True:
        try:
            choice = input("\nEnter number, or q to cancel: ").strip()
        except EOFError:
            print("\nCancelled.", file=sys.stderr)
            raise SystemExit(1)

        if choice.lower() == "q":
            print("Cancelled.", file=sys.stderr)
            raise SystemExit(1)

        if choice.isdigit():
            number = int(choice)
            if 1 <= number <= len(reports):
                return reports[number - 1]

        print(f"Invalid selection: {choice!r}. Enter 1-{len(reports)} or q.")


def _format_menu_line(index: int, report_path: Path) -> str:
    modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(_safe_mtime(report_path)))
    run_id = report_path.stem
    label = report_path.name
    counts: dict[str, int] = {}
    try:
        report = load_summary_report(report_path)
        run_id = report.get("run_id") or run_id
        label = (report.get("input") or {}).get("path") or label
        counts = _report_counts(report)
    except ValueError:
        pass

    failed = counts.get("FAILED", 0)
    largesize = counts.get("LARGESIZE", 0)
    return (
        f"{index}. {modified} | run {run_id} | "
        f"FAILED {failed} | LARGESIZE {largesize} | {label}"
    )


def resolve_retry_report(target: Optional[str], log_dir: Path) -> Path:
    """Resolve the ``retry`` positional target to a concrete report path."""
    log_dir = Path(log_dir)

    if target is None:
        return select_retry_report_interactively(log_dir)

    if target == "latest":
        reports = find_summary_reports(log_dir)
        if not reports:
            raise ValueError(f"No summary reports found in {log_dir}.")
        return reports[0]

    report_path = Path(target).expanduser()
    if not report_path.is_file():
        raise ValueError(f"Summary report does not exist: {report_path}")
    return report_path


def make_retry_batch_input(report_path: Path, report: dict[str, Any]) -> BatchInput:
    """Build a fresh BatchInput from the FAILED records of a report."""
    report_path = Path(report_path).resolve(strict=False)
    source_label = _report_input_label(report, report_path)
    failed_paths = failed_paths_from_report(report)
    return BatchInput(
        source_path=report_path,
        kind="retry",
        video_paths=failed_paths,
        label=slugify(f"retry-{source_label}"),
        target_hash=short_hash(str(report_path)),
    )


def make_retry_context(
    report_path: Path,
    report: dict[str, Any],
    batch_input: BatchInput,
) -> dict[str, Any]:
    """Build the retry provenance/context attached to the new run."""
    info = report.get("input") or {}
    return {
        "source_report": str(report_path),
        "source_run_id": report.get("run_id"),
        "source_input": info.get("path"),
        "selected_status": "FAILED",
        "selected_failed_count": len(batch_input.video_paths),
        # Internal: failed entries keyed by normalized path, used to warn about
        # leftover temp outputs. Not emitted verbatim into the new report.
        "_failed_entries": failed_entries_from_report(report),
    }
