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
STATUS = {"done": ("✓", "Complete", "green"), "running": ("▶", "In progress", "green"),
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
    """Paint whole cells; a style may be several names ('bold yellow')."""
    out = []
    for t, st in parts:
        for name in (st or "").split() if color else ():
            t = paint(t, name, True)
        out.append(t)
    return "".join(out)


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
    k = n if s >= 1 else min(n - 1, int(s * n))  # a full bar only at 100%
    return "█" * k + "░" * (n - k) + f" {round(s * 100)}%"


def level_bar(share, n: int = 10) -> list:
    """The same bar as segments; the filled blocks are green below 70%, yellow below 90%, red above."""
    s = num(share) or 0.0
    k, pct = max(round(s * n), 1 if s > 0 else 0), round(s * 100)  # a small value still shows one block
    return [("█" * k, "green" if pct < 70 else "yellow" if pct < 90 else "red"), ("░" * (n - k) + f" {pct}%", None)]


def alert(n: int, style: str):
    return str(n), (style if n > 0 else "dim")


def wrap2(text: str, w: int) -> list[str]:
    """At most two lines; the second ends with '...' when there is more."""
    lines = textwrap.wrap(text, max(w, 1))
    return lines if len(lines) <= 2 else [lines[0], lines[1] + "..."]


TONE = {"good": "green", "wait": "yellow", "bad": "red"}
TRY = {1: None, 2: "yellow"}


def left_panel(d: dict, w: int, h: int, color: bool) -> list[str]:
    p, pr, ny, now, size = d["project"], d["progress"], d["needs_you"], d["now"], d["size"]

    def row(label, value, style=None):
        return [[f"{label:<9}: ", (value, style)]] if value != "" else []

    def text(t, style=None, indent=""):
        return [[(indent + x, style)] for x in wrap2(t, w - 4 - len(indent))]

    def rule(title, style="bold"):
        """The first line of a titled group: the title in a line of the full inner width."""
        return [("── ", "dim"), (title, style), (" " + "─" * max(w - 8 - len(title), 0), "dim")]
    status = row("Project", p["name"]) + row("Branch", p["branch"]) + row("Status", p["status"], TONE.get(p["tone"]))
    status += text(p["state_words"], None, "  ")
    if p["stale_min"] > 0:
        status.append([(f"No change for {p['stale_min']} min.", {"warn": "yellow", "bad": "red"}.get(p["stale"], "dim"))])
    groups = [status + row("Started", p["started"][:16]) + row("Elapsed", p["elapsed"]) + row("Left", p["eta"])]
    if ny:
        n = max(count(pr.get("questions")), len(ny))
        groups.append([rule("! Questions for you", "bold yellow"),
                       f"{n} questions wait for you." if n > 1 else "1 question waits for you.",
                       *text(ny[0]["title"]), [("Run: ", None), ("ap answer", "cyan")]])
    if now and (now["title"] or now["model"] or count(now["n"])):
        n, total, tries = count(now["n"]), count(pr.get("total")), count(now["attempt"])
        g = [rule("Now")]
        if n:
            g.append([("Task ", None), (f"{n} of {total}" if total else str(n), "count")])
        g += text(now["title"])
        if n and tries:
            g.append([(f"Try {tries}" + (f" of {now['max_attempts']}" if count(now["max_attempts"]) else ""),
                       TRY.get(tries, "red"))])
        groups.append(g + (row("Time", now["time"]) if n else []) + row("Model", now["model"]))
    if p["next"]:
        groups.append([rule("Next"), *text(p["next"])])
    if size:
        g = [rule("Size")]
        if size.get("code") is not None:
            g += row("Code", f"{count(size['code']):,} lines")
        if size.get("tests") is not None:
            lines_, cases = f"{count(size['tests']):,} lines", f"{count(size.get('test_count')):,} tests"
            fits = len(lines_) + len(cases) + 13 <= w - 4
            g += row("Tests", f"{lines_}, {cases}" if fits else lines_) + ([] if fits else [" " * 11 + cases])
        if size.get("docs") is not None:
            g += row("Docs", f"{count(size['docs']):,} lines")
        if size.get("run_lines") is not None:
            g += row("This run", f"+{count(size['run_lines']):,} lines, {count(size.get('run_files'))} files")
        groups.append(g)
    if p["last_commit"]:
        groups.append([rule("Last commit"), *text(p["last_commit"]),
                       *([[(f"{p['last_commit_age']} ago", "dim")]] if p["last_commit_age"] else [])])
    ph = d["phases"]
    if ph:  # five lines at most, around the active phase; the last group, so it is cut first
        at = next((i for i, x in enumerate(ph) if x["status"] == "running"),
                  next((i for i, x in enumerate(ph) if x["status"] != "done"), len(ph) - 1))
        start = min(max(at - 2, 0), max(len(ph) - 5, 0))
        g = [rule("Phases")]
        for x in ph[start:start + 5]:
            sym, _, st = STATUS.get(x["status"], STATUS["pending"])
            g.append([(sym, st), f" {x['id']} ", (f"{x['done']}/{x['total']}", "count" if x["done"] else "dim")])
        groups.append(g)
    rows = []
    for g in groups:
        if rows and len(rows) + len(g) > h - 2:
            continue  # a group that does not fit does not stop the smaller groups after it
        rows += g
    return box("Project", rows, w, h, color)


def cnt(n: int, style=None):
    """A number: its style when above 0, dim at 0."""
    return str(n), (style if n > 0 else "dim")


def right_column(d: dict, w: int, h: int, color: bool) -> list[str]:
    pr, u, f, why = d["progress"], d["usage"], d["files"], d["blocked_why"]
    prog = [bar(d["share"]),
            [cnt(count(pr.get("done")), "count"), " done · ", cnt(count(pr.get("working")), "count"), " working"],
            [alert(count(pr.get("blocked")), "red"), " blocked · ", cnt(count(pr.get("waiting")), "count"), " waiting"],
            [(f"{count(pr.get('phases_done'))} of {count(pr.get('phases_total'))}", "count"), " phases"]]
    use = []
    for label, key in (("5h", "five"), ("Week", "week"), ("Context", "context")):
        if num(u.get(key)) is not None:
            use.append([f"{label:<8}", *level_bar(u.get(key))])
        if key == "five" and u["reset_in"]:
            use.append([(f"Resets in {u['reset_in']}", "dim")])
    if u["tokens_text"]:
        use.append(f"Tokens  {u['tokens_text']}")
    use += [f"{m['name']:<9}{m['tokens_text']:>6} {round((num(m['share']) or 0) * 100):>3}%" for m in u["models"]]
    if u["cost_text"]:
        use.append(f"Cost    {u['cost_text']}")
    issues = [["Blocked   ", alert(count(pr.get("blocked")), "red")]]
    if why:
        issues += wrap2(f"{why['id']}: {why['why']}", w - 4)
    issues += [[f"{label:<10}", alert(count(pr.get(key)), "yellow")]
               for label, key in (("Questions", "questions"), ("Warnings", "warnings"))]
    issues += ["  " + x for x in wrap2(" ".join(pr["warned"]), w - 6)]  # the tasks that have a warning
    issues += [[f"{k:<10}", (v, "green" if v == "OK" else "red")] for k, v in d["health"].items() if k != "words" and v]
    issues += [[(x, "red")] for x in wrap2(d["health"]["words"], w - 4)]
    boxes = [("Progress", prog), ("Usage", use)]
    if f is not None:
        boxes.append(("Files", [["Added     ", cnt(count(f.get("added")), "green")],
                                ["Modified  ", cnt(count(f.get("modified")))],
                                ["Deleted   ", cnt(count(f.get("deleted")), "red")]]))
    boxes.append(("Issues", issues))
    tip = d["next"][0][0] if d["next"] else ""
    out, left = [], h
    for i, (title, lines) in enumerate(boxes):
        if left < 3:
            break
        need = min(len(lines) + 2, left)
        if i == len(boxes) - 1 or left - need < 3:  # the last box that fits takes the spare rows
            need = left
        if title == "Issues" and tip and len(lines) < need - 2:  # the next step in the last row, only with a free row
            lines = lines + [""] * (need - 3 - len(lines)) + [[("Run: ", None), (tip, "cyan")]]
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
    total, active = count(pr.get("total")), count(pr.get("active"))
    task = f"Task {active}/{total}" if active > 0 else f"Done {count(pr.get('done'))}/{total}"
    blocked = count(pr.get("blocked"))
    parts = [(p["name"], "bold"), (p["branch"], None), (task if total else "", "count"),
             (bar(d["share"]) if pr else "", None), (f"Left {p['eta']}" if p["eta"] else "", None),
             (f"Blocked {blocked}" if pr else "", "red" if blocked > 0 else "dim"),
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

    def listed(k):
        return data[k] if isinstance(data.get(k), (list, tuple)) else []

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
    def one(x, keys):
        return {k: clean(x.get(k)) for k in keys} if isinstance(x, dict) else None
    now = one(sub("project").get("now"), ("n", "title", "attempt", "max_attempts", "time", "model"))
    size = data.get("size") if isinstance(data.get("size"), dict) else None
    return {
        "project": {**{k: clean(p.get(k)) for k in ("name", "branch", "model", "started", "status", "tone", "stale",
                                                    "state_words", "elapsed", "eta", "next", "last_commit",
                                                    "last_commit_age")},
                    "stale_min": count(p.get("stale_min"))},
        "progress": {**pr, "warned": [clean(x) for x in (pr.get("warned") if isinstance(pr.get("warned"), list) else [])][:6]},
        "share": num(share) or 0.0, "now": now, "size": size,
        "phases": [{"id": clean(r.get("id")), "status": clean(r.get("status")), "done": count(r.get("done")),
                    "total": count(r.get("total"))} for r in listed("phases") if isinstance(r, dict)],
        "next": [(clean(t[0]), clean(t[1]) if len(t) > 1 else "") for t in listed("next")
                 if isinstance(t, (list, tuple)) and t],
        "needs_you": [x for x in (one(r, ("id", "title")) for r in data.get("needs_you") or []) if x],
        "blocked_why": one(data.get("blocked_why"), ("id", "why")),
        "tasks": rows("tasks", ("n", "id", "title", "status", "time", "detail")),
        "live": rows("live", ("at", "text", "kind")),
        "usage": {**u, "tokens_text": clean(u.get("tokens_text")), "cost_text": cost_text,
                  "reset_in": clean(u.get("reset_in")),
                  "models": [{"name": clean(m.get("name"))[:9], "tokens_text": clean(m.get("tokens_text")),
                              "share": m.get("share")} for m in models]},
        "files": data["files"] if isinstance(data.get("files"), dict) else None,
        "health": {"Git": clean(sub("health").get("git")), "Checks": clean(sub("health").get("checks")),
                   "words": clean(sub("health").get("words"))},
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
