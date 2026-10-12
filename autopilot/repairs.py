"""Q20: five repairs without a question. Each returns one plain line (or '' when there is nothing to do) and is safe to run
again. Python never builds or runs an elevated PowerShell string: the Defender step only prints one line, because the
N8 scheduled task installs winget ids only (widening its elevated body is a change for the owner to review).

1. safe.directory and autocrlf for the project (the Q21 lines, applied and logged)
2. a persistent PATH, once: `uv tool update-shell` (POSIX) or the user PATH value (Windows, HKCU, no admin)
3. a Defender exclusion for the project and the worktrees folder (Windows): one printed line
4. the `.agent/` migration is in `migrate.py` (run by `ap upgrade`)
5. duplicate installs of one vendor CLI: both paths named, the one PATH picks, the removal command for the other"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import profile
from .proc import run_proc

PATH_MARK = "path_persisted"


def project_git(root: Path, run=run_proc, platform: str | None = None) -> list[str]:
    """Repair 1: the Q21 lines for this project (dubious ownership, autocrlf), applied; the lines say what was done."""
    from .commands.precheck import apply, check, gather
    snap = gather(None, None, None, run, cwd=str(root))
    snap.platform = platform or snap.platform
    lines = [(i, s, t) for i, s, t in check(snap) if i in ("git-dubious", "autocrlf")]
    return [f"{status}: {text}" for _, status, text in apply(lines, snap, run=run)]


def persist_path(home: Path | None = None, platform: str | None = None, run=run_proc, which=shutil.which,
                 add_windows=None) -> str:
    """Repair 2: put `~/.local/bin` on the PATH of new terminals, once. A marker in the machine profile stops a second
    run (so `open a new terminal` is printed once, not on every run)."""
    if profile.read(home).get(PATH_MARK):
        return ""
    p = platform or sys.platform
    d = Path(home or Path.home()) / ".local" / "bin"
    if p.startswith("win"):
        from .doctor import _add_user_path_windows
        try:
            (add_windows or _add_user_path_windows)(d)  # HKCU\Environment through winreg: no admin, never the machine PATH
        except (OSError, ImportError):
            return f"skipped: could not edit your user PATH; add {d} by hand"
        how = f"{d} added to your user PATH"
    else:
        uv = which("uv")
        if not uv:
            return "skipped: uv is not installed, so its PATH helper cannot run"
        if run([uv, "tool", "update-shell"], timeout=60).rc != 0:
            return "skipped: `uv tool update-shell` did not finish; run it by hand"
        how = "`uv tool update-shell` put the uv tool folder on PATH"
    profile.update({PATH_MARK: True}, home)
    return f"fixed: {how}. Open a new terminal once; this line is printed only this time."


def defender(root: Path, platform: str | None = None) -> str:
    """Repair 3: one printed line. The exclusion needs an administrator, and the N8 task installs winget ids only."""
    if not (platform or sys.platform).startswith("win"):
        return ""
    wt = Path(os.environ.get("TEMP") or "") / "autopilot-worktrees"
    return ("skipped: Defender scans every file of the project and its worktrees, which slows builds. In an administrator "
            f"PowerShell, add an exclusion (Add-MpPreference -ExclusionPath) for {root} and {wt}.")

def duplicates(which_all=None) -> list[str]:
    """Repair 5: two installs of one vendor CLI (npm and native, two paths). Names both, says which one PATH picks, and
    prints the removal command of the other. Nothing is removed by itself."""
    from .doctor import RUNNERS
    out = []
    for row in RUNNERS:
        found: list[str] = []
        for name in row.names:
            found += (which_all or _which_all)(name)
        found = list(dict.fromkeys(found))
        if len(found) < 2:
            continue
        first, other = found[0], found[1]
        undo = row.uninstall.get(_method_of(other), "")
        out.append(f"{row.binary} is installed twice: {first} and {other}. PATH picks {first}. "
                   + (f"Remove the other with: {undo}" if undo else f"Remove {other} by hand."))
    return out


def _which_all(name: str) -> list[str]:
    exts = os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if sys.platform.startswith("win") else [""]
    hits = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for e in exts:
            f = Path(d) / (name + e)
            if d and f.is_file() and (sys.platform.startswith("win") or os.access(f, os.X_OK)):
                hits.append(str(f))
    return hits


def _method_of(path: str) -> str:
    low = path.replace("\\", "/").lower()
    if "node_modules" in low or "/npm" in low or low.endswith((".cmd", ".bat")):
        return "npm"
    return "winget" if "/winget/" in low else "native-windows" if sys.platform.startswith("win") else "native-posix"


def fix_all(root: Path | None = None, *, home: Path | None = None, platform: str | None = None, run=run_proc) -> list[str]:
    """What `ap doctor --fix` and `ap setup` print for the repairs: only lines that did or said something."""
    out: list[str] = []
    if root is not None and (Path(root) / ".git").exists():
        out += project_git(Path(root), run, platform)
    if line := persist_path(home, platform, run):
        out.append(line)
    if root is not None and (line := defender(Path(root), platform)):
        out.append(line)
    out += duplicates()
    return out