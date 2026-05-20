from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "manifest.yaml"


@pytest.fixture(scope="session")
def fixture_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def fixture_media_root(fixture_manifest: dict[str, Any]) -> Path:
    root = Path(fixture_manifest["default_media_root"])
    if not root.is_absolute():
        root = REPO_ROOT / root
    return root


@pytest.fixture(scope="session")
def generated_fixture_entries(fixture_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return list(fixture_manifest.get("generated", []))


@pytest.fixture(scope="session")
def available_generated_entries(
    fixture_media_root: Path, generated_fixture_entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    entries = [
        entry
        for entry in generated_fixture_entries
        if (fixture_media_root / entry["path"]).is_file()
    ]
    if not entries:
        pytest.skip(
            "No generated fixtures found. Run: python scripts/prepare_fixtures.py generate --profile generated"
        )
    return entries
