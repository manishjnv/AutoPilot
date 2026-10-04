"""J9: the data of the dashboard, one plain dict for both views (the browser page in dash_web.py and the terminal
window in dash_term.py). It only reads. Every value is a str, int, float, bool, None, list or dict, so a view never
needs the plan, the state or the log."""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import time

from .decisions import problems
from .plain import SimpleView, ending
from .report import (MODEL_NAMES, STATE_WORDS, _n, _runtime, _shares, next_steps, open_window, status_line,
                     warned_tasks)

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
                facts["run"] = {"files": int(files.group(1)), "lines": int(plus.group(1)) if plus else 0}
        _cache[key] = facts
    return _cache[key]


def live_rows(root, plan, lines: int = 40) -> list[dict]:
    """The last lines of the simple view as {at, text, kind}; kind: heading, goal, step, good, bad, note, blank."""
    from . import AGENT_DIR
    log = root / AGENT_DIR / "logs" / "autopilot.log"
    ids = plan.all_tasks()
    view = SimpleView({t.id: (i + 1, len(ids), t.title, t.description) for i, t in enumerate(ids)})
    # ponytail: reads the end of the log on each call; read by offset if a log grows to many MB
    raw = log.read_text(encoding="utf-8", errors="replace").splitlines()[-600:] if log.exists() else []
    rows = []
    for text in ([out for row in raw for out in view.feed(row)] + view.close())[-lines:]:
        m = re.match(r"(\d\d:\d\d)  (.*)$", text)
        at, body = (m.group(1), m.group(2)) if m else ("", text)
        kind = ("blank" if not text else "goal" if text.startswith("Goal: ") else "heading" if not m else
                "good" if " is complete." in body else
                "bad" if body.startswith(("The checks failed.", "The build stopped.")) else
                "note" if not re.match(r"(Reads|Writes|Changes|Checks|Runs|Searches|Installs|Uses) ", body) else "step")
        rows.append({"at": at, "text": body, "kind": kind})
    return rows


def _first(text, limit: int = 90) -> str:
    line = re.sub(r"^[A-Z]+:\s*", "", " ".join(str(text or "").split()))  # e.g. the gate's "PROBLEM: " prefix
    line = re.split(r"(?<=[.!?:])\s", line)[0].rstrip(":")
    return line if len(line) <= limit else line[:limit - 4].rsplit(" ", 1)[0] + " ..."


