"""W37: find process-wide kills (by name) in a Claude Code stream-json session log. Read by gate.task_gate."""
from __future__ import annotations

import json
import re

KILL_WORDS = {"taskkill", "pkill", "killall", "stop-process"}
SHELL_TOOLS = {"Bash", "PowerShell"}
_PARTS = re.compile(r"&&|\|\||[;|\n]")


def _kills(command: str) -> bool:
    """True when a part of the command starts with a kill-by-name program (a path to taskkill.exe counts)."""
    for part in _PARTS.split(command):
        words = part.strip().split()
        if words and re.split(r"[\/]", words[0])[-1].lower().removesuffix(".exe") in KILL_WORDS:
            return True
    return False


def kill_commands(log_text: str) -> list[str]:
    """The Bash/PowerShell tool-call commands of a stream-json log that kill by name, at most 5. Text never counts."""
    found: list[str] = []
    for line in log_text.splitlines():
        if '"tool_use"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        content = (event.get("message") or {}).get("content") if isinstance(event, dict) else None
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict) or item.get("type") != "tool_use" or item.get("name") not in SHELL_TOOLS:
                continue
            command = str((item.get("input") or {}).get("command", ""))
            if _kills(command) and command not in found:
                found.append(command)
                if len(found) == 5:
                    return found
    return found
