"""N11: hand a task to the next runner when the first one hits a usage limit that resets in more than 30 minutes."""
from __future__ import annotations

from pathlib import Path

from .backends import get_backend
from .config import Config

MIN_WAIT = 1800  # seconds to the reset; below this the normal pause is shorter than a handoff


def entry_folder(entry) -> str:
    """W28: the CLAUDE_CONFIG_DIR of an `agent.fallback` entry `{claude_cli: {CLAUDE_CONFIG_DIR: folder}}`, else ''."""
    if not isinstance(entry, dict):
        return ""
    env = next(iter(entry.values()), None)
    return str(env.get("CLAUDE_CONFIG_DIR") or "") if isinstance(env, dict) else ""


def account_of(cfg) -> str:
    """W28: the Claude config folder the main runner uses (`agent.env`), else `default`."""
    return str((cfg.get("agent.env") or {}).get("CLAUDE_CONFIG_DIR") or "default")


def fallback_backend(cfg, entry):
    """The backend of fallback `entry`: a runner name (a command preset), or W28 `{claude_cli: {CLAUDE_CONFIG_DIR: f}}`
    = the same runner with that env added (this backend only), both built by the normal factory."""
    agent = dict(cfg.data.get("agent") or {})
    if isinstance(entry, dict):
        agent["env"] = {**(agent.get("env") or {}), "CLAUDE_CONFIG_DIR": entry_folder(entry)}
    else:
        agent.update(backend="command", preset=entry, command="")
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
