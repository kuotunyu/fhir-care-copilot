from __future__ import annotations

import struct
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_VERSION = "0.2.0"
RELEASE_DATE = "2026-08-03"


def test_package_and_citation_release_metadata_match() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == RELEASE_VERSION
    assert citation["version"] == RELEASE_VERSION
    assert str(citation["date-released"]) == RELEASE_DATE


def test_social_preview_is_the_required_png_size() -> None:
    path = REPO_ROOT / "docs/portfolio/social-preview.png"
    data = path.read_bytes()

    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (1280, 640)
    assert len(data) < 1024 * 1024
