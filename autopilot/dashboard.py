"""J9: the data of the dashboard, one plain dict for both views (the browser page in dash_web.py and the terminal
window in dash_term.py). It only reads. Every value is a str, int, float, bool, None, list or dict, so a view never
needs the plan, the state or the log."""
from __future__ import annotations

import datetime as dt
import re
import subprocess

from .plain import SimpleView, ending
from .report import (MODEL_NAMES, STATE_WORDS, _n, _runtime, _shares, next_steps, open_window, status_line,
                     warned_tasks)


def _git(root, *args) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=5)  # noqa: S603, S607
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _span(start, end) -> str:
    """'4m' between two ISO times, '' when one is missing or the clock went back."""
    try:
        secs = (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return ""
    return "" if secs < 0 else f"{int(secs // 3600)}h{int(secs % 3600 // 60):02d}m" if secs >= 3600 else f"{max(1, round(secs / 60))}m"


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
        return {"n": i + 1, "id": t.id, "title": t.title, "phase": t.phase_id, "status": st,
                "time": (_span(r["started_at"], r["finished_at"]) if st == "done" else
                         _span(r["started_at"], now) if st == "running" else "") if r else "",
                "detail": " · ".join(x for x in (name(r["model"]) if r else "",
                                                 f"{tries} attempts" if tries > 1 else "") if x)}

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
    files = None
    if run.get("started_at"):  # what the commits of this run changed. ponytail: one git call for each refresh
        marks = re.findall(r"^([AMD])\t", _git(root, "log", f"--since={run['started_at']}", "--name-status",
                                              "--pretty=format:"), re.M)
        files = {"added": marks.count("A"), "modified": marks.count("M"), "deleted": marks.count("D")}
    return {
        "project": {
            "name": str(cfg.get("name", root.name)), "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "commit": _git(root, "rev-parse", "--short", "HEAD"), "model": name(run.get("model")) if live else "",
            "run_id": str(run.get("run_id") or ""), "started": str(run.get("started_at") or "").replace("T", " "),
            "status": "running" if live else "finished" if finished else "idle",
            "state_words": (STATE_WORDS.get(str(run.get("state") or ""), "Works.") if live else
                            ending(run.get("outcome")) if finished else "No build is active."),
            "elapsed": _runtime(run.get("started_at")) if live else "", "eta": eta,
            "attempt": int(run.get("attempt") or 1) if live else 0,
        },
        "progress": {
            "done": done, "total": len(tasks), "pct": 100 * done // len(tasks) if tasks else 0,
            "phases_done": sum(1 for p in plan.phases if p.tasks and all(status.get(t.id) == "done" for t in p.tasks)),
            "phases_total": len(plan.phases), "blocked": blocked, "questions": len(state.decisions("OPEN")),
            "warnings": sum(len(warned_tasks(cfg, p)) for p in plan.phases),
        },
        "tasks": [one(i, t) for i, t in enumerate(tasks)],
        "live": live_rows(root, plan),
        "usage": {
            "five": float(five["pct"]) if five else None,
            "week": float(week["pct"]) if five and "pct" in week else None,
            "context": (used / (200_000 if used <= 200_000 else 1_000_000)) if used else None,
            "tokens_text": _n(total), "cost": round(state.cost(), 2),
            "models": [{"name": name(m), "tokens_text": _n(v["total"]), "share": v["total"] / total}
                       for m, v in sorted(models, key=lambda x: -x[1]["total"]) if total and v["total"]],
        },
        "files": files,
        "health": {"git": str(run.get("git") or "") if live else "", "checks": str(run.get("build") or "") if live else ""},
        "next": [tuple(re.split(r"\s{2,}", tip, maxsplit=1)) if re.search(r"\s{2,}", tip) else (tip, "")
                 for tip in next_steps(root, live)],
        "line": status_line(cfg, plan, state, run),
    }
