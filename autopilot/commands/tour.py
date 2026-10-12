"""W2: `ap tour` replays a recorded run in the watch window. No login, no key, no network, nothing written."""
from __future__ import annotations

import json
import shutil
import sys
import time
from importlib import resources

from ..dash_term import MIN_COLS, MIN_ROWS, frame
from ..plain import colors_on

INSTALL = ("Install: uv tool install dev-autopilot", "Start: ap")


def _text(name: str) -> str:
    return resources.files("autopilot").joinpath("templates", "tour", name).read_text(encoding="utf-8")


def load_events() -> list[dict]:
    return [json.loads(ln) for ln in _text("events.jsonl").splitlines() if ln.strip()]


def snapshot(events: list[dict], t: float) -> dict:
    """The dashboard data of the recorded run at second t: the same shape `dashboard_data` returns."""
    tasks, live, phases, cost, last, running = [], [], [], 0.0, "", ""
    by_id: dict = {}
    for e in events:
        if e["kind"] == "task_start" and e["task_id"] not in by_id:
            n = len(tasks) + 1
            by_id[e["task_id"]] = {"n": str(n), "id": e["task_id"], "title": e["message"].partition(" ")[2],
                                   "status": "pending", "time": "", "detail": "", "risk": "", "tries": "", "start": e["t"]}
            tasks.append(by_id[e["task_id"]])
    for e in events:
        if e["t"] > t:
            break
        k, tid, msg = e["kind"], e["task_id"], e["message"]
        cost += float(e["usage"].get("cost_usd") or 0) if k == "task_done" else 0
        row = by_id.get(tid)
        if k == "task_start":
            row["status"], running = "running", tid
        elif k == "session" and row:
            row["detail"] = msg.partition(" on ")[2].partition(" ")[0] or msg
            row["risk"] = msg.rpartition("risk ")[2]
            row["tries"] = msg.partition("attempt ")[2].partition(")")[0]
        elif k == "task_done" and row:
            row["status"], row["time"] = "done", f"{int(e['t'] - row['start'])}s"
        elif k == "phase_start":
            phases.append({"id": msg.removeprefix("Phase ").split()[0], "status": "running", "done": 0, "total": 0})
        elif k == "phase_done" and phases:
            phases[-1]["status"] = "done"
        if k in ("task_done", "criterion", "gate", "files", "feature", "run_end", "phase_done", "task_start"):
            live.append({"at": f"{int(e['t']) // 60:02d}:{int(e['t']) % 60:02d}", "text": msg,
                         "kind": "good" if k in ("task_done", "run_end", "feature") else "step", "took": ""})
        last = k
    done = sum(r["status"] == "done" for r in tasks)
    for ph in phases:
        mine = [r for r in tasks if r["id"].startswith(ph["id"] + "-")]
        ph["total"], ph["done"] = len(mine), sum(r["status"] == "done" for r in mine)
    ended = last == "run_end"
    now = by_id.get(running) if running and not ended else None
    return {"project": {"name": "autopilot (recorded run)", "status": "finished" if ended else "running",
                        "state": "Done" if ended else "Work", "elapsed": f"{int(t)}s",
                        "now": {"n": now["n"], "title": now["title"]} if now else None},
            "progress": {"total": len(tasks), "done": done, "active": 0 if ended or not now else int(now["n"]),
                         "blocked": 0},
            "phases": phases, "tasks": [{k: v for k, v in r.items() if k != "start"} for r in tasks],
            "live": live[-40:], "usage": {"cost": cost}}


def cmd_tour(args) -> int:
    events = load_events()
    end = events[-1]["t"]
    color, out = colors_on(sys.stdout), sys.stdout
    size = shutil.get_terminal_size((MIN_COLS + 20, MIN_ROWS + 6))
    cols, rows = max(size.columns, MIN_COLS), max(size.lines, MIN_ROWS)
    if not args.once and out.isatty():
        speed = max(float(args.speed), 0.1)
        out.write("\x1b[?1049h\x1b[?25l\x1b[?7l")
        try:
            start = time.monotonic()
            while (t := (time.monotonic() - start) * speed) < end:
                out.write("\x1b[H" + "\n".join(frame(snapshot(events, t), cols, rows, color)))
                out.flush()
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            out.write("\x1b[?7h\x1b[?25h\x1b[?1049l")
    print("\n".join(frame(snapshot(events, end), cols, rows, color)))
    print()
    print(_text("PROOF.md").rstrip())
    print()
    print("\n".join(INSTALL))
    return 0
