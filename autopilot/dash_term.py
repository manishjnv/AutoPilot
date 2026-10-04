"""A full-window terminal dashboard as a list of text lines. frame() is a pure function of the data dict made by
dashboard.dashboard_data: no I/O, no clock, no terminal query. Every returned line has exactly `cols` visible cells
(every printed character counts as one cell: wide characters in data become '?'). Cutting and padding happen on plain
text first; colour wraps whole cells afterwards, so colour never changes a width."""
from __future__ import annotations

import textwrap
import unicodedata

from .plain import paint

MIN_COLS, MIN_ROWS = 100, 24
LEFT_W, RIGHT_W = 36, 30
STATUS = {"done": ("✓", "Complete", "green"), "running": ("▶", "In progress", "cyan"),
          "blocked": ("✗", "Blocked", "red"), "pending": ("○", "Pending", "dim")}
KIND = {"heading": "bold", "goal": "dim", "good": "green", "bad": "red", "note": "yellow"}


def clean(x) -> str:
    """A data value as safe one-cell-wide text: no control characters, no wide or combining characters."""
    return "".join("?" if unicodedata.east_asian_width(c) in "WF" or unicodedata.combining(c) else c
                   for c in str(x if x is not None else "") if c.isprintable())


def cut(s: str, w: int) -> str:
    return s if len(s) <= w else s[:w - 3] + "..." if w >= 3 else s[:max(w, 0)]


def fit(s: str, w: int) -> str:
    """Plain text cut to w cells ('...' at the end) and padded to w."""
    return cut(s, w).ljust(max(w, 0))


def segs(line) -> list:
    """A line is a str or a list of str / (text, style) pieces."""
    return [(line, None)] if isinstance(line, str) else [(p, None) if isinstance(p, str) else p for p in line]


def fit_segs(line, w: int) -> list:
    parts = segs(line)
    if sum(len(t) for t, _ in parts) > w:
        keep, out = max(w - 3, 0), []
        for t, st in parts:
            if keep <= 0:
                break
            out.append((t[:keep], st))
            keep -= len(t[:keep])
        out.append(("..."[:w], parts[-1][1]))
        parts = out
    return parts + [(" " * (w - sum(len(t) for t, _ in parts)), None)]


def render(parts, color: bool) -> str:
    return "".join(paint(t, st, color) if st else t for t, st in parts)


def box(title: str, lines: list, w: int, h: int, color: bool) -> list[str]:
    """A box of exactly w cells by h rows; lines that do not fit are cut off at the bottom."""
    title = cut(title, w - 6)
    top = [("┌─ ", "dim"), (title, "bold"), (" " + "─" * (w - 5 - len(title)) + "┐", "dim")]
    out = [render(top, color)]
    for line in (list(lines) + [""] * h)[:h - 2]:
        out.append(render([("│ ", "dim"), *fit_segs(line, w - 4), (" │", "dim")], color))
    return out + [render([("└" + "─" * (w - 2) + "┘", "dim")], color)]


def num(x):
    """A share clamped to 0..1, or None."""
    try:
        return min(max(float(x), 0.0), 1.0) if x is not None else None
    except (TypeError, ValueError):
        return None


