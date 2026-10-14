"""W18a: the liveness facts of the watch screen: what the run waits for, the runner heartbeat, the age of an error, the
version and the run number. dashboard.py calls the data helpers; dash_term.py and dash_web.py call tick() and span()."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
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


# ---------------------------------------------------------------- W18b: the data of the Now card
STEPS = ("read", "write", "tests", "gate", "merge")
END_STEPS = ("read", "tests", "report")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# ponytail: a test command is recognised by name (pytest, npm test, ...); an unusual runner counts as a write step
TEST_CMD = re.compile(r"pytest|unittest|\b(?:npm|yarn|pnpm) (?:run )?test|go test|cargo test|jest|vitest|wsltest|tox\b"
                      r"|rspec|dotnet test|mvn test|gradle test")
# keyword of run.json `current` -> (title, what it does, kind of the session in the database)
END_PHASE = {"audit": ("Completion audit", "checks the whole plan for gaps", "audit"),
             "functional check": ("Functional check", "runs each user journey", "verify"),
             "docs": ("Final docs", "writes the docs of the app", "docs"),
             "replan": ("Replan", "rewrites the rest of the plan", "replan")}
THEN = {"audit": "then the run ends", "functional check": "then the phase closes", "docs": "then the phase closes",
        "replan": "then the build goes on"}
WORDS = {"VERIFIED": ("✓", "green"), "BLOCKED": ("⏸", "yellow"), "STOPPED": ("⏸", "yellow"),
         "BUDGET_STOP": ("⏸", "yellow"), "STALLED": ("⏸", "yellow"), "FAILED": ("✗", "red"), "DEAD": ("✗", "red")}
_SESSION = re.compile(r"session #(\d+) (\w+) (\S*) model=(\S+) attempt=(\d+)")
_cache: dict = {}


def median(xs):
    xs = sorted(xs)
    return None if not xs else xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2


def sessions(root) -> list[dict]:
    """The sessions in the tail of the log: {id, kind, task, model, attempt, start, tools: [(epoch, name, text)],
    done_at}. Cached by the size and time of the log file."""
    from . import AGENT_DIR
    log = root / AGENT_DIR / "logs" / "autopilot.log"
    try:
        st = log.stat()
        key = (str(log), st.st_size, st.st_mtime_ns)
        if _cache.get("log") == key:
            return _cache["sessions"]
        with open(log, "rb") as fh:
            fh.seek(max(0, st.st_size - 3_000_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out, cur = [], None
    for ln in lines:
        ts = epoch(ln[:19])
        if ts is None:
            continue
        m = _SESSION.search(ln)
        if m:
            cur = {"id": int(m.group(1)), "kind": m.group(2), "task": m.group(3), "model": m.group(4),
                   "attempt": int(m.group(5)), "start": ts, "tools": [], "done_at": None}
            out.append(cur)
        elif cur is None:
            continue
        elif " ▸ " in ln:
            parts = ln.split(" · ")
            act = (parts[-2] if len(parts) >= 3 else "").split("; ")[-1].strip()
            name, _, what = act.partition(" ")
            if name and not act.startswith('"'):
                cur["tools"].append((ts, name, " ".join(what.split())))
        elif cur["done_at"] is None and cur["task"] and re.search(rf"\btask {re.escape(cur['task'])} done\b", ln):
            cur["done_at"] = ts
    _cache.update(log=key, sessions=out)
    return out


def marks(s: dict) -> tuple:
    """(first edit, first test command after it, last tool) as epochs; None for a step not seen."""
    edit = test = last = None
    for ts, name, text in s["tools"]:
        last = ts
        if edit is None and name in EDIT_TOOLS:
            edit = ts
        elif edit is not None and test is None and name == "Bash" and TEST_CMD.search(text):
            test = ts
    return edit, test, last


def step_secs(past: list[dict]) -> list[float] | None:
    """The median time of the five steps over past task sessions (gate and merge share the time after the last tool,
    3 to 1), or None when the log holds too little. ponytail: the gate time is not in the log by itself."""
    rd, wr, ts, post = [], [], [], []
    for s in past:
        edit, test, last = marks(s)
        if edit is None or test is None or last is None or s["done_at"] is None:
            continue
        rd.append(edit - s["start"]), wr.append(test - edit), ts.append(max(last - test, 1.0))
        post.append(s["done_at"] - last)
    if not (rd and post):
        return None
    p = max(median(post), 4.0)
    return [max(median(rd), 1.0), max(median(wr), 1.0), max(median(ts), 1.0), p * 0.75, p * 0.25]


def weights(secs: list | None, n: int) -> list[float]:
    """The share of each step in the bar: from the median times, or equal. No step is thinner than 5 percent."""
    if not secs or len(secs) != n:
        return [1 / n] * n
    floor = 0.05 * sum(secs)
    w = [max(x, floor) for x in secs]
    return [x / sum(w) for x in w]


def quartiles(xs: list[float]):
    """(low, median, high) of the middle half of the values; None with fewer than 3 values."""
    xs = sorted(xs)
    if len(xs) < 3:
        return None
    return xs[len(xs) // 4], median(xs), xs[(3 * len(xs)) // 4]


def eta_text(peers: list[float], model: str, risk: str) -> dict:
    """The ETA range and its basis: the middle half of past tasks with the same model and risk."""
    q = quartiles(peers)
    if q:
        return {"lo": q[0], "mid": q[1], "hi": q[2], "basis": f"median of {len(peers)} {model} {risk}"}
    return {"lo": None, "mid": median(peers), "hi": None,
            "basis": f"{len(peers)} past {model} {risk}" if peers else f"no past {model} {risk} task"}


def task_diff(root, main: str) -> dict | None:
    """The open task branch against main: {plus, minus, files, tests}, from the working tree (committed or not).
    Cached for 3 s. ponytail: a task in a parallel worktree is not seen (the card names no diff then)."""
    from .dashboard import TEST_CASE, _git
    key = (str(root), int(time.time() // 3))
    if _cache.get("diffkey") == key:
        return _cache["diff"]
    raw = _git(root, "diff", "-U0", main)
    plus = minus = 0
    added: list[str] = []
    for ln in raw.splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            plus += 1
            added.append(ln[1:])
        elif ln.startswith("-") and not ln.startswith("---"):
            minus += 1
    files = len(re.findall(r"^diff --git ", raw, re.M))
    for rel in _git(root, "ls-files", "--others", "--exclude-standard").splitlines()[:50]:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            continue
        files += 1
        plus += text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        added += text.splitlines()
    out = {"plus": plus, "minus": minus, "files": files, "tests": len(TEST_CASE.findall("\n".join(added)))} \
        if files else None
    _cache.update(diffkey=key, diff=out)
    return out


def end_kind(run: dict) -> str:
    """The keyword of the end-phase step that runs now (audit, functional check, docs, replan), else ''."""
    cur = str(run.get("current") or "")
    return next((k for k in END_PHASE if cur.startswith(k)), "") if not run.get("task") else ""


def _tokens(state, where: str, arg) -> tuple[int, float]:
    r = state.db.execute("SELECT COALESCE(SUM(COALESCE(tokens_in,0)+COALESCE(tokens_out,0)+COALESCE(tokens_cache_read,0)"
                         f"+COALESCE(tokens_cache_write,0)),0), COALESCE(SUM(cost),0) FROM sessions WHERE {where}",
                         arg).fetchone()
    return int(r[0]), float(r[1])


def task_card(root, state, run: dict, doing: dict, tid: str, risk: str, peers: list, work, first_iso, clock: float,
              main: str, wait) -> dict:
    """The Now card of the task in work (features/watch-screen.md). Plain values only; the window clock decides what
    is shown of the time (dash_card.py)."""
    allsess = sessions(root)
    mine = [s for s in allsess if s["task"] == tid and s["kind"] == "task"]
    s = mine[-1] if mine else None
    past = [x for x in allsess if x["kind"] == "task" and x["done_at"] and x["task"] != tid]
    secs = step_secs(past)
    cur, at = str(run.get("current") or ""), epoch(run.get("current_at"))
    start = s["start"] if s else epoch(run.get("session_at"))
    edit, test, _ = marks(s) if s else (None, None, None)
    row = state.db.execute("SELECT ended_at FROM sessions WHERE task_id=? AND kind='task' ORDER BY id DESC LIMIT 1",
                           (tid,)).fetchone()
    if cur.startswith("gate: merge") or run.get("state") == "Commit":
        idx, since = 4, at
    elif cur.startswith("gate:"):
        idx, since = 3, at
    elif row and row[0]:
        idx, since = 3, epoch(row[0])
    else:
        idx, since = (2, test) if test else (1, edit) if edit else (0, start)
    eta = eta_text(peers, doing["model"], risk)
    w = weights(secs, 5)
    tokens, cost = _tokens(state, "task_id=?", (tid,))
    t0 = epoch(first_iso)
    return {"kind": "task", "n": doing["n"], "title": doing["title"], "model": doing["model"], "attempt": doing["attempt"],
            "max_attempts": doing["max_attempts"], "work": float(work or 0), "work_at": clock,
            "first_start": str(first_iso or "")[11:16] if t0 and clock - t0 > 2 * float(work or 0) + 60 else "",
            "eta": eta, "steps": list(STEPS), "step": idx, "since": since, "weights": w,
            "step_eta": secs[idx] if secs else eta["mid"] * w[idx] if eta["mid"] else None,
            "diff": task_diff(root, main), "tokens": tokens + int(run.get("live_tokens") or 0), "cost": cost,
            "wait": wait, "why": _why(state, tid) if doing["attempt"] > 1 else ""}


def _why(state, tid) -> str:
    r = state.db.execute("SELECT last_error FROM tasks WHERE id=?", (tid,)).fetchone()
    return " ".join(str(r[0] or "").split())[:80] if r else ""


def findings_noted(root, state) -> int:
    """W53: review findings kept per task (meta review_list:<id>, W40) plus the lines of FOLLOWUPS.md.
    ponytail: FOLLOWUPS.md has no dates; it is emptied when the auditor consumes it, so it counts since then."""
    from . import AGENT_DIR
    n = 0
    for r in state.db.execute("SELECT value FROM meta WHERE key LIKE 'review_list:%'"):
        try:
            n += len(json.loads(r[0]) or [])
        except (ValueError, TypeError):
            pass
    try:
        n += sum(1 for x in (root / AGENT_DIR / "FOLLOWUPS.md").read_text(encoding="utf-8").splitlines() if x.startswith("- ["))
    except OSError:
        pass
    return n


def end_card(root, state, run: dict, name: str, clock: float, wait) -> dict:
    """The Now card of an end-phase step: the completion audit, the functional check, the docs, the replan."""
    key = end_kind(run)
    title, what, kind = END_PHASE[key]
    s = next((x for x in reversed(sessions(root)) if x["kind"] == kind), None)
    idx, since = 0, s["start"] if s else epoch(run.get("session_at"))
    for ts, tool, text in (s["tools"] if s else []):
        if tool == "Bash" and TEST_CMD.search(text) and idx < 1:
            idx, since = 1, ts
        elif tool == "StructuredOutput":
            idx, since = 2, ts
    past = []
    for r in state.db.execute("SELECT started_at, ended_at FROM sessions WHERE kind=? AND ended_at IS NOT NULL", (kind,)):
        a, b = epoch(r[0]), epoch(r[1])
        if a and b and b >= a:
            past.append(b - a)
    tokens, cost = _tokens(state, "kind=? AND started_at >= ?", (kind, str(run.get("started_at") or "")))
    base = epoch(run.get("session_at"))
    return {"kind": "end", "title": title, "what": what, "model": name, "steps": list(END_STEPS), "step": idx,
            "since": since, "weights": [1 / 3] * 3, "step_eta": None, "then": THEN[key],
            "work": max(0.0, clock - base) if base else 0.0, "work_at": clock, "eta": eta_text(past, name, key),
            "tokens": tokens + int(run.get("live_tokens") or 0), "cost": cost, "wait": wait,
            "findings": findings_noted(Path(root), state)}


def pending(cfg, plan, state, run: dict, root, status: dict) -> list[dict]:
    """What is still open when the run ended: [{what, how}], each with the command or the person."""
    from . import AGENT_DIR
    from .dashboard import _git
    out = []
    for t in plan.all_tasks():
        if t.owner_only and status.get(t.id) != "done":
            out.append({"what": f"Owner task {t.id}: {t.title}"[:60], "how": "you do it"})
    out += [{"what": f"Blocked task {r['id']}", "how": f"ap unblock {r['id']}"} for r in state.tasks("blocked")]
    asked = len(state.decisions("OPEN"))
    if asked:
        out.append({"what": f"{asked} question(s) wait for you", "how": "ap answer"})
    if "audit failed to produce a report" in str(run.get("outcome") or ""):
        out.append({"what": "The completion audit gave no report", "how": "ap start"})
    open_n, first = 0, ""
    for f in sorted((root / cfg.get("docs.history_dir", f"{AGENT_DIR}/history")).glob("*/PROOF.md")):
        try:
            sec = f.read_text(encoding="utf-8").partition("## Not proven")[2].partition("\n## ")[0]
        except OSError:
            continue
        items = [x for x in sec.splitlines() if x.startswith("- ") and not x[2:].startswith("Nothing.")]
        if items:
            open_n, first = open_n + len(items), first or str(f.relative_to(root)).replace("\\", "/")
    if open_n:
        out.append({"what": f"{open_n} Not proven item(s)", "how": first})
    if cfg.get("deploy.prod.enabled"):
        wait = [r["id"] for r in state.db.execute("SELECT id FROM phases WHERE prod_status='awaiting_approval'")]
        if wait:
            out.append({"what": f"Deploy to prod waits ({', '.join(wait)})", "how": f"ap approve {wait[0]}"})
    main = str(cfg.get("main_branch", "main"))
    if main not in ("main", "master"):
        out.append({"what": f"The work is on branch {main}", "how": f"git merge {main}"})
    if _git(root, "remote") and not cfg.get("git.push"):
        out.append({"what": "Nothing is pushed (git.push is off)", "how": "git push"})
    try:
        entries = (root / "CHANGELOG.md").read_text(encoding="utf-8").partition("## [Unreleased]")[2].partition("\n## ")[0]
    except OSError:
        entries = ""
    n = sum(1 for x in entries.splitlines() if x.startswith("- "))
    if n and (root / "scripts" / "bump.py").exists():
        out.append({"what": f"No release yet ({n} CHANGELOG entries)", "how": "python scripts/bump.py"})
    return out


def ended_card(cfg, plan, state, run: dict, root, status: dict, done: int, total: int, elapsed: str, live: bool,
               dead_since: str) -> dict:
    """The final summary block: the outcome word, the counts and what is still pending."""
    dead = run.get("status") == "running" and not live
    word = "DEAD" if dead else str(run.get("word") or "") or ("VERIFIED" if done == total and total else "STOPPED")
    sym, tone = WORDS.get(word, ("⏸", "yellow"))
    return {"kind": "ended", "word": word, "sym": sym, "tone": tone,
            "at": dead_since if dead else str(run.get("updated_at") or "")[11:16], "done": done, "total": total,
            "retries": sum(max(0, int(r["attempts"] or 0) - 1) for r in state.tasks()), "cost": round(state.cost(), 2),
            "elapsed": elapsed, "pending": pending(cfg, plan, state, run, root, status)}


def end_steps(cfg, plan) -> int:
    """How many end steps the profile will run after the last task: completion audit, functional check, final docs."""
    return (int(bool(cfg.get("audit.enabled") and cfg.get("audit.completion_audit") and not cfg.lean))
            + int(bool(cfg.get("functional.enabled", True) and any(p.features for p in plan.phases)))
            + int(bool(cfg.get("docs.session", True))))
