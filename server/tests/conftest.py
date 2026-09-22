from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
