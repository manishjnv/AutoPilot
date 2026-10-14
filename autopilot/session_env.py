"""W38: what a session runs with: its CLAUDE_CONFIG_DIR, passthrough count, runner and config folder.

Printed by `ap validate` and named in the run start log line, so a wrong account shows before hours are spent."""
from __future__ import annotations

import shutil
from pathlib import Path

from .proc import agent_env


def config_folder(cfg) -> str:
    """The Claude config folder sessions use: CLAUDE_CONFIG_DIR of the session env, else ~/.claude."""
    return agent_env(cfg).get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")


def runner_where(cfg) -> tuple[str, str]:
    """(name, path) of the agent CLI a session starts; the path is 'not found' when nothing is on PATH."""
    if cfg.get("agent.backend", "claude_cli") == "claude_cli":
        from .backends.claude_cli import ClaudeCLIBackend
        found = ClaudeCLIBackend.resolve_binary()
        return "claude", (found if Path(found).is_file() else shutil.which(found) or "not found")
    if cfg.get("agent.backend") == "command":
        from .backends.command import PRESETS
        preset = cfg.get("agent.preset")
        cmd = cfg.get("agent.command") or PRESETS.get(str(preset), "")
        name = (str(cmd).split() or [str(preset or "command")])[0]
        return str(preset or name), shutil.which(name) or "not found"
    return str(cfg.get("agent.backend")), str(cfg.get("agent.base_url") or "default endpoint")


def session_lines(cfg) -> list[str]:
    """The two lines `ap validate` prints: the session env and the runner with its config folder."""
    env = agent_env(cfg)
    passthrough = len(cfg.get("agent.env_passthrough", []) or [])
    name, path = runner_where(cfg)
    return [f"session env: CLAUDE_CONFIG_DIR={env.get('CLAUDE_CONFIG_DIR') or 'unset'}, {passthrough} passthrough",
            f"runner: {name} at {path}, config folder {config_folder(cfg)}"]
