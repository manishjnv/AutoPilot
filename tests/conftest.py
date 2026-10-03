import pytest


@pytest.fixture(autouse=True)
def _no_autofix(monkeypatch, tmp_path_factory):
    """Tests must never reinstall the claude CLI or edit the real PATH (doctor.autofix)."""
    monkeypatch.setenv("AUTOPILOT_NO_AUTOFIX", "1")
    monkeypatch.setenv("AUTOPILOT_NO_BROWSER", "1")  # nor open browser tabs
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path_factory.mktemp("aphome")))  # nor the list of recent projects
