"""共用 pytest fixtures。"""

from pathlib import Path

import pytest

from fhir_copilot.store import LocalBundleFHIRStore

FIXTURES_DIR = Path(__file__).parent / "data" / "fixtures"

AMY_ID = "a1000000-0000-0000-0000-000000000001"
BEN_ID = "b2000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="session")
def store() -> LocalBundleFHIRStore:
    return LocalBundleFHIRStore(FIXTURES_DIR)