def count(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def bar(share, n: int = 10) -> str:
    s = num(share) or 0.0
    return "█" * round(s * n) + "░" * (n - round(s * n)) + f" {round(s * 100)}%"


def alert(n: int, style: str):
    return str(n), (style if n > 0 else None)


def left_panel(d: dict, w: int, h: int, color: bool) -> list[str]:
    p, pr, u = d["project"], d["progress"], d["usage"]
    rows = []

    def row(label, value, style=None):
        if value != "":
            rows.append([(f"{label:<9}: ", "dim"), (value, style)])
    for label, key in (("Project", "name"), ("Branch", "branch"), ("Commit", "commit"), ("Model", "model"),
                       ("Run", "run_id"), ("Start", "started"), ("Status", "status")):
        row(label, p[key])
    wrapped = textwrap.wrap(p["state_words"], w - 6)
    if len(wrapped) > 2:
        wrapped = [wrapped[0], wrapped[1] + "..."]
    rows += [[("  " + x, "dim")] for x in wrapped]
    row("Elapsed", p["elapsed"])
    row("Left", p["eta"])
    rows.append("")
    if count(pr.get("total")):
        row("Tasks", f"{count(pr.get('done'))}/{count(pr.get('total'))}", "count")
    row("Phases", f"{count(pr.get('phases_done'))}/{count(pr.get('phases_total'))}", "count")
    rows.append(bar(d["share"]))
    for label, key, style in (("Blocked", "blocked", "red"), ("Questions", "questions", "yellow"),
                              ("Warnings", "warnings", "yellow")):
        row(label, *alert(count(pr.get(key)), style))
    rows.append("")
    row("Tokens", u["tokens_text"])
    row("Cost", u["cost_text"])
    if num(u.get("context")) is not None:
        row("Context", bar(u["context"]))
    return box("Project", rows, w, h, color)


def right_column(d: dict, w: int, h: int, color: bool) -> list[str]:
    pr, u, f = d["progress"], d["usage"], d["files"]
    prog = [[(f"{round(d['share'] * 100)}%", "bold")], bar(d["share"]),
            [(f"{count(pr.get('done'))} of {count(pr.get('total'))}", "count"), " tasks"],
            [(f"{count(pr.get('phases_done'))} of {count(pr.get('phases_total'))}", "count"), " phases"]]
    if d["project"]["eta"]:
        prog.append(f"Left {d['project']['eta']}")
    use = [f"{label:<8}{bar(u.get(key))}" for label, key in (("5h", "five"), ("Week", "week"), ("Context", "context"))
           if num(u.get(key)) is not None]
    if u["tokens_text"]:
        use.append(f"Tokens  {u['tokens_text']}")
    use += [f"{m['name']:<9}{m['tokens_text']:>6} {round((num(m['share']) or 0) * 100):>3}%" for m in u["models"]]
    if u["cost_text"]:
        use.append(f"Cost    {u['cost_text']}")
    issues = [[(f"{label:<10}", "dim"), alert(count(pr.get(key)), style)]
              for label, key, style in (("Blocked", "blocked", "red"), ("Questions", "questions", "yellow"),
                                        ("Warnings", "warnings", "yellow"))]
    issues += [[(f"{k:<10}", "dim"), (v, "green" if v == "OK" else "yellow")] for k, v in d["health"].items() if v]
    boxes = [("Progress", prog), ("Usage", use)]
    if f is not None:
        boxes.append(("Files", [[(f"{k:<10}", "dim"), str(count(f.get(k.lower())))]
                                for k in ("Added", "Modified", "Deleted")]))
    boxes.append(("Issues", issues))
    out, left = [], h
    for i, (title, lines) in enumerate(boxes):
        if left < 3:
            break
        need = min(len(lines) + 2, left)
        if i == len(boxes) - 1 or left - need < 3:  # the last box that fits takes the spare rows
            need = left
        out += box(title, lines, w, need, color)
        left -= need
    return out + [" " * w] * left


def tasks_panel(d: dict, w: int, h: int, color: bool) -> list[str]:
    iw, tasks = w - 4, d["tasks"]
    detail = iw - 44 >= 14
    tw = iw - 25 - (19 if detail else 0)

    def line(n, title, status, time, det, style=None, sstyle=None):
        parts = [(n.rjust(3), style), (" ", None), (fit(title, tw), style), (" ", None), (fit(status, 13), sstyle),
                 (" ", None), (fit(time, 6), style)]
        return parts + ([(" ", None), (fit(det, 18), style)] if detail else [])
    rows = [line("#", "Task", "Status", "Time", "Detail", "dim", "dim")]
    room = h - 3
    focus = next((i for i, t in enumerate(tasks) if t["status"] == "running"),
                 next((i for i, t in enumerate(tasks) if t["status"] != "done"), len(tasks) - 1))
    start = min(max(focus - room // 2, 0), max(len(tasks) - room, 0))
    for t in tasks[start:start + room]:
        sym, word, st = STATUS.get(t["status"], ("○", t["status"] or "Pending", "dim"))
        rows.append(line(t["n"], t["title"], f"{sym} {word}", t["time"], t["detail"],
                         "bold" if t["status"] == "running" else None, st))
    return box("Tasks", rows, w, h, color)


def live_panel(d: dict, w: int, h: int, color: bool) -> list[str]:
    rows = []
    for e in d["live"][-(h - 2):]:
        if e["kind"] == "blank":
            rows.append("")
        elif e["kind"] in ("heading", "goal"):
            rows.append([(e["text"], KIND[e["kind"]])])
        else:
            rows.append([(fit(e["at"], 5), "dim"), "  ", (e["text"], KIND.get(e["kind"]))])
    return box("Live output", rows or [[("No output yet.", "dim")]], w, h, color)


def status_bar(d: dict, cols: int, color: bool) -> str:
    p, pr, u = d["project"], d["progress"], d["usage"]
    total = count(pr.get("total"))
    parts = [(p["name"], "bold"), (p["branch"], None), (p["commit"], None),
             (f"Task {count(pr.get('done'))}/{total}" if total else "", "count"), (bar(d["share"]) if pr else "", None),
             (f"Left {p['eta']}" if p["eta"] else "", None), (f"Blocked {count(pr.get('blocked'))}" if pr else "", None),
             (f"Tok {u['tokens_text']}" if u["tokens_text"] else "", None), (u["cost_text"], None)]
    line = [(" ", None)]
    for t, st in (x for x in parts if x[0]):
        line += ([(" │ ", "dim")] if len(line) > 1 else []) + [(t, st)]
    return render(fit_segs(line, cols), color)


def normalize(data) -> dict:
    """Every key present, every string clean, odd types replaced: the panels need no checks."""
    data = data if isinstance(data, dict) else {}

    def sub(k):
        return data[k] if isinstance(data.get(k), dict) else {}

    def rows(k, keys):
        return [{key: clean(r.get(key)) for key in keys} for r in data.get(k) or [] if isinstance(r, dict)]
    p, u, pr = sub("project"), sub("usage"), sub("progress")
    try:
        cost_text = f"${float(u.get('cost')):.2f}" if u.get("cost") else ""
    except (TypeError, ValueError):
        cost_text = ""
    total = count(pr.get("total"))
    pct = pr.get("pct")
    share = pct / 100 if isinstance(pct, (int, float)) else count(pr.get("done")) / total if total else 0
    models = [m for m in u.get("models") or [] if isinstance(m, dict)]
    return {
        "project": {k: clean(p.get(k)) for k in ("name", "branch", "commit", "model", "run_id", "started", "status",
                                                 "state_words", "elapsed", "eta")},
        "progress": pr, "share": num(share) or 0.0,
        "tasks": rows("tasks", ("n", "title", "status", "time", "detail")),
        "live": rows("live", ("at", "text", "kind")),
        "usage": {**u, "tokens_text": clean(u.get("tokens_text")), "cost_text": cost_text,
                  "models": [{"name": clean(m.get("name"))[:9], "tokens_text": clean(m.get("tokens_text")),
                              "share": m.get("share")} for m in models]},
        "files": data["files"] if isinstance(data.get("files"), dict) else None,
        "health": {"Git": clean(sub("health").get("git")), "Checks": clean(sub("health").get("checks"))},
    }


def frame(data: dict, cols: int, rows: int, color: bool = False) -> list[str]:
    if cols < MIN_COLS or rows < MIN_ROWS:
        raise ValueError(f"the window must be at least {MIN_COLS}x{MIN_ROWS}")
    d = normalize(data)
    body = rows - 1
    top = max(8, round(body * 0.45))
    mid = tasks_panel(d, cols - LEFT_W - RIGHT_W, top, color) + live_panel(d, cols - LEFT_W - RIGHT_W, body - top, color)
    return [a + b + c for a, b, c in zip(left_panel(d, LEFT_W, body, color), mid,
                                         right_column(d, RIGHT_W, body, color))] + [status_bar(d, cols, color)]
