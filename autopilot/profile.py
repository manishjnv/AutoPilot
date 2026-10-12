"""The machine profile: one small JSON file, `~/.autopilot/machine.json` (`AUTOPILOT_HOME` moves it; the tests use that).
It holds facts about this PC that Autopilot learned: when a runner was proved with a real answer (Q11), how each tool
was installed (Q12), and one-time markers (Q20). It never holds a token, a password or a credential file."""
from __future__ import annotations

import json
import os
from pathlib import Path


def profile_path(home: Path | None = None) -> Path:
    return Path(os.environ.get("AUTOPILOT_HOME") or (home or Path.home()) / ".autopilot") / "machine.json"


def read(home: Path | None = None) -> dict:
    try:
        d = json.loads(profile_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def update(patch: dict, home: Path | None = None) -> bool:
    """Merge `patch` into the profile (one level deep for dict values). False when the file cannot be written."""
    d = read(home)
    for k, v in patch.items():
        d[k] = {**d.get(k, {}), **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    p = profile_path(home)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True
