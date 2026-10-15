"""W70: PreToolUse hook. While an Autopilot run holds this checkout, a Claude Code session must not edit it.
Edit, Write, MultiEdit and NotebookEdit outside `.agent/` are refused; a Bash command that moves git or deletes
files is refused; reads, tests and lints pass. Stdlib only; the plugin must not import autopilot."""
import json
import os
import re
import sys
from pathlib import Path

GIT_WRITE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:commit|checkout|switch|reset|stash|rebase|merge|cherry-pick|clean|"
                       r"branch\s+-[dD]|push|worktree)\b|(?:^|[;&|]\s*)rm\s+-|Remove-Item\b", re.I)
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def active_run(root: Path) -> str:
    """'' when no run holds `root`, else the start time of the run that does."""
    lock = root / ".agent" / "run.lock"
    if not lock.exists():
        return ""
    try:
        fh = open(lock, "a+")
    except OSError:
        return ""
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return started(root)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return started(root)
            fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()
    return ""


def started(root: Path) -> str:
    try:
        run = json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8"))
        return str(run.get("started_at") or "")[11:16] or "a moment ago"
    except (OSError, ValueError):
        return "a moment ago"


def project_root(cwd: Path) -> Path | None:
    for p in (cwd, *cwd.parents):
        if (p / ".agent" / "run.lock").exists():
            return p
    return None


def decide(payload: dict) -> str:
    """The refusal text, or '' to allow."""
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    cwd = Path(str(payload.get("cwd") or os.getcwd())).resolve()
    root = project_root(cwd)
    if root is None:
        return ""
    since = active_run(root)
    if not since:
        return ""
    line = f"Autopilot runs in {root} since {since}: type `ap stop` first. A second session must not edit this checkout."
    if tool in EDIT_TOOLS:
        target = str(inp.get("file_path") or inp.get("notebook_path") or "")
        try:
            rel = Path(target).resolve().relative_to(root).as_posix() if target else ""
        except ValueError:
            rel = ""
        return "" if rel.startswith(".agent/") else line
    if tool == "Bash" and GIT_WRITE.search(str(inp.get("command") or "")):
        return line
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    why = decide(payload)
    if why:
        print(why, file=sys.stderr)
        return 2  # Claude Code: exit 2 blocks the call and shows stderr to the model
    return 0


if __name__ == "__main__":
    sys.exit(main())
