"""Shared fixtures: load the recorded REAL provider payloads from tests/fixtures/."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fli_dates():
    return _load("fli_dates.json")


@pytest.fixture
def fli_exact():
    return _load("fli_exact.json")


@pytest.fixture
def serpapi_hotels():
    return _load("serpapi_hotels.json")
