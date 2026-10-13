"""W8: `ap audit --history` reads the local Claude Code history and prices repeated failing commands. Offline, writes nothing."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# Public API rates in USD per million tokens (input, output), checked 2026-10. Unknown model = Sonnet.
RATES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
REPEAT_MIN = 3
EXIT_RE = re.compile(r"exit code:?\s*([1-9]\d*)", re.I)
KEYS = ("sessions", "in", "out", "calls", "repeats", "cost", "retry")


def rate(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    return next((v for k, v in RATES.items() if k in m), RATES["sonnet"])


def _blocks(msg: dict) -> list[dict]:
    c = msg.get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _failed(b: dict) -> bool:
    if b.get("is_error") is True:
        return True
    c = b.get("content")
    if isinstance(c, list):
        c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return isinstance(c, str) and bool(EXIT_RE.search(c))


def _int(v) -> int:
    return v if isinstance(v, int) else 0


def read_session(path: Path) -> dict | None:
    """Tokens, cost, tool calls and repeats of one session file; None when it cannot be read."""
    tin = tout = calls = 0
    cost = 0.0
    cmds: dict[str, str] = {}  # tool_use id -> Bash command
    fails: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        msg = d.get("message") if isinstance(d, dict) else None
        if not isinstance(msg, dict):
            continue
        u = msg.get("usage")
        if isinstance(u, dict):
            i, o = _int(u.get("input_tokens")), _int(u.get("output_tokens"))
            ri, ro = rate(str(msg.get("model") or ""))
            tin, tout, cost = tin + i, tout + o, cost + (i * ri + o * ro) / 1e6
        for b in _blocks(msg):
            if b.get("type") == "tool_use":
                calls += 1
                inp = b.get("input")
                cmd = inp.get("command") if isinstance(inp, dict) else None
                if b.get("name") == "Bash" and isinstance(cmd, str) and isinstance(b.get("id"), str):
                    cmds[b["id"]] = cmd
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in cmds and _failed(b):
                c = cmds[b["tool_use_id"]]
                fails[c] = fails.get(c, 0) + 1
    rep = [n for n in fails.values() if n >= REPEAT_MIN]
    share = sum(rep) / calls if calls else 0.0
    return {"in": tin, "out": tout, "calls": calls, "repeats": len(rep), "cost": cost, "retry": cost * share}


def label(folder: str) -> str:
    """The project folder name with the encoded home prefix removed."""
    home = re.sub(r"[^A-Za-z0-9]", "-", str(Path.home()))
    name = folder[len(home):] if folder.startswith(home) else folder
    return name.lstrip("-") or folder


def cmd_history(args) -> int:
    root = Path(getattr(args, "home", None) or "~/.claude").expanduser() / "projects"
    cutoff = time.time() - max(int(getattr(args, "days", 30)), 0) * 86400
    rows: dict[str, dict] = {}
    for f in sorted(root.glob("*/*.jsonl")) if root.is_dir() else []:
        try:
            if f.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        s = read_session(f)
        if s is None:
            continue
        r = rows.setdefault(label(f.parent.name), dict.fromkeys(KEYS, 0))
        r["sessions"] += 1
        for k in KEYS[1:]:
            r[k] += s[k]
    if not rows:
        print("No Claude Code history found.")
        return 0

    def fmt(name: str, r: dict) -> str:
        return f"{name[:32]:<32} {r['sessions']:>8} {r['in']:>10} {r['out']:>9} {r['calls']:>10} {r['repeats']:>7} {r['retry']:>8.2f}"

    print(f"{'Project':<32} {'Sessions':>8} {'Input':>10} {'Output':>9} {'Tool calls':>10} {'Repeats':>7} {'Retry $':>8}")
    for name, r in sorted(rows.items()):
        print(fmt(name, r))
    t = {k: sum(r[k] for r in rows.values()) for k in KEYS}
    print(fmt("Total", t))
    print(f"Retries cost about ${t['retry']:.2f} of ${t['cost']:.2f}.")
    return 0


def cmd_signals(args) -> int:
    """W29b: unknown wordings from unknown.jsonl and the parked tasks and retries of every known project, as one
    plain table. Read-only, offline; a missing file or project is skipped with one line."""
    from datetime import date, timedelta

    from .. import signals
    from ..cli import recent_projects
    days = max(int(getattr(args, "days", 30)), 0)
    since = (date.today() - timedelta(days=days)).isoformat()
    unknown = signals.read_unknown(since=since)
    skipped = [] if unknown is not None else [f"skipped: no {signals.path().name} in {signals.path().parent}"]
    projects: list[list[tuple[str, str]]] = []  # one event list per project: task ids repeat across projects
    for root in recent_projects():
        got = signals.read_events(root / ".agent" / "state.db", since)
        if got is None:
            skipped.append(f"skipped: {root.name} (no readable .agent/state.db)")
        else:
            projects.append(got)
    t = signals.tally(unknown or [], projects)
    if not any(t.values()):  # one line, whatever was missing
        print(f"No signals in the last {days} days: no unknown errors, parked tasks or retries.")
        return 0
    print("\n".join(skipped + [f"Signals of the last {days} days"]))
    print(f"\nTop unknown wordings\n{'Count':>5}  {'Cause':<8} Text")
    for n, cause, text in t["unknown"][:10] or [(0, "-", "(none)")]:
        print(f"{n:>5}  {cause:<8} {text}")
    for title, key in (("Parked by cause", "parked"), ("Gate failures by kind", "gates"), ("Retries by cause", "retries")):
        print(f"\n{title}\n{'Count':>5}  Cause")
        for name, n in sorted(t[key].items(), key=lambda x: (-x[1], x[0])) or [("(none)", 0)]:
            print(f"{n:>5}  {name}")
    return 0


SAME_COST = 0.10  # W23: costs within 10 percent of each other count as the same cost per task
LADDER_MIN = 2  # finished tasks a tier needs before it is compared


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _minutes(row) -> float:
    ms, a, b = row
    if ms:
        return ms / 60000
    try:
        from datetime import datetime
        return max((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds(), 0) / 60
    except (TypeError, ValueError):
        return 0.0


def read_ladder(db: Path, risks: dict[str, str]) -> list[dict] | None:
    """W23: one row per finished task: its first model (the ladder start), risk, minutes (the sum of its session
    durations), attempts and cost, from state.db opened read-only; None when the database cannot be read."""
    import sqlite3
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
            ms = "duration_ms" if "duration_ms" in cols else "0"
            done = con.execute("SELECT id, attempts FROM tasks WHERE status = 'done'").fetchall()
            sess = con.execute(f"SELECT task_id, kind, model, {ms}, started_at, ended_at, cost FROM sessions "
                               "WHERE task_id IS NOT NULL ORDER BY id").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    rows = []
    for tid, attempts in done:
        mine = [s for s in sess if s[0] == tid]
        first = next((s[2] for s in mine if s[1] == "task"), None)
        if not first:
            continue
        rows.append({"model": str(first), "risk": risks.get(tid, "medium"), "attempts": int(attempts or 1),
                     "minutes": sum(_minutes(s[3:6]) for s in mine), "cost": sum(float(s[6] or 0) for s in mine)})
    return rows


def ladder_table(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(model, risk) -> tasks, median minutes, median attempts, retry share and cost per task (mean)."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["model"], r["risk"]), []).append(r)
    return {k: {"tasks": len(g), "minutes": _median([r["minutes"] for r in g]),
                "attempts": _median([r["attempts"] for r in g]),
                "retry": sum(r["attempts"] > 1 for r in g) / len(g), "cost": sum(r["cost"] for r in g) / len(g)}
            for k, g in groups.items()}


def propose(table: dict[tuple[str, str], dict], ladder: dict) -> list[str]:
    """W23, pure: for each risk tier whose ladder starts on a model that is slower than the next model up and not
    cheaper per task, one line that starts the tier on the model up. The model up is compared on the same risk,
    else on all its tasks."""
    from ..orchestrator import model_rank
    out = []
    for risk, steps in (ladder or {}).items():
        if not steps:
            continue
        start = str(steps[0])
        up = min({m for m, _ in table if model_rank(m) > model_rank(start)}, key=model_rank, default=None)
        a = table.get((start, risk))
        b = table.get((up, risk)) if up else None
        if up and b is None:
            g = [v for (m, _), v in table.items() if m == up]
            n = sum(v["tasks"] for v in g)
            b = n and {"tasks": n, "minutes": sum(v["minutes"] * v["tasks"] for v in g) / n,
                       "cost": sum(v["cost"] * v["tasks"] for v in g) / n}
        if not a or not b or min(a["tasks"], b["tasks"]) < LADDER_MIN:
            continue
        if a["minutes"] > b["minutes"] and a["cost"] >= b["cost"] * (1 - SAME_COST):
            same = abs(a["cost"] - b["cost"]) <= SAME_COST * max(a["cost"], b["cost"])
            cost = "same cost" if same else f"${a['cost']:.2f} vs ${b['cost']:.2f} per task"
            new = ", ".join([up] + [str(s) for s in steps[1:]])
            out.append(f"propose: models.ladder.{risk}: [{new}] ({start} {a['minutes']:.0f} min vs {up} "
                       f"{b['minutes']:.0f} min, {cost})")
    return out


def cmd_ladder(args) -> int:
    """W23: per model and risk of this project, how fast and how costly finished tasks were, and the ladder change
    the data supports. Read-only."""
    from ..config import Config
    root = Path(getattr(args, "path", None) or ".").resolve()
    cfg = Config.load(root)
    rows = read_ladder(root / ".agent" / "state.db", plan_risks(root / ".agent" / "plan.yaml"))
    if not rows:
        print("No finished tasks in .agent/state.db yet: nothing to measure.")
        return 0
    table = ladder_table(rows)
    print(f"{'Model':<10} {'Risk':<9} {'Tasks':>5} {'Min/task':>8} {'Attempts':>8} {'Retried':>7} {'$/task':>7}")
    order = ("low", "medium", "high", "critical")
    for (m, risk), v in sorted(table.items(), key=lambda kv: (order.index(kv[0][1]) if kv[0][1] in order else 9,
                                                              kv[0][0])):
        print(f"{m[:10]:<10} {risk:<9} {v['tasks']:>5} {v['minutes']:>8.0f} {v['attempts']:>8.1f} "
              f"{v['retry']:>7.0%} {v['cost']:>7.2f}")
    for line in propose(table, cfg.get("models.ladder", {})):
        print(line)
    return 0


def plan_risks(path: Path) -> dict[str, str]:
    """Task id -> risk from plan.yaml, without validation (a broken plan still has measurable tasks)."""
    import yaml

    from ..config import load_yaml
    try:
        data = load_yaml(path) if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        return {}
    return {str(t.get("id")): str(t.get("risk", "medium")).lower()
            for p in (data.get("phases") or []) if isinstance(p, dict)
            for t in (p.get("tasks") or []) if isinstance(t, dict)}
