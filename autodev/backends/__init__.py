"""Agent backends. Each runs ONE fresh session and returns a SessionResult."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

RATE_LIMIT_RX = re.compile(
    r"rate.?limit|\b429\b|\b529\b|overloaded|usage limit|quota|too many requests|limit reached", re.I)


@dataclass
class SessionRequest:
    prompt: str
    model: str
    cwd: str
    timeout_sec: int = 3600
    budget_usd: float | None = None
    system_append: str = ""
    read_only: bool = False
    log_path: str = ""


@dataclass
class SessionResult:
    ok: bool
    text: str = ""
    cost: float = 0.0
    session_id: str = ""
    report: dict = field(default_factory=dict)
    error: str = ""
    rate_limited: bool = False
    timed_out: bool = False


def parse_report(text: str) -> dict:
    """Extract the last ```json block (or bare JSON object) from the agent's final message."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    candidates = list(reversed(blocks))
    if not candidates:
        m = re.search(r"(\{[^{}]*\"status\".*\})\s*$", text or "", re.S)
        if m:
            candidates = [m.group(1)]
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return {}


def get_backend(cfg):
    kind = cfg.get("agent.backend", "claude_cli")
    if kind == "claude_cli":
        from .claude_cli import ClaudeCLIBackend
        return ClaudeCLIBackend(cfg)
    if kind == "command":
        from .command import CommandBackend
        return CommandBackend(cfg)
    raise ValueError(f"unknown backend {kind}")
