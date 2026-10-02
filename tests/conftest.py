import pytest


@pytest.fixture(autouse=True)
def _no_autofix(monkeypatch):
    """Tests must never reinstall the claude CLI or edit the real PATH (doctor.autofix)."""
    monkeypatch.setenv("AUTOPILOT_NO_AUTOFIX", "1")
