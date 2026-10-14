"""Q12: `ap setup` can be run again. Every step writes {name, status, date, detail} to `~/.autopilot/setup.json` when it
ends; a rerun prints the finished steps as `done` lines and continues at the first step that is not finished. `ap setup
--reset` clears the file. `ap uninstall --steps` undoes each finished step in reverse. The install method of every tool
(native, winget, brew, npm, pip, uv) goes into the machine profile so `ap upgrade` and `ap uninstall` use the matching
command. No credential file is read or written here."""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

from . import profile

ORDER = ("uv", "python", "autopilot", "runner", "login", "probe", "config")  # the order a rerun walks through


def state_path(home: Path | None = None) -> Path:
    return Path(os.environ.get("AUTOPILOT_HOME") or (home or Path.home()) / ".autopilot") / "setup.json"  # same rule as profile.py


def load(home: Path | None = None) -> dict:
    """name -> {name, status, date, detail}; {} when there is no file or it is unreadable."""
    try:
        rows = json.loads(state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {r["name"]: r for r in rows if isinstance(r, dict) and r.get("name")} if isinstance(rows, list) else {}


def record(name: str, status: str, detail: str = "", home: Path | None = None) -> None:
    """Write one step as it ends. status: done, failed or skipped. Never raises (a read-only home only loses the resume)."""
    rows = load(home)
    rows[name] = {"name": name, "status": status, "date": datetime.date.today().isoformat(), "detail": detail}
    ordered = sorted(rows.values(), key=lambda r: ORDER.index(r["name"]) if r["name"] in ORDER else len(ORDER))
    p = state_path(home)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def reset(home: Path | None = None) -> bool:
    """`ap setup --reset`: forget every step. True when a file was removed."""
    try:
        state_path(home).unlink()
        return True
    except OSError:
        return False


def is_done(rows: dict, name: str) -> bool:
    return rows.get(name, {}).get("status") == "done"


def done_line(rows: dict, name: str) -> str:
    r = rows[name]
    return f"done      {name}: {r.get('detail') or 'finished'} ({r.get('date', '')})"


def method_of(cmd: str) -> str:
    """The install method a command line stands for: winget, brew, npm, pip, uv, or native (the vendor's own script)."""
    c = (cmd or "").strip().lower()
    c = re.sub(r"^(?:sudo |& |cmd /c |powershell -command )+", "", c)  # the first real token decides
    if c.startswith("winget"):
        return "winget"
    if c.startswith("brew"):
        return "brew"
    if c.startswith(("npm ", "npx ")):
        return "npm"
    if re.match(r"^(python3?|py)( -\d)?( -m)? pip |^pip3? ", c):
        return "pip"
    if c.startswith("uv "):
        return "uv"
    return "native"


def remember_method(tool: str, method: str, home: Path | None = None) -> None:
    profile.update({"install": {tool: method}}, home)


def recorded_method(tool: str, home: Path | None = None) -> str:
    return str((profile.read(home).get("install") or {}).get(tool, ""))


def undo_plan(home: Path | None = None, platform: str | None = None) -> list[tuple[str, str]]:
    """(step, what happens) for every finished step, in reverse order. Only what Autopilot's own record says it did:
    the runner CLI by the method it was installed with, the written choice. uv, Python and git are never removed."""
    from .doctor import RUNNERS
    rows = load(home)
    out: list[tuple[str, str]] = []
    for name in reversed(ORDER):
        if not is_done(rows, name):
            continue
        if name == "config":
            out.append((name, "delete the runner choice (~/.autopilot/runner and the machine profile)"))
        elif name == "runner":
            row = next((r for r in RUNNERS if r.name in rows[name].get("detail", "")), None)
            how = recorded_method(row.key, home) if row else ""
            cmd = uninstall_cmd(row, how, platform) if row and how else ""
            out.append((name, cmd or "keep the runner CLI (it was found, not installed by Autopilot)"))
        else:
            out.append((name, "keep (uv, Python and the Autopilot package are removed with `ap uninstall --all`)"))
    return out


def uninstall_cmd(row, method: str, platform: str | None = None) -> str:
    """The undo command of a runner row for the recorded method ('' when the row has none for it)."""
    key = method if method != "native" else ("native-windows" if (platform or sys.platform).startswith("win") else "native-posix")
    return row.uninstall.get(key, "")


def undo_argvs(what: str, platform: str | None = None) -> list[list[str]]:
    """L6: an undo string as argv lists, run with shell=False. `&&` / `;` split the steps, `~` is expanded here.
    A PowerShell undo (Remove-Item ...) runs through powershell with the whole string as its one -Command argument."""
    import shlex
    if (platform or sys.platform).startswith("win"):
        if what.startswith("Remove-Item"):
            return [["powershell", "-NoProfile", "-Command", what]]
        return [shlex.split(c, posix=False) for c in re.split(r"\s*(?:&&|;)\s*", what) if c]
    return [[os.path.expanduser(a) for a in shlex.split(c)] for c in re.split(r"\s*(?:&&|;)\s*", what) if c]
