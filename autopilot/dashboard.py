"""J9: the data of the dashboard, one plain dict for both views (the browser page in dash_web.py and the terminal
window in dash_term.py). It only reads. Every value is a str, int, float, bool, None, list or dict, so a view never
needs the plan, the state or the log."""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import time

from . import dash_live
from .decisions import problems
from .plain import SimpleView, ending
from .report import (MODEL_NAMES, STATE_WORDS, _n, _runtime, _shares, next_steps, open_window, run_alive,
                     status_line, warned_tasks)

CODE = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".hpp", ".cs",
        ".rb", ".php", ".html", ".css", ".scss", ".vue", ".svelte", ".sh", ".ps1", ".sql"}
DOCS = {".md", ".rst", ".txt"}
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")
TEST_CASE = re.compile(r"^\s*(?:async\s+)?def test_|^\s*(?:it|test)\(|^\s*#\[test\]|^func Test", re.M)
_cache: dict = {}  # (root, commit) -> the facts that only change with a commit


def _git(root, *args) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=5,  # noqa: S603, S607
                             encoding="utf-8", errors="replace")
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _span(start, end) -> str:
    """'4m' between two ISO times, '' when one is missing or the clock went back."""
    try:
        secs = (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return ""
    return "" if secs < 0 else _dur(secs)


def _dur(secs: float) -> str:
    if secs >= 86400:
        return f"{int(secs // 86400)}d"
    return f"{int(secs // 3600)}h{int(secs % 3600 // 60):02d}m" if secs >= 3600 else f"{max(1, round(secs / 60))}m"


def project_size(root) -> dict:
    """Lines of code, tests and docs in the files that git tracks, and the number of test cases (a count of test
    functions, not a result). Lock files, images and files over 1 MB are not counted, and .agent/ is not the product.
    ponytail: the split is by file type and folder name; an unusual layout can put a file in the wrong group."""
    size = {"code": 0, "tests": 0, "docs": 0, "test_count": 0}
    for rel in _git(root, "ls-files").splitlines()[:5000]:
        ext = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else ""
        if rel.startswith(".agent/") or ext not in CODE | DOCS:
            continue
        try:
            path = root / rel
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        if ext in DOCS:
            size["docs"] += lines
        elif TEST_FILE.search(rel.lower()):
            size["tests"] += lines
            size["test_count"] += len(TEST_CASE.findall(text))
        else:
            size["code"] += lines
    return size


def by_commit(root, main: str, started: str) -> dict:
    """The facts that change only with a commit on main: the last commit, the size of the project, what this run
    changed. One git call for each refresh finds the commit; the rest is read again only for a new commit."""
    head = _git(root, "log", "-1", "--format=%h%x09%ct%x09%s", main) or _git(root, "log", "-1", "--format=%h%x09%ct%x09%s")
    sha, _, rest = head.partition("\t")
    stamp, _, subject = rest.partition("\t")
    key = (str(root), sha, started)
    if key not in _cache:
        _cache.clear()  # one project, one commit: nothing old is of use
        facts = {"commit": sha, "subject": subject, "stamp": int(stamp) if stamp.isdigit() else 0,
                 "size": project_size(root) if sha else None, "files": None, "run": None}
        if sha and started:
            marks = re.findall(r"^([AMD])\t", _git(root, "log", f"--since={started}", "--name-status",
                                                  "--pretty=format:", main), re.M)
            facts["files"] = {"added": marks.count("A"), "modified": marks.count("M"), "deleted": marks.count("D")}
            base = _git(root, "rev-list", "-1", f"--before={started}", main)
            stat = _git(root, "diff", "--shortstat", base, main) if base else ""
            files, plus = re.search(r"(\d+) files? changed", stat), re.search(r"(\d+) insertions?", stat)
            if files:
                gone = re.search(r"(\d+) deletions?", stat)
                diff = _git(root, "diff", "-U0", base, main)  # J13/6: tests added = new test functions in the diff
                new = "\n".join(x[1:] for x in diff.splitlines() if x.startswith("+") and not x.startswith("+++"))
                facts["run"] = {"files": int(files.group(1)), "lines": int(plus.group(1)) if plus else 0,
                                "removed": int(gone.group(1)) if gone else 0, "tests": len(TEST_CASE.findall(new))}
                facts["files"].update(plus=facts["run"]["lines"], minus=facts["run"]["removed"], tests=facts["run"]["tests"])
        _cache[key] = facts
    return _cache[key]


def live_rows(root, plan, lines: int = 40, live: bool = False) -> list[dict]:
    """The last lines of the simple view as {at, text, kind}; kind: heading, goal, step, good, bad, note, blank."""
    from . import AGENT_DIR
    log = root / AGENT_DIR / "logs" / "autopilot.log"
    ids = plan.all_tasks()
    view = SimpleView({t.id: (i + 1, len(ids), t.title, t.description) for i, t in enumerate(ids)})
    # ponytail: reads the end of the log on each call; read by offset if a log grows to many MB
    raw = log.read_text(encoding="utf-8", errors="replace").splitlines()[-600:] if log.exists() else []
    # J13/8: the time of a step = the session clock of the line that ends it minus the clock of the line that began it
    clock = lambda row: (lambda m: int(m.group(1)) * 60 + int(m.group(2)) if m else None)(  # noqa: E731
        re.search(r"· (\d+)m(\d\d)s\s*$", row))
    outs, begun, last = [], None, None
    for row in raw:
        g0, now_s = view.group, clock(row)
        got = view.feed(row)
        if now_s is not None:
            last = now_s
        if g0 and view.group is not g0 and got:  # the group g0 ended with the first line
            took = now_s - begun if now_s is not None and begun is not None and now_s >= begun else None
            outs.append((got[0], took))
            got = got[1:]
        if view.group is not g0 and view.group:
            begun = now_s
        outs += [(x, None) for x in got]
    tail = view.close()
    if tail:
        outs.append((tail[0], last - begun if last is not None and begun is not None and last >= begun else None))
    rows = []
    for text, took in outs[-lines:]:
        m = re.match(r"(\d\d:\d\d)  (.*)$", text)
        at, body = (m.group(1), m.group(2)) if m else ("", text)
        kind = ("blank" if not text else "goal" if text.startswith("Goal: ") else "heading" if not m else
                "good" if " is complete." in body else
                "bad" if body.startswith(("The checks failed.", "The build stopped.")) else
                "note" if not re.match(r"(Reads|Writes|Changes|Checks|Runs|Searches|Installs|Uses) ", body) else "step")
        rows.append({"at": at, "text": body, "kind": kind,
                     **({"took": f"{took // 60}m{took % 60:02d}s"} if took is not None and kind == "step" else {})})
    try:  # a tool that runs for over 60 s writes nothing: say so, dim
        quiet = int(time.time() - log.stat().st_mtime)
    except OSError:
        quiet = 0
    if live and raw and quiet > 60 and "▸" in raw[-1]:
        rows.append({"at": "", "text": f"A tool runs for {_dur(quiet)}.", "kind": "wait"})
    return rows


def _first(text, limit: int = 90) -> str:
    line = re.sub(r"^[A-Z]+:\s*", "", " ".join(str(text or "").split()))  # e.g. the gate's "PROBLEM: " prefix
    line = re.split(r"(?<=[.!?:])\s", line)[0].rstrip(":")
    return line if len(line) <= limit else line[:limit - 4].rsplit(" ", 1)[0] + " ..."


def data_mtime(root, run: dict) -> float | None:
    """The time of the newest sign of life: the run journal, the state file (and its WAL), the log. None when none has one."""
    from . import AGENT_DIR
    stamps = []
    try:
        stamps.append(dt.datetime.fromisoformat(run["updated_at"]).timestamp())
    except (KeyError, TypeError, ValueError):
        pass
    for rel in ("state.db", "state.db-wal", "logs/autopilot.log"):
        try:
            stamps.append((root / AGENT_DIR / rel).stat().st_mtime)
        except OSError:
            pass
    return max(stamps) if stamps else None


def data_age(root, run: dict) -> int | None:
    """J13/11: seconds since data_mtime. None when there is no time (the view shows a dash, never a guess)."""
    m = data_mtime(root, run)
    return max(0, int(time.time() - m)) if m is not None else None


SPIN = {True: ("⠋⠙⠹⠸⠼⠴⠦⠧", "⏸", "✗"), False: ("|/-\\", "||", "x")}  # braille dots, or ASCII when the console is not UTF-8


def is_utf(stream) -> bool:
    """True when the console encoding is UTF-8 (braille spinner); else the ASCII spinner."""
    return "utf" in (getattr(stream, "encoding", "") or "").lower()


def spinner(d: dict, mtime, now: float, prev: dict | None = None, utf: bool = True) -> dict:
    """J13/18: the one running indicator, for both views. The frame moves only when the data file changed since the
    last call (prev = the dict this function returned last time). kind: run (turns), stale (no change for over 30 s:
    frozen, yellow), stopped (the run ended: red, with the end time), or '' (nothing to show)."""
    frames, pause, stop = SPIN[utf]
    a, prev = d.get("asof") or {}, prev or {}
    seen = mtime
    mtime = a["pulse"] if a.get("pulse") is not None else mtime  # W18a: the data or the runner heartbeat, the newest
    frame = int(prev.get("frame", 0)) + (1 if prev and mtime != prev.get("mtime") else 0)
    age = max(0, int(now - mtime)) if mtime is not None else a.get("age")
    out = {"frame": frame, "mtime": mtime, "clock": now, "age": age, "utf": utf,
           "data_age": max(0, int(now - seen)) if seen is not None else age}
    if not a.get("live", True):
        stopped = a.get("stopped") or ""
        return {**out, "kind": "stopped" if stopped else "", "text": f"{stop} stopped {stopped}" if stopped else ""}
    if isinstance(age, (int, float)) and age > 30:
        what = a.get("wait_text")  # W18a: a gate or the start check says what it waits for, not 'no change'
        return {**out, "kind": "stale", "text": f"{pause} {what}" if what else
                f"{pause} no change {age}s" if age < 60 else f"{pause} no change {age // 60}m"}
    return {**out, "kind": "run", "text": frames[frame % len(frames)]}


def dashboard_data(cfg, plan, state, run: dict) -> dict:
    root = cfg.root
    status, tasks = state.status_map(), plan.all_tasks()
    done = sum(1 for t in tasks if status.get(t.id) == "done")
    blocked = sum(1 for t in tasks if status.get(t.id) == "blocked")
    live, dead_since = run_alive(run)
    finished = run.get("status") == "finished"
    rows = {r["id"]: r for r in state.tasks()}
    now = dt.datetime.now().isoformat(timespec="seconds")
    name = lambda m: next((s for k, s in MODEL_NAMES.items() if k in str(m).lower()), str(m or ""))  # noqa: E731

    # J13/15: a task's time = its first session to its merge (every try), not the last attempt only
    first = {r[0]: r[1] for r in state.db.execute(
        "SELECT task_id, MIN(started_at) FROM sessions WHERE kind IN ('task','review','unstick') AND task_id IS NOT NULL "
        "GROUP BY task_id")}

    def secs(a, b):
        try:
            return max(0.0, (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds())
        except (TypeError, ValueError):
            return None

    # W42: a task's time is the sum of its sessions (a running one counts to now), never the wall clock between them
    work: dict = {}
    for r in state.db.execute("SELECT task_id, started_at, ended_at FROM sessions WHERE kind IN ('task','review','unstick') "
                              "AND task_id IS NOT NULL"):
        work[r[0]] = work.get(r[0], 0.0) + (secs(r[1], r[2] or (now if rows.get(r[0]) and rows[r[0]]["status"] == "running" else None)) or 0.0)

    def took(r, st, tries):  # (seconds, 'took 24m' [+ ' (3 tries, first 15:12)' when the wall span is over 2x the work])
        w, a, b = work.get(r["id"]), *span(r)
        if not w:
            return None, ""
        text, wall = f"took {_dur(w)}", secs(a, b if st == "done" else now)
        if wall and wall > 2 * w and a:
            text += f" ({tries} {'try' if tries == 1 else 'tries'}, first {str(a)[11:16]})"
        return w, text

    def span(r):  # (start, end) of a task: first session to the merge, or to now while it works
        start = first.get(r["id"]) or r["started_at"]
        return (start, r["finished_at"] if r["status"] == "done" else now if r["status"] == "running" else None)

    def one(i, t):
        r = rows.get(t.id)
        a, b = span(r) if r else (None, None)
        st = "running" if live and run.get("task") == t.id else status.get(t.id, "pending")
        st = st if st in ("done", "running", "blocked") else "pending"
        tries = int(r["attempts"] or 0) if r else 0
        if st == "running":  # the session in work, not the last attempt in the database
            tries, model = int(run.get("attempt") or 1), name(run.get("model"))
        else:
            model = name(r["model"]) if r else ""
        w, note = took(r, st, tries) if r and st in ("done", "running") else (None, "")
        return {"n": i + 1, "id": t.id, "title": t.title, "phase": t.phase_id, "status": st,
                "risk": t.risk, "tries": tries, "secs": w if w is not None else (secs(a, b) or 0) if r and a and b else None,
                "time": _dur(w) if w else (_span(a, b) if st == "done" else _span(a, now) if st == "running" else "") if r else "",
                "took": note,
                "detail": " · ".join(x for x in (model, f"{tries} tries" if tries > 1 else "") if x)}

    table = [one(i, t) for i, t in enumerate(tasks)]
    gone = sorted(t["secs"] for t in table if t["status"] == "done" and t["secs"] is not None)
    med = (gone[len(gone) // 2] if len(gone) % 2 else (gone[len(gone) // 2 - 1] + gone[len(gone) // 2]) / 2) if gone else 0
    for t in table:  # J13/17: a time over 2x the median task time shows yellow
        t["slow"] = bool(med and t["secs"] and t["secs"] > 2 * med)
    working = [t for t in table if t["status"] == "running"]
    here = [r for r in state.tasks("done") if (r["finished_at"] or "") >= (run.get("started_at") or "")]
    left = sum(1 for t in tasks if status.get(t.id, "pending") in ("pending", "running"))
    # J13/15: tasks + other = elapsed. The tasks' time is the union of their spans inside the run, so a parallel run
    # never counts one minute twice. Elapsed ends now (live) or at the last journal write.
    begin, end = run.get("started_at"), now if live else run.get("updated_at")
    elapsed = secs(begin, end) if begin and end else None
    time_secs = None
    if elapsed is not None:
        cut = sorted((max(s, 0.0), min(e, elapsed)) for s, e in (
            (secs(begin, a), secs(begin, b)) for a, b in (span(r) for r in rows.values() if r["id"] in first or r["started_at"])
            if a and b) if s is not None and e is not None and min(e, elapsed) > max(s, 0.0))
        used, edge = 0.0, 0.0
        for s, e in cut:
            used += max(0.0, e - max(s, edge))
            edge = max(edge, e)
        time_secs = {"tasks": round(used), "other": round(elapsed) - round(used), "elapsed": round(elapsed)}
    # J13/16: ETA = (queued / parallel) x median task time of this run + what the running tasks still need
    eta, mid = "", None
    if live and left:
        spent = sorted(s for s in (secs(*span(r)) for r in here if r["id"] in rows) if s is not None)
        if len(spent) < 3:
            eta = f"after 3 tasks ({len(spent)} done)"
        else:
            mid = spent[len(spent) // 2] if len(spent) % 2 else (spent[len(spent) // 2 - 1] + spent[len(spent) // 2]) / 2
            par = max(1, int(cfg.get("scheduling.parallel", 1) or 1))
            run_rows = [rows[t["id"]] for t in table if t["status"] == "running"]
            queued = left - len(run_rows)
            rest = sum(max(0.0, mid - (secs(*span(r)) or 0)) for r in run_rows)
            total = queued * mid / par + rest / par
            hours = f"{total / 3600:.1f}h" if total >= 5400 else f"{round(total / 60)}m"
            basis = (f"{queued} × {_dur(mid)}" if queued else f"{len(run_rows)} running, {_dur(mid)} each") + \
                (f" + {_dur(rest)} now" if queued and rest else "")
            eta = f"~{hours} ({basis})"
    total, models, _, _ = _shares(state, 0)
    five, week = open_window(state), (state.get_meta("window_seen", {}) or {}).get("seven_day") or {}
    used = int(run.get("context_tokens") or 0) if live else 0
    main = str(cfg.get("main_branch", "main"))
    facts = by_commit(root, main, str(run.get("started_at") or ""))

    # J10: what the build does now, what is next, and what waits for the person
    doing = None
    if live and working:  # one task in work; a parallel run has no single task in the journal
        t = working[0]
        doing = {"n": t["n"], "title": t["title"], "attempt": int(run.get("attempt") or 1),
                 "max_attempts": int(run.get("max_attempts") or 0), "time": t["time"], "model": name(run.get("model")),
                 "work": t["secs"] or 0.0, "work_at": time.time(),  # W18b: the work time, as the Tasks table counts it
                 "since": round(dt.datetime.fromisoformat(first.get(t["id"]) or rows[t["id"]]["started_at"]).timestamp())
                 if t["id"] in rows and (first.get(t["id"]) or rows[t["id"]]["started_at"]) else None}
    elif live and run.get("state") not in ("Wait", "Block"):
        many = sum(1 for t in tasks if status.get(t.id) == "running")
        doing = {"n": 0, "title": f"{many} tasks in work" if many > 1 else str(run.get("current") or ""),
                 "attempt": 1, "max_attempts": 0, "time": "", "model": name(run.get("model"))}
    try:
        nxt = plan.next_ready({**status, **({run["task"]: "running"} if live and run.get("task") else {})},
                              cfg.get("scheduling.phase_dependency", "soft"))
    except Exception:  # noqa: BLE001 — a plan in the middle of a change
        nxt = None
    asked = state.decisions("OPEN")
    stuck = next((r for r in state.tasks("blocked")), None)
    stale = 0
    if live:
        try:
            stale = int((dt.datetime.fromisoformat(now) - dt.datetime.fromisoformat(run["updated_at"])).total_seconds() // 60)
        except (KeyError, TypeError, ValueError):
            stale = 0
    git, checks = (str(run.get("git") or ""), str(run.get("build") or "")) if live else ("", "")
    warned = [tid for p in plan.phases for tid in warned_tasks(cfg, p)]
    why_warned = []  # J13/7: the first gate warning of each warned task, from its history file
    hist = root / cfg.get("docs.history_dir", ".agent/history")
    for p in plan.phases:
        for tid in warned_tasks(cfg, p):
            try:
                first_line = (hist / p.id / f"{tid}.md").read_text(encoding="utf-8").rpartition("## Gate warnings\n")[2].splitlines()[0]
            except (OSError, IndexError):
                continue
            why_warned.append({"id": tid, "why": first_line.lstrip("- ").replace("outside files_in_scope", "out of scope")[:70]})
    # J13/3: the last error still open (a task that is not done); J13/5: minutes per done task, from the task spans
    broken = max((r for r in rows.values() if r["last_error"] and r["status"] != "done"),
                 key=lambda r: r["updated_at"] or "", default=None)
    kept = [secs(*span(r)) for r in rows.values() if r["status"] == "done"]
    kept = [x for x in kept if x is not None]
    login = (state.get_meta("window_seen", {}) or {}).get("plan_tier")
    backend = str(cfg.get("agent.backend", "claude_cli"))
    runner = ("claude" if backend == "claude_cli" else
              str(cfg.get("agent.preset") or (cfg.get("agent.command") or "command").split()[0]))
    ended = sorted((r for r in rows.values() if r["status"] == "done" and r["finished_at"]),
                   key=lambda r: r["finished_at"], reverse=True)[:3]
    number = {t["id"]: t for t in table}
    clock = time.time()
    wait = dash_live.waiting(root, run, live, clock)
    err_age, err_old = dash_live.error_age(state, broken, clock) if broken else ("", False)
    why_age, why_old = dash_live.error_age(state, stuck, clock) if stuck else ("", False)
    # W18b: the Now card (a task, an end-phase step, or the end of the run) and the total with the end steps
    risk_of, card = {t.id: t.risk for t in tasks}, None
    if doing and doing["n"] and working:
        peers = [work[i] for i, r in rows.items() if r["status"] == "done" and work.get(i) and name(r["model"]) == doing["model"]
                 and risk_of.get(i) == risk_of.get(working[0]["id"])]
        card = dash_live.task_card(root, state, run, doing, working[0]["id"], risk_of.get(working[0]["id"], ""), peers,
                                   work.get(working[0]["id"]), first.get(working[0]["id"]), clock, main, wait)
    elif live and dash_live.end_kind(run):
        card = dash_live.end_card(root, state, run, name(run.get("model")), clock, wait)
    elif run.get("status") in ("finished", "running"):
        card = dash_live.ended_card(cfg, plan, state, run, root, status, done, len(tasks),
                                    _dur(time_secs["elapsed"]) if time_secs else "", live, dead_since)
    n_end = dash_live.end_steps(cfg, plan) if live else 0
    pct = 100 if not live and tasks and done == len(tasks) else 100 * done // (len(tasks) + n_end) if tasks else 0
    added = next((int(m.group(1)) for r in state.db.execute(
        "SELECT message FROM events WHERE kind='audit' AND ts >= ? ORDER BY id DESC", (str(run.get("started_at") or ""),))
        if (m := re.search(r"added (\d+) tasks", r[0]))), 0)
    kind = card["kind"] if card else ""
    step_word = (("Done " if card["word"] == "VERIFIED" else "Ended ") + card["word"] if kind == "ended" else
                 {"audit": "Checking the whole plan", "functional check": "Checking the features",
                  "docs": "Writing the docs", "replan": "Planning again"}.get(dash_live.end_kind(run), "Working")
                 if kind == "end" else f"Building {working[0]['n']} of {len(tasks)}" if kind == "task" else "")
    return {
        # the age of the data; a run that is not live shows when it stopped
        "asof": {"age": data_age(root, run), "live": live, "mtime": data_mtime(root, run),
                 "stopped": "" if live else dead_since or str(run.get("updated_at") or "")[11:16],
                 "dead_since": dead_since, "pulse": dash_live.pulse(run, data_mtime(root, run)) if live else None,
                 "wait_text": str(run.get("current") or "") if live and dash_live.gate_label(run.get("current")) else ""},
        "project": {
            "name": str(cfg.get("name", root.name)), "branch": main, "commit": facts["commit"],
            "last_commit": _first(facts["subject"], 60),
            "last_commit_age": _dur(time.time() - facts["stamp"]) if 0 < facts["stamp"] <= time.time() else "",
            # J13/17: no commit for over 10 minutes while a task works is a stall
            "commit_stalled": bool(live and working and 0 < facts["stamp"] <= time.time() - 600),
            "model": name(run.get("model")) if live else "", "state": str(run.get("state") or "") if live else "",
            "runner": runner, "login": str(login or "not checked"),  # J13/17: the plan is stored by no check yet: no call
            "resets": f"{dt.datetime.fromtimestamp(float(five['reset'])):%H:%M}" if five else "—",
            "last_error": _first(broken["last_error"], 70) if broken else "—",
            "error_age": err_age, "error_old": err_old,
            "version": dash_live.version_text(), "run_line": dash_live.run_line(state, clock), "wait": wait,
            "since_ts": dash_live.epoch(run.get("started_at")) if live else None,
            "end_title": f"{card['sym']} {card['word']} {card['at']}".strip() if kind == "ended" else "",
            "word": str(run.get("word") or ""),  # P14: the W3 outcome word of the last run
            "run_id": str(run.get("run_id") or ""),"started": str(run.get("started_at") or "").replace("T", " "),
            "status": "running" if live else "finished" if finished else "idle",
            # how the status word looks: good, wait (it needs the person or a usage window), bad, or '' (neutral)
            "tone": ("wait" if live and run.get("state") in ("Wait", "Block") else "good" if live else
                     "good" if finished and done == len(tasks) else "bad" if finished else ""),
            "state_words": (STATE_WORDS.get(str(run.get("state") or ""), "Works.") if live else
                            ending(run.get("outcome")) if finished else "No build is active."),
            "elapsed": _runtime(run.get("started_at")) if live else "", "eta": eta,
            "other": _dur(time_secs["other"]) if time_secs and time_secs["other"] > 0 else "", "time_secs": time_secs,
            "attempt": int(run.get("attempt") or 1) if live else 0,
            "now": doing, "next": nxt.title if nxt else "",
            # a build that writes nothing for a long time can be in one long command, or stuck
            "stale_min": stale if stale >= 5 else 0, "stale": "bad" if stale >= 30 else "warn" if stale >= 10 else "",
        },
        "progress": {
            "done": done, "total": len(tasks), "pct": pct, "end_steps": n_end, "audit_added": added, "word": step_word,
            "phases_done": sum(1 for p in plan.phases if p.tasks and all(status.get(t.id) == "done" for t in p.tasks)),
            "phases_total": len(plan.phases), "blocked": blocked, "questions": len(asked),
            "warnings": len(warned), "warned": warned[:6], "warned_why": why_warned[:6],
            "retries": sum(max(0, int(r["attempts"] or 0) - 1) for r in rows.values()),
            "working": len(working) if live else 0, "waiting": max(0, len(tasks) - done - blocked - (len(working) if live else 0)),
            "active": working[0]["n"] if live and working else 0,
        },
        "card": card,
        "needs_you": [{"id": str(d["id"]), "title": _first(d["title"] or d["question"], 70)} for d in asked[:2]],
        # the same simple sentence as docs/NEEDS-YOU.md gives for this problem
        "blocked_why": ({"id": stuck["id"], "why": (problems(stuck["last_error"] or stuck["note"])
                                                    or ["No reason is recorded."])[0][:160],
                         "age": why_age, "old": "1" if why_old else ""} if stuck else None),
        # J11: each phase in one line, and the tasks that ended last
        "phases": [{"id": p.id, "title": p.title, "total": len(p.tasks),
                    "done": sum(1 for t in p.tasks if status.get(t.id) == "done"),
                    "status": ("done" if p.tasks and all(status.get(t.id) == "done" for t in p.tasks) else
                               "blocked" if any(status.get(t.id) == "blocked" for t in p.tasks) else
                               "running" if any(status.get(t.id) == "done" for t in p.tasks)
                               or (live and any(run.get("task") == t.id for t in p.tasks)) else "pending")}
                   for p in plan.phases],
        "recent": [{"n": number[r["id"]]["n"], "title": number[r["id"]]["title"], "time": number[r["id"]]["time"]}
                   for r in ended if r["id"] in number],
        "tasks": table,
        "live": live_rows(root, plan, live=live),
        "usage": {
            "five": float(five["pct"]) if five else None,
            "week": float(week["pct"]) if five and "pct" in week else None,
            "reset_in": _dur(float(five["reset"]) - time.time()) if five and float(five.get("reset") or 0) > time.time() else "",
            "context": (used / (200_000 if used <= 200_000 else 1_000_000)) if used else None,
            "tokens_text": _n(total), "cost": round(state.cost(), 2),
            "rate": f"{round(sum(kept) / len(kept) / 60)} min per task" if kept else "—",
            "models": [{"name": name(m), "tokens_text": _n(v["total"]), "share": v["total"] / total}
                       for m, v in sorted(models, key=lambda x: -x[1]["total"]) if total and v["total"]],
        },
        "size": ({**facts["size"], "run_lines": facts["run"]["lines"] if facts["run"] else None,
                  "run_files": facts["run"]["files"] if facts["run"] else None,
                  "run_tasks": len(here)} if facts["size"] else None),
        "files": facts["files"],
        "health": {"git": git, "checks": checks,
                   "words": " ".join(x for x in ("The checks fail on main." if checks == "Red" else "",
                                                 "Git has no connection." if git == "Off" else "",
                                                 "The push to GitHub fails." if git == "Push!" else "") if x)},
        "next": [tuple(re.split(r"\s{2,}", tip, maxsplit=1)) if re.search(r"\s{2,}", tip) else (tip, "")
                 for tip in next_steps(root, live)],
        "line": status_line(cfg, plan, state, run),
    }
