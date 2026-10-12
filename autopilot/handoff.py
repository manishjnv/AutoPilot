"""N11: hand a task to the next runner when the first one hits a usage limit that resets in more than 30 minutes."""
from __future__ import annotations

from pathlib import Path

from .backends import get_backend
from .config import Config

MIN_WAIT = 1800  # seconds to the reset; below this the normal pause is shorter than a handoff


def fallback_backend(cfg, name: str):
    """The backend of runner `name` (a command preset), built by the normal factory."""
    agent = {**(cfg.data.get("agent") or {}), "backend": "command", "preset": name, "command": ""}
    return get_backend(Config(cfg.root, {**cfg.data, "agent": agent}))


def write_handoff(root, task, git, main: str, gate: str = "") -> str:
    """HANDOFF.md in the worktree: goal, done, next, failing tests. Returns its text."""
    done = git.run("log", "--format=%s", f"{main}..HEAD", check=False)
    text = "\n".join([
        "# Handoff", "", "## Goal", f"{task.id} {task.title}", task.description or "", "",
        "## Done", *(f"- {line}" for line in done.splitlines()), "",
        "## Next", *(f"- {c}" for c in task.acceptance_criteria), "",
        "## Failing tests", (gate or "none").strip()[-3000:], ""])
    (Path(root) / "HANDOFF.md").write_text(text, encoding="utf-8")
    return text
