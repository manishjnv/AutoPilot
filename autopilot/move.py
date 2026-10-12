"""Q15: a project in a folder that hurts (OneDrive, a redirected Documents folder, a network share, `/mnt/<drive>` from
WSL) gets one sentence that says why, and one command that moves it: `ap move <target>`. The move is a `git clone --local`
plus a copy of `.agent/`; the remotes of the old folder are kept; the new path goes to the recent-projects list; the old
folder stays untouched except for one `MOVED.md` note that names the new path. Nothing is deleted."""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from . import AGENT_DIR
from .proc import run_proc

WHY = {
    "onedrive": "This project is in a OneDrive folder: sync locks files, git runs slowly and worktrees can break.",
    "unc": "This project is on a network share: git runs slowly and worktrees can break.",
    "mapped": "This project is on a mapped network drive: git runs slowly and worktrees can break.",
    "mnt": "This project is on a Windows drive seen from WSL: git runs slowly and worktrees can break.",
}


def location_kind(path: str | Path, env: dict | None = None, platform: str | None = None, drive_type=None) -> str:
    """'' for a good place; else `onedrive`, `unc`, `mapped` or `mnt`. `drive_type(letter)` is replaced by a test."""
    env = os.environ if env is None else env
    plat = platform or sys.platform
    p = str(path).replace("\\", "/")
    low = p.lower()
    if low.startswith("//"):
        return "unc"
    roots = [env.get(k, "") for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    if any("onedrive" in part.lower() for part in p.split("/")) or any(
            r and low.startswith(r.replace("\\", "/").lower().rstrip("/") + "/") for r in roots):
        return "onedrive"  # also a Documents folder that Known Folder Move put under OneDrive
    if re.match(r"^/mnt/[a-z]/", low) and plat.startswith("linux"):
        return "mnt"
    m = re.match(r"^([a-z]):/", low)
    if m and plat.startswith("win") and (drive_type or _drive_type)(m.group(1).upper()) == 4:  # DRIVE_REMOTE
        return "mapped"
    return ""


def _drive_type(letter: str) -> int:
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\"))
    except (AttributeError, OSError):
        return 0


def default_target(name: str, env: dict | None = None, platform: str | None = None, home: Path | None = None) -> str:
    """`%LOCALAPPDATA%\\dev\\<name>` on Windows, `~/dev/<name>` on WSL and everywhere else."""
    env = os.environ if env is None else env
    from pathlib import PurePosixPath, PureWindowsPath  # the target OS decides the separators, not the test host
    if (platform or sys.platform).startswith("win"):
        base = env.get("LOCALAPPDATA") or str(PureWindowsPath(str(home or Path.home())) / "AppData" / "Local")
        return str(PureWindowsPath(base) / "dev" / name)
    return str(PurePosixPath(str(home or Path.home()).replace("\\", "/")) / "dev" / name)


def warning(root: Path, **kw) -> list[str]:
    """The lines for a project in a bad place: why (one sentence), then the command. [] when the place is fine."""
    kind = location_kind(root, **{k: v for k, v in kw.items() if k in ("env", "platform", "drive_type")})
    if not kind:
        return []
    target = default_target(root.name, kw.get("env"), kw.get("platform"), kw.get("home"))
    return [WHY[kind], f'Move it with: ap move "{target}"']

def _git(cwd, *args, run=run_proc):
    p = run(["git", *args], cwd=str(cwd), timeout=300)
    return p.rc, ((p.stdout or "") + (p.stderr or "")).strip()


def move_project(root: Path, target: Path, *, say=print, run=run_proc) -> int:
    """Clone, copy `.agent/`, keep the remotes, remember the new path, leave a note. Exit code 0 or 1."""
    root, target = Path(root).resolve(), Path(target).expanduser().resolve()
    if not (root / ".git").exists():
        say("FAILED  move: this folder is not a git repository, so it cannot be cloned.")
        say("        Run by hand: git init")
        return 1
    if target == root or root in target.parents:
        say("FAILED  move: the new folder must be outside the old one.")
        return 1
    if target.exists() and any(target.iterdir()):
        say(f"FAILED  move: {target} already holds files. Choose an empty folder.")
        return 1
    from .cli import remember, run_active
    if run_active(root):
        say("FAILED  move: a build is running in this project. Stop it first, then move.")
        say("        Run by hand: ap stop")
        return 1
    rc, dirty = _git(root, "status", "--porcelain", run=run)
    if rc == 0 and dirty:
        say("note     uncommitted changes stay in the old folder: the clone holds committed work only.")
    target.parent.mkdir(parents=True, exist_ok=True)
    rc, _ = _git(target.parent, "clone", "--local", "-q", str(root), str(target), run=run)
    if rc != 0:
        say("FAILED  move: git could not clone the project.")
        say(f'        Run by hand: git clone --local "{root}" "{target}"')
        return 1
    _, names = _git(root, "remote", run=run)  # the remotes of the old folder, not the old folder itself
    old = set(names.split())
    for name in old:
        _, url = _git(root, "remote", "get-url", name, run=run)
        if _git(target, "remote", "set-url", name, url, run=run)[0] != 0:
            _git(target, "remote", "add", name, url, run=run)
    if "origin" not in old:
        _git(target, "remote", "remove", "origin", run=run)
    src = root / AGENT_DIR
    if src.is_dir():
        shutil.copytree(src, target / AGENT_DIR, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.lock", "STOP", "worktrees"))
    remember(target)
    try:
        (root / "MOVED.md").write_text(
            f"# This project moved\n\nThe project now lives in:\n\n    {target}\n\nThis folder is left as it was. "
            f"Work in the new folder. You can delete this one when you no longer need it.\n", encoding="utf-8")
    except OSError:
        say("note     the old folder is read-only: MOVED.md was not written.")
    say(f"moved     {root} -> {target}")
    say(f'next      cd "{target}" and run: ap status')
    return 0


def cmd_move(args) -> int:
    root = Path(getattr(args, "path", None) or ".").resolve()
    target = getattr(args, "target", None) or default_target(root.name)
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    if not (getattr(args, "yes", False) or tty):
        print(f'No terminal to ask on. Run: ap move "{target}" --yes')
        return 0
    if not getattr(args, "yes", False):
        from .commands.setup import ask_tty
        if (ask_tty(f"Move {root} to {target}? (y/N): ") or "").lower() not in ("y", "yes"):
            print("Nothing moved.")
            return 0
    return move_project(root, Path(target))