import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "state.sample.json"


@pytest.fixture
def state() -> dict:
    """The real-shaped, sanitised state.json fixture."""
    return json.loads(FIXTURE.read_text())