def dashboard_data(cfg, plan, state, run: dict) -> dict:
    root = cfg.root
    status, tasks = state.status_map(), plan.all_tasks()
    done = sum(1 for t in tasks if status.get(t.id) == "done")
    blocked = sum(1 for t in tasks if status.get(t.id) == "blocked")
    live = run.get("status") == "running"
    finished = run.get("status") == "finished"
    rows = {r["id"]: r for r in state.tasks()}
    now = dt.datetime.now().isoformat(timespec="seconds")
    name = lambda m: next((s for k, s in MODEL_NAMES.items() if k in str(m).lower()), str(m or ""))  # noqa: E731

    def one(i, t):
        r = rows.get(t.id)
        st = "running" if live and run.get("task") == t.id else status.get(t.id, "pending")
        st = st if st in ("done", "running", "blocked") else "pending"
        tries = int(r["attempts"] or 0) if r else 0
        if st == "running":  # the session in work, not the last attempt in the database
            tries, model = int(run.get("attempt") or 1), name(run.get("model"))
        else:
            model = name(r["model"]) if r else ""
        return {"n": i + 1, "id": t.id, "title": t.title, "phase": t.phase_id, "status": st,
                "time": (_span(r["started_at"], r["finished_at"]) if st == "done" else
                         _span(r["started_at"], now) if st == "running" else "") if r else "",
                "detail": " · ".join(x for x in (model,
                                                 f"{tries} attempts" if tries > 1 else "") if x)}

    table = [one(i, t) for i, t in enumerate(tasks)]
    working = [t for t in table if t["status"] == "running"]
    here = [r for r in state.tasks("done") if (r["finished_at"] or "") >= (run.get("started_at") or "")]
    left = sum(1 for t in tasks if status.get(t.id, "pending") in ("pending", "running"))
    eta = ""
    if live and left and len(here) >= 3:  # the same pace rule as the digest (G3)
        ms = state.db.execute("SELECT COALESCE(SUM(duration_ms),0) FROM sessions WHERE id >= ?",
                              (int(run.get("first_session") or 0),)).fetchone()[0]
        mins = left * ms / len(here) / 60000
        eta = f"{round(mins)}m" if mins < 90 else f"{mins / 60:.1f}h"
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
                 "max_attempts": int(run.get("max_attempts") or 0), "time": t["time"], "model": name(run.get("model"))}
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
    return {
        "project": {
            "name": str(cfg.get("name", root.name)), "branch": main, "commit": facts["commit"],
            "last_commit": _first(facts["subject"], 60),
            "last_commit_age": _dur(time.time() - facts["stamp"]) if 0 < facts["stamp"] <= time.time() else "",
            "model": name(run.get("model")) if live else "",
            "run_id": str(run.get("run_id") or ""), "started": str(run.get("started_at") or "").replace("T", " "),
            "status": "running" if live else "finished" if finished else "idle",
            # how the status word looks: good, wait (it needs the person or a usage window), bad, or '' (neutral)
            "tone": ("wait" if live and run.get("state") in ("Wait", "Block") else "good" if live else
                     "good" if finished and done == len(tasks) else "bad" if finished else ""),
            "state_words": (STATE_WORDS.get(str(run.get("state") or ""), "Works.") if live else
                            ending(run.get("outcome")) if finished else "No build is active."),
            "elapsed": _runtime(run.get("started_at")) if live else "", "eta": eta,
            "attempt": int(run.get("attempt") or 1) if live else 0,
            "now": doing, "next": nxt.title if nxt else "",
            # a build that writes nothing for a long time can be in one long command, or stuck
            "stale_min": stale if stale >= 5 else 0, "stale": "bad" if stale >= 30 else "warn" if stale >= 10 else "",
        },
        "progress": {
            "done": done, "total": len(tasks), "pct": 100 * done // len(tasks) if tasks else 0,
            "phases_done": sum(1 for p in plan.phases if p.tasks and all(status.get(t.id) == "done" for t in p.tasks)),
            "phases_total": len(plan.phases), "blocked": blocked, "questions": len(asked),
            "warnings": sum(len(warned_tasks(cfg, p)) for p in plan.phases),
            "working": len(working) if live else 0, "waiting": max(0, len(tasks) - done - blocked - (len(working) if live else 0)),
            "active": working[0]["n"] if live and working else 0,
        },
        "needs_you": [{"id": str(d["id"]), "title": _first(d["title"] or d["question"], 70)} for d in asked[:2]],
        # the same simple sentence as docs/NEEDS-YOU.md gives for this problem
        "blocked_why": ({"id": stuck["id"], "why": (problems(stuck["last_error"] or stuck["note"])
                                                    or ["No reason is recorded."])[0][:160]} if stuck else None),
        "tasks": table,
        "live": live_rows(root, plan),
        "usage": {
            "five": float(five["pct"]) if five else None,
            "week": float(week["pct"]) if five and "pct" in week else None,
            "reset_in": _dur(float(five["reset"]) - time.time()) if five and float(five.get("reset") or 0) > time.time() else "",
            "context": (used / (200_000 if used <= 200_000 else 1_000_000)) if used else None,
            "tokens_text": _n(total), "cost": round(state.cost(), 2),
            "models": [{"name": name(m), "tokens_text": _n(v["total"]), "share": v["total"] / total}
                       for m, v in sorted(models, key=lambda x: -x[1]["total"]) if total and v["total"]],
        },
        "size": ({**facts["size"], "run_lines": facts["run"]["lines"] if facts["run"] else None,
                  "run_files": facts["run"]["files"] if facts["run"] else None} if facts["size"] else None),
        "files": facts["files"],
        "health": {"git": git, "checks": checks,
                   "words": " ".join(x for x in ("The checks fail on main." if checks == "Red" else "",
                                                 "Git has no connection." if git == "Off" else "",
                                                 "The push to GitHub fails." if git == "Push!" else "") if x)},
        "next": [tuple(re.split(r"\s{2,}", tip, maxsplit=1)) if re.search(r"\s{2,}", tip) else (tip, "")
                 for tip in next_steps(root, live)],
        "line": status_line(cfg, plan, state, run),
    }
