"""W18a: the liveness facts of the watch screen: what the run waits for, the runner heartbeat, the age of an error, the
version and the run number. dashboard.py calls the data helpers; dash_term.py and dash_web.py call tick() and span()."""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache
from pathlib import Path


def epoch(iso) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def version_text() -> str:
    """`Autopilot 0.7.1 (a1b2c3d)`, plus `from <folder>` for a checkout: the text of `ap --version` (cli._version_line)."""
    from .cli import _version_line
    line = _version_line()
    return f"Autopilot {line}" + ("" if "(installed)" in line else f" from {Path(__file__).resolve().parent.parent.name}")


def span(sec) -> str:
    """'3m 10s', '1h 02m': a running time with a space, for the Waiting line."""
    sec = max(0, int(sec))
    return f"{sec // 3600}h {sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m {sec % 60:02d}s"


def gate_label(current) -> str:
    """'Gate: tests' / 'Gate: merge' / 'Start check: tests on main' from a journal `current` line, else ''."""
    m = re.match(r"(gate|start check): ([^(]+?)\s*(?:\(|$)", str(current or ""))
    return f"{m.group(1).capitalize()}: {m.group(2)}" if m else ""


def pulse(run: dict, mtime):
    """The time of the newest sign that the run works: the data files, the runner heartbeat, and during a gate the
    process beat (a gate streams no events). The spinner turns while this moves; W37 `run_alive` still decides dead."""
    stamps = [mtime, epoch(run.get("heartbeat_at"))]
    if gate_label(run.get("current")):
        stamps.append(epoch(run.get("beat_at")))
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def last_tool(root) -> dict | None:
    """The tool the session runs now, from the last `▸` line of the log: {text: 'Bash (pytest -q)', since: epoch}."""
    from . import AGENT_DIR
    log = root / AGENT_DIR / "logs" / "autopilot.log"
    try:
        with open(log, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 4096))
            last = fh.read().decode("utf-8", "replace").splitlines()[-1:]
        since = log.stat().st_mtime
    except OSError:
        return None
    if not last or "▸" not in last[0]:
        return None
    parts = last[0].split(" · ")
    act = (parts[-2] if len(parts) >= 3 else "").split("; ")[-1].strip()
    if not act or act.startswith('"'):  # Claude's own words are not a tool
        return None
    name, _, what = act.partition(" ")
    what = " ".join(what.split())
    return {"text": name + (f" ({what[:30]})" if what else ""), "since": since}


def waiting(root, run: dict, live: bool, now: float) -> dict | None:
    """What the run waits for: {kind: gate|tool, text, since (epoch), secs}. A gate line comes from the journal."""
    if not live:
        return None
    label, since = gate_label(run.get("current")), epoch(run.get("current_at"))
    if label and since:
        return {"kind": "gate", "text": label, "since": since, "secs": max(0, int(now - since))}
    tool = last_tool(root)
    if tool and run.get("state") not in ("Wait", "Block"):
        return {"kind": "tool", **tool, "secs": max(0, int(now - tool["since"]))}
    return None


def run_line(state, now: float) -> str:
    """`Run 2 (since 06:59) · total 4h38m since 03:30` from the run_start events; '' with no event."""
    rows = [r[0] for r in state.db.execute("SELECT ts FROM events WHERE kind='run_start' ORDER BY id")]
    if not rows:
        return ""
    first = epoch(rows[0])
    total = f" · total {span(now - first).replace(' ', '')} since {rows[0][11:16]}" if first and len(rows) > 1 else ""
    return f"Run {len(rows)} (since {rows[-1][11:16]}){total}"


def error_age(state, row, now: float) -> tuple[str, bool]:
    """('3d ago', stale): the age of an error; stale when a session ended ok after it (the error is old news)."""
    at = row["updated_at"] if row is not None else None
    t = epoch(at)
    if t is None:
        return "", False
    sec = max(0, now - t)
    age = f"{int(sec // 86400)}d" if sec >= 86400 else f"{int(sec // 3600)}h" if sec >= 3600 else f"{max(1, int(sec // 60))}m"
    ok = state.db.execute("SELECT 1 FROM sessions WHERE ok=1 AND ended_at > ? LIMIT 1", (at,)).fetchone()
    return f"{age} ago", bool(ok)


def tick(wait: dict | None, clock: float | None) -> str:
    """'Waiting for: Bash (pytest), 3m 10s'; the time runs on the window clock when there is one."""
    if not wait or not wait.get("text"):
        return ""
    secs = clock - wait["since"] if clock and wait.get("since") else wait.get("secs", 0)
    return f"Waiting for: {wait['text']}, {span(secs)}"
