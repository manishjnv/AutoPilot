"""Agent backends. Each runs ONE fresh session and returns a SessionResult."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

LIMIT_RX = re.compile(r"hit your (?:[\w-]+ ){0,3}limit(?:\s*[·•|\-–—,.]*\s*resets?\s+(?P<reset>[^\n]+))?", re.I)
API_LIMIT_RX = re.compile(r"API Error: (?:429|529)|rate_limit_error|overloaded_error", re.I)
_RESET_RX = re.compile(r"^(?:(?P<mon>[a-z]{3,9})\.?\s+(?P<day>\d{1,2})\s*(?:,|at)?\s*)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?"
                       r"\s*(?P<ap>am|pm)?\s*(?:\((?P<tz>[^)]+)\))?$", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def parse_reset(s: str, now: datetime) -> float | None:
    """Next future occurrence of a CLI reset time like `3:45pm`, `Oct 3, 9am (Asia/Calcutta)`; None if unparseable."""
    try:
        m = _RESET_RX.match((s or "").strip().rstrip(".").strip())
        if not m or not (m["ap"] or m["m"]):
            return None
        tz = now.tzinfo
        if m["tz"]:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(m["tz"].strip())
            except Exception:  # noqa: BLE001  no tzdata / unknown zone: fall back to local time
                pass
        if now.tzinfo:
            now = now.astimezone(tz)
        h, mi = int(m["h"]), int(m["m"] or 0)
        if m["ap"]:
            if not 1 <= h <= 12:
                return None
            h = h % 12 + (12 if m["ap"].lower() == "pm" else 0)
        if m["mon"]:
            mon = _MONTHS.get(m["mon"][:3].lower())
            if not mon:
                return None
            t = now.replace(month=mon, day=int(m["day"]), hour=h, minute=mi, second=0, microsecond=0)
            if t <= now:
                t = t.replace(year=t.year + 1)
        else:
            t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if t <= now:
                t += timedelta(days=1)
        return t.timestamp()
    except Exception:  # noqa: BLE001
        return None


def detect_limit(text: str, now: datetime | None = None) -> tuple[bool, float | None]:
    """(limited, reset_at epoch). Only the CLI's subscription message or API 429/529 errors count, never agent prose."""
    text = text or ""
    m = LIMIT_RX.search(text)
    if m:
        return True, (parse_reset(m["reset"], now or datetime.now().astimezone()) if m["reset"] else None)
    return bool(API_LIMIT_RX.search(text)), None


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
    reset_at: float | None = None
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
