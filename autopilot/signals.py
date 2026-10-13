"""W29: session failures whose text no catalogue line knows go to `<AUTOPILOT_HOME or ~/.autopilot>/unknown.jsonl`.

One JSON line per unknown wording per day: {date, cause, text, count, runner, version, project, action}. The text is
scrubbed (secret variables and token shapes) and cut to 2000 characters; `project` is the folder NAME, never a path.
A known wording (a limit, an infra failure or an `install_errors` line) writes nothing."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path

from . import __version__
from .backends import detect_infra, detect_limit
from .gate import SECRET_PATTERNS
from .install_errors import explain, secrets
from .log_scrub import scrub_secrets

TEXT_MAX, KEY_MAX = 2000, 200        # stored text, and the part of it that makes two hits the same wording
CAUSES = ("scope", "tests", "environment", "limit", "infra", "unknown")
KNOWN = ("environment", "limit", "infra")  # a detector or the catalogue names it: no line
ACTIONS = ("retried", "parked", "healed")
_TESTS = re.compile(r"^\$ .+\n\(exit \d+\)|^FAILED |\btests? failed\b", re.M | re.I)


def path(home: Path | str | None = None) -> Path:
    """`home` is the Autopilot folder itself (a test passes one); else AUTOPILOT_HOME, else ~/.autopilot."""
    base = Path(home) if home else Path(os.environ.get("AUTOPILOT_HOME") or Path.home() / ".autopilot")
    return base / "unknown.jsonl"


def cause_of(text: str) -> str:
    """The harness cause of a failure text, detectors first, then the gate problem shapes; else 'unknown'."""
    text = text or ""
    if detect_limit(text)[0]:
        return "limit"
    if detect_infra(text):
        return "infra"
    if explain(text)[0]:
        return "environment"
    if "outside files_in_scope" in text or "scope_additions" in text:
        return "scope"
    return "tests" if _TESTS.search(text) else "unknown"


def scrub(text: str) -> str:
    """Secret variable values and token-shaped strings are replaced, then the text is cut to TEXT_MAX."""
    text = scrub_secrets(text or "", secrets())
    for rx, label in SECRET_PATTERNS:
        text = rx.sub(f"***REDACTED[{label}]***", text)
    return text[:TEXT_MAX]


def folder_name(project) -> str:
    """The last segment of a POSIX or Windows path (a Windows path on a POSIX host too), never the path itself."""
    return re.split(r"[\\/]", str(project or "").rstrip("\\/"))[-1]


def record_unknown(text: str, runner: str, project, action: str, home: Path | str | None = None) -> bool:
    """Append one line for an unknown failure wording, or add one to `count` of today's line with the same first
    KEY_MAX characters. True when a line was written or counted; False for a known wording. Never raises."""
    cause = cause_of(text)
    if cause in KNOWN:
        return False
    try:
        clean, today, p = scrub(text), date.today().isoformat(), path(home)
        key = clean[:KEY_MAX]
        lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        for i, raw in enumerate(lines):
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get("date") == today and str(row.get("text", ""))[:KEY_MAX] == key:
                row["count"] = int(row.get("count", 1)) + 1
                lines[i] = json.dumps(row)
                p.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return True
        row = {"date": today, "cause": cause, "text": clean, "count": 1, "runner": str(runner or ""),
               "version": __version__, "project": folder_name(project), "action": action}
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return True
    except OSError:
        return False


# ---------- W29b: the signals table read by `ap audit --signals` (read-only, offline)
GATE_KINDS = tuple((k, re.compile(rx)) for k, rx in (  # the gate.py problem wordings, first match wins
    ("no_change", r"no file changes"), ("protected", r"protected files"), ("secret", r"possible .{1,40} added: "),
    ("kill", r"process-wide kill"), ("scope", r"outside files_in_scope"), ("reasons", r"new file without a reason"),
    ("growth", r"file grew past the budget"), ("review", r"REVIEW")))
_QUALITY = re.compile(r"^(\S+) · .* · attempts (\d+) · ")


def gate_kind(text: str) -> str:
    """The gate check a parked task's error names: the first GATE_KINDS marker found, then 'tests', else 'other'."""
    text = text or ""
    kind = next((k for k, rx in GATE_KINDS if rx.search(text)), "")
    return kind or ("tests" if cause_of(text) == "tests" else "other")


def read_unknown(home: Path | str | None = None, since: str = "") -> list[dict] | None:
    """The rows of unknown.jsonl dated `since` (YYYY-MM-DD) or later; None when the file is missing."""
    try:
        lines = path(home).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    out = []
    for raw in lines:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and str(row.get("date", "")) >= since:
            out.append(row)
    return out


def read_events(db: Path, since: str = "") -> list[tuple[str, str]] | None:
    """(kind, message) of the `quality` and `task_blocked` events at `since` or later, opened read-only; None when
    the database cannot be read."""
    import sqlite3
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return [(str(k), str(m or "")) for k, m in con.execute(
                "SELECT kind, message FROM events WHERE kind IN ('quality', 'task_blocked') AND ts >= ? ORDER BY id",
                (since,))]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def tally_project(events: list[tuple[str, str]]) -> dict[str, Counter]:
    """Parked by cause, gate failures by kind and retries by cause of ONE project (task ids repeat across projects).
    The extra attempts of a parked task count under its cause only; those of a finished task count as 'recovered'."""
    out = {"parked": Counter(), "gates": Counter(), "retries": Counter()}
    parked_cause: dict[str, str] = {}
    for kind, msg in events:
        if kind == "task_blocked":
            cause = cause_of(msg)
            out["parked"][cause] += 1
            out["gates"][gate_kind(msg)] += 1
            parked_cause[(msg.split() or [""])[0]] = cause
    for kind, msg in events:
        m = _QUALITY.match(msg) if kind == "quality" else None
        if m and int(m.group(2)) > 1:
            out["retries"][parked_cause.get(m.group(1), "recovered")] += int(m.group(2)) - 1
    return out


def tally(unknown: list[dict], projects: list[list[tuple[str, str]]]) -> dict:
    """The table: unknown wordings as (count, cause, first 80 characters), most frequent first, plus the sums of
    tally_project over the projects (each project tallied on its own)."""
    words: Counter = Counter()
    for row in unknown:
        words[(str(row.get("cause", "unknown")), " ".join(str(row.get("text", "")).split())[:80])] += int(row.get("count", 1) or 1)
    out: dict = {"unknown": sorted(((n, c, t) for (c, t), n in words.items()), key=lambda x: (-x[0], x[2]))}
    per = [tally_project(ev) for ev in projects]
    for key in ("parked", "gates", "retries"):
        out[key] = sum((p[key] for p in per), Counter())
    return out
