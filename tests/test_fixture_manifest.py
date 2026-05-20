from __future__ import annotations

from pathlib import Path


def test_manifest_has_unique_ids(fixture_manifest):
    entries = fixture_manifest.get("generated", []) + fixture_manifest.get("external", [])
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids))


def test_manifest_paths_are_relative(fixture_manifest):
    entries = fixture_manifest.get("generated", []) + fixture_manifest.get("external", [])
    for entry in entries:
        path = Path(entry["path"])
        assert not path.is_absolute()
        assert ".." not in path.parts


def test_small_profile_stays_under_two_gb_budget(fixture_manifest):
    budget = fixture_manifest["profiles"]["small"]["max_total_bytes"]
    external_budget = sum(entry.get("max_bytes", 0) for entry in fixture_manifest.get("external", []))
    # Synthetic files are intentionally tiny; keep a generous 250 MB reserve for them.
    assert external_budget + 250_000_000 <= budget
