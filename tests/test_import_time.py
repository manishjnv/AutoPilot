"""W47: `ap` must start fast. Slow modules load inside the function that needs them."""
import os
import re
import subprocess
import sys

import pytest


def _run(code, *flags):
    return subprocess.run([sys.executable, *flags, "-c", code], capture_output=True, text=True, timeout=120)


@pytest.mark.skipif(bool(os.environ.get("CI")) or sys.platform == "win32", reason="slow host")
def test_cli_and_orchestrator_import_time():
    err = _run("import autopilot.cli, autopilot.orchestrator", "-X", "importtime").stderr
    cum = {m.group(2): int(m.group(1)) for m in re.finditer(r"\|\s*(\d+) \| (autopilot\.(?:cli|orchestrator))$", err, re.M)}
    assert set(cum) == {"autopilot.cli", "autopilot.orchestrator"}, err[-500:]
    assert sum(cum.values()) < 1_000_000, cum  # microseconds; the roadmap target is 0.5 s


def test_error_path_modules_stay_unloaded():
    out = _run("import autopilot.outage, autopilot.signals, sys; print('urllib.request' in sys.modules, 'http.client' in sys.modules)")
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "False"]  # doctor stays: install_errors builds its table from it, and it is cheap now
