"""Agent backends. Each runs ONE fresh session and returns a SessionResult."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Anchored to a line start: the CLI prints these as its own message, so prose inside a failed session doesn't count.
LIMIT_RX = re.compile(r"^\s*(?:you've|you have) hit your (?:[\w-]+ ){0,3}limit"
                      r"(?:\s*[·•|\-–—,.]*\s*resets?\s+(?P<reset>[^\n]+))?", re.I | re.M)
API_LIMIT_RX = re.compile(r"^\s*API Error: (?:429|529)\b|^\s*API Error:.*(?:rate_limit_error|overloaded_error)", re.I | re.M)
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


# Failures of the machinery, not of the work: retried by the orchestrator, never counted as a task attempt.
# Anchored to a line start like LIMIT_RX, so the agent's own prose about these words never counts.
_AUTH_RX = re.compile(r"^\s*(?:Invalid API key|Please run /login|OAuth token (?:has )?expired|API Error: 401\b)",
                      re.I | re.M)
# Node's own error shapes ("reason: getaddrinfo ENOTFOUND", "Error: connect ECONNREFUSED"), not a bare code in prose
_NET_RX = re.compile(r"^\s*API Error: (?:Connection error|Request timed out|50[0234]\b)|"
                     r"(?:reason:|Error:)\s+(?:getaddrinfo |connect |read |write )?"
                     r"(?:ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN)\b", re.I | re.M)


def detect_infra(text: str) -> str:
    """'auth' (not logged in / key rejected), 'network' (connection, timeout, server 5xx) or ''."""
    text = text or ""
    return "auth" if _AUTH_RX.search(text) else "network" if _NET_RX.search(text) else ""


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
    resume: str = ""                                        # continue this CLI session instead of starting fresh
    resume_totals: dict = field(default_factory=dict)       # that session's totals so far (see SessionResult.totals)
    schema: dict | None = None                              # JSON Schema of the final report (schemas.REPORTS)
    effort: str = ""                                        # overrides agent.effort for this session
    web_only: bool = False                                  # research: only web search/fetch and reading files
    mcp_config: str = ""                                    # MCP servers for this session only (e.g. Playwright)
    no_tools: bool = False                                  # triage of untrusted text: no file, shell, web or MCP tools
    label: str = ""                                         # live progress lines: "P01-T01 Project skeleton [haiku]"
    on_tokens: object = None                                # G8: called with the session's running token total


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
    stuck: bool = False                          # killed for repeating the same action (stream-json watch)
    usage: dict = field(default_factory=dict)   # model -> {input, output, cache_read, cache_write, cost}
    num_turns: int = 0
    duration_ms: int = 0
    totals: dict = field(default_factory=dict)  # whole-session {cost, usage, num_turns, duration_ms}, for a later resume
    infra: str = ""                              # 'cli' | 'auth' | 'network': the machinery failed, not the work
    window: dict = field(default_factory=dict)  # G1: the CLI's own usage figure {five_hour: {pct, reset}, seven_day, status}


def since(totals: dict, base: dict) -> dict:
    """A resumed CLI session reports whole-session totals; keep only what this run added (never below zero)."""
    def sub(a, b):
        return max(0, (a or 0) - (b or 0))
    bu = base.get("usage") or {}
    usage = {m: {k: sub(v, (bu.get(m) or {}).get(k)) for k, v in u.items()} for m, u in (totals.get("usage") or {}).items()}
    return {"cost": sub(totals.get("cost"), base.get("cost")), "usage": usage,
            "num_turns": sub(totals.get("num_turns"), base.get("num_turns")),
            "duration_ms": sub(totals.get("duration_ms"), base.get("duration_ms"))}


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
