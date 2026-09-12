from __future__ import annotations

import json
from pathlib import Path

import pytest

from feed_clean.profile import Profile, load_profile

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO


@pytest.fixture(scope="session")
def profile() -> Profile:
    return load_profile(REPO / "profiles" / "supplier.json")


@pytest.fixture(scope="session")
def expected() -> dict:
    """The ground truth fixtures/generate_feed.py wrote alongside the feed."""
    return json.loads((REPO / "tests" / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def feed_path() -> Path:
    return REPO / "fixtures" / "supplier-feed.csv"
