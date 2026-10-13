"""W37: find process-wide kills (by name) in a Claude Code stream-json session log. Read by gate.task_gate."""
from __future__ import annotations

import json
import re

KILL_WORDS = {"taskkill", "pkill", "killall", "stop-process"}
SHELL_TOOLS = {"Bash", "PowerShell"}
_PARTS = re.compile(r"&&|\|\||[;|\n]")


WRAPPERS = {"sudo", "env", "nohup", "exec", "command", "cmd", "/c", "/k", "powershell", "pwsh", "-c", "-command",
            "-noprofile", "start", "&"}


def _program(word: str) -> str:
    return re.split(r"[\\/]", word.strip("\"'"))[-1].lower().removesuffix(".exe")


def _kills(command: str) -> bool:
    """True when a part of the command runs a kill-by-name program, also behind sudo / cmd /c / powershell -c
    (a path to taskkill.exe counts). `taskkill /PID n` and `Stop-Process -Id n` stop by pid and pass."""
    for part in _PARTS.split(command):
        words = part.strip().split()
        while words and (words[0].lower() in WRAPPERS or _program(words[0]) in WRAPPERS or "=" in words[0]):
            words = words[1:]
        if not words or _program(words[0]) not in KILL_WORDS:
            continue
        flags = {w.strip("\"'").lower() for w in words[1:]}
        name = _program(words[0])
        if name == "taskkill" and "/im" not in flags and "/pid" in flags:
            continue
        if name == "stop-process" and "-name" not in flags and ("-id" in flags or words[1:2] and words[1].isdigit()):
            continue
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
