"""A full-window terminal dashboard as a list of text lines. frame() is a pure function of the data dict made by
dashboard.dashboard_data: no I/O, no clock, no terminal query. Every returned line has exactly `cols` visible cells
(every printed character counts as one cell: wide characters in data become '?'). Cutting and padding happen on plain
text first; colour wraps whole cells afterwards, so colour never changes a width."""
from __future__ import annotations

import textwrap
import unicodedata

from . import dash_card, dash_live
from .plain import paint

MIN_COLS, MIN_ROWS = 100, 24
LEFT_W, RIGHT_W = 36, 30
STATUS = {"done": ("✓", "Complete", "green"), "running": ("▶", "In progress", "cyan"),
          "blocked": ("✗", "Blocked", "red"), "pending": ("○", "Pending", "dim")}
KIND = {"heading": "value", "goal": "dim", "good": "green", "bad": "red", "note": "yellow", "wait": "dim"}
# J13/9: one colour, one meaning, on every screen. "bold" is only the Now headline; "value" is bright white, not bold.
COLOUR_MEANING = {"green": "done or ok", "cyan": "running now", "yellow": "warning", "red": "blocked or failed",
                  "magenta": "cost and usage", "blue": "model name", "dim": "label, border, pending or zero",
                  "value": "a value the eye lands on", "bold": "the one headline",
                  "active": "the task in work: filled background, bold"}
# J13/17: every (colour, use) pair of the screen. A colour has one meaning; a plain fact stays white (no colour).
_USES = {
    "green": ["Login Pro/Max", "Status Complete", "Progress bar fill", "Files Added", "Lines +", "Git and Checks OK",
              "Size This run", "Phase ✓", "Live: the task is complete"],
    "cyan": ["Status In progress", "Phase ▶", "Live: test run", "State word", "Spinner turning"],
    "yellow": ["Login not checked", "Time over 2x the median", "Risk high", "Tries 2 or more", "Try on the last try",
               "Questions", "Warnings", "Retries", "Last commit age when stalled", "Usage bar over 75%",
               "Data stale", "No change for minutes", "Spinner no change", "Live: note", "Live: a wait over 60 s (dim)"],
    "red": ["Login failed", "Status Blocked", "Risk crit", "Error text", "Blocked", "Files Deleted", "Lines -",
            "Git and Checks fail", "Usage bar over 90%", "Phase ✗", "Live: an error line", "Spinner stopped"],
    "magenta": ["Resets", "Usage bars", "Cost"],
    "blue": ["Model", "Detail model", "Usage model names"],
    "dim": ["Labels and borders", "Status Pending", "Phase ○", "Risk low", "Waiting", "Error empty", "Zero counts",
            "Live: step verbs"],
    "value": ["Counts the eye lands on", "Next step"],
    "bold": ["Now headline"],
    "active": ["Running task row", "Now card label"],
}
COLOUR_USES = [(c, COLOUR_MEANING[c], u) for c, uses in _USES.items() for u in uses]
RISK = {"critical": ("crit", "red"), "high": ("high", "yellow"), "medium": ("med", None), "low": ("low", "dim")}
SPIN_STYLE = {"run": "cyan", "stale": "yellow", "stopped": "red"}


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


MONO = {"dim": "dim", "bold": "bold", "value": "bold", "active": "bold"}  # W18a: NO_COLOR draws with bold and dim only


def render(parts, color) -> str:
    """Paint whole cells; a style may be several names ('bold yellow'). color: True, False or 'mono' (bold and dim)."""
    out = []
    for t, st in parts:
        for name in (st or "").split() if color else ():
            name = MONO.get(name) if color == "mono" else name
            t = paint(t, name, True) if name else t
        out.append(t)
    return "".join(out)


def box(title: str, lines: list, w: int, h: int, color: bool, note=None) -> list[str]:
    """A box of exactly w cells by h rows; lines that do not fit are cut off at the bottom. note = (text, style)
    sits at the right end of the title bar when it fits."""
    title = cut(title, w - 6)
    if note and note[0] and w - 7 - len(title) - len(note[0]) >= 1:
        top = [("┌─ ", "dim"), (title, None), (" " + "─" * (w - 7 - len(title) - len(note[0])) + " ", "dim"),
               note, (" ┐", "dim")]
    else:
        top = [("┌─ ", "dim"), (title, None), (" " + "─" * (w - 5 - len(title)) + "┐", "dim")]
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
    """A usage bar as segments; the filled blocks are magenta, yellow over 75%, red over 90%."""
    s = num(share) or 0.0
    k, pct = max(round(s * n), 1 if s > 0 else 0), round(s * 100)  # a small value still shows one block
    return [("█" * k, "red" if pct > 90 else "yellow" if pct > 75 else "magenta"), ("░" * (n - k) + f" {pct}%", None)]


def bar_segs(share, n: int = 10) -> list:
    """The progress bar (same text as bar()) as segments; the fill is green."""
    t = bar(share, n)
    k = t.count("█")
    return [(t[:k], "green"), (t[k:], None)]


def alert(n: int, style: str):
    return str(n), (style if n > 0 else "dim")


def wrap2(text: str, w: int) -> list[str]:
    """At most two lines; the second ends with '...' when there is more."""
    lines = textwrap.wrap(text, max(w, 1))
    return lines if len(lines) <= 2 else [lines[0], lines[1] + "..."]


TONE = {"good": "green", "wait": "yellow", "bad": "red"}


def try_style(tries: int, last: int):
    """White on the first tries, yellow on the last one."""
    return "yellow" if last and tries >= last else None


def login_cell(v: str):
    """('not checked', yellow) until the check ran; green for a paid plan; red when the check failed."""
    if v in ("", "—", "not checked"):
        return "not checked", "yellow"
    return v, "green" if v.lower().startswith(("pro", "max")) else "red"


def spin_cell(d: dict):
    """The spinner text and its colour, or None."""
    sp = d.get("spin")
    return (sp["text"], SPIN_STYLE[sp["kind"]]) if sp and sp["text"] and sp["kind"] in SPIN_STYLE else None


def ticking(sec) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s"


def asof_note(d: dict, first: bool, own: bool = False):
    """J13/11: the note in a panel title. A stopped run shows 'stopped 12:50' on every panel; a live run shows the age
    of the data in the first panel only, yellow with 'stale' over 30 s; no source shows a dash. No key: no note."""
    a = d["asof"]
    if a is None:
        return None
    if a["stopped"]:
        return (f"stopped {a['stopped']}", "dim")
    if not first or d.get("card") and not own:  # W18b: with a card the data age lives at the right end of its border
        return None
    if a["age"] is None:
        return ("data —", "dim")
    age = f"{a['age']}s" if a["age"] < 60 else f"{a['age'] // 60}m"
    return (f"data {age} old stale", "yellow") if a["age"] > 30 else (f"data {age} old", "dim")


def left_panel(d: dict, w: int, h: int, color: bool, narrow: bool = False) -> list[str]:
    p, pr, ny, now, size = d["project"], d["progress"], d["needs_you"], d["now"], d["size"]

    def row(label, value, style=None):
        return [[f"{label:<9}: ", (value, style)]] if value != "" else []

    def text(t, style=None, indent=""):
        return [[(indent + x, style)] for x in wrap2(t, w - 4 - len(indent))]

    def rule(title, style=None, spin=None):
        """The first line of a titled group: the title in a line of the full inner width. spin = (text, style) before it."""
        pre = [(spin[0], spin[1]), (" ", None)] if spin else []
        return [("── ", "dim"), *pre, (title, style), (" " + "─" * max(w - 8 - len(title) - (len(spin[0]) + 1 if spin else 0), 0), "dim")]
    status = row("Project", p["name"]) + row("Branch", p["branch"])  # the state lives in the title and the bar
    if p["stale_min"] > 0:
        status.append([(f"No change for {p['stale_min']} min.", {"warn": "yellow", "bad": "red"}.get(p["stale"], "dim"))])
    sp0, since = d.get("spin"), p.get("since_ts")
    elapsed = ticking(sp0["clock"] - since) if sp0 and since else p["elapsed"]  # W18a: ticks on the window clock
    groups = [status + row("Started", p["started"][:16]) + row("Elapsed", elapsed)]
    if ny:
        n = max(count(pr.get("questions")), len(ny))
        groups.append([rule("! Questions for you", "yellow"),
                       f"{n} questions wait for you." if n > 1 else "1 question waits for you.",
                       *text(ny[0]["title"]), [("Run: ", None), ("ap answer", "value")]])
    if d.get("card"):  # W18b: the Now card is at the top of the window; under 120 columns it is a group of this column
        if narrow:
            groups.append(dash_card.group(d, w))
    elif now and (now["title"] or now["model"] or count(now["n"])):
        n, total, tries = count(now["n"]), count(pr.get("total")), count(now["attempt"])
        g = [rule("Now", spin=spin_cell(d))]
        # J13/10: the one bold headline of the screen: 'Task 7 of 17: title'
        head = (f"Task {n} of {total}" if total else f"Task {n}") if n else ""
        g += [[(x, "bold")] for x in wrap2(f"{head}: {now['title']}" if head and now["title"] else head or now["title"],
                                           w - 4)]
        if n and tries:
            g.append([(f"Try {tries}" + (f" of {now['max_attempts']}" if count(now["max_attempts"]) else ""),
                       try_style(tries, count(now["max_attempts"])))])
        tt = []
        if n:  # J13/18: the task time ticks from the local clock; 'data Ns old' is the truth check
            sp = d.get("spin")  # W18b: the work time like the Tasks table (W42), never the wall clock since the first start
            t = ticking(now["work"] + (sp["clock"] - now["work_at"] if sp and sp["clock"] else 0))                 if now.get("work") is not None and now.get("work_at") else now["time"]
            if t:
                tt = [[f"{'Task time':<9}: ", t]]
        wt = dash_live.tick(p["wait"], sp0["clock"] if sp0 else None)  # W18a: what the run waits for, ticking
        groups.append(g + tt + row("Model", now["model"], "blue") + (text(wt) if wt else []))
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
            g += [[f"This run ({count(size.get('run_tasks'))} tasks)"], [" " * 2, (f"+{count(size['run_lines']):,} lines", "green")],
                  [" " * 2 + f"{count(size.get('run_files'))} files"]]
        groups.append(g)
    if p["last_commit"]:
        groups.append([rule("Last commit"), *text(p["last_commit"]),
                       *([[(f"{p['last_commit_age']} ago", "yellow" if p["commit_stalled"] else "dim")]]
                         if p["last_commit_age"] else [])])
    login, err, resets = login_cell(p["login"]), p["last_error"] or "—", p["resets"] or "—"
    if err != "—" and p["error_age"]:  # W18a: the age of the error; dim after the next successful session
        err = f"{p['error_age']}: {err}"
    g = [rule("Agent")] + row("Runner", p["runner"] or "—") + row("Login", *login)
    groups.append(g + row("Resets", resets, "magenta" if resets != "—" else "dim")
                  + row("Error", err, "dim" if err == "—" or p["error_old"] else "red"))
    rows = []
    for g in groups:
        if rows and len(rows) + len(g) > h - 2:
            continue  # a group that does not fit does not stop the smaller groups after it
        rows += g
    ph = d["phases"]
    build = [rule("Build")] + ([[(cut(p["version"], w - 4), "dim")]] if p["version"] else []) +         [line for x in [p["run_line"]] if x for line in text(x, "dim")]  # W18a: the version (one line) and the run number
    if len(build) > 1 and h - 2 - len(rows) - len(build) - 1 >= len(ph):  # W18b: Phases first
        rows += build
    room = h - 2 - len(rows) - 1  # the last group takes the rows that are left, after its rule line
    if ph and room >= min(len(ph), 2):  # all phases when they fit, else a last row '… N more'
        k = len(ph) if room >= len(ph) else room - 1
        at = next((i for i, x in enumerate(ph) if x["status"] == "running"),
                  next((i for i, x in enumerate(ph) if x["status"] != "done"), len(ph) - 1))
        start = min(max(at - 2, 0), len(ph) - k)
        g = [rule("Phases")]
        for x in ph[start:start + k]:
            sym, _, st = STATUS.get(x["status"], STATUS["pending"])
            g.append([(sym, st), f" {x['id']} ", (f"{x['done']}/{x['total']}", "value" if x["done"] else "dim")])
        if k < len(ph):
            g.append([(f"… {len(ph) - k} more", "dim")])
        rows += g
    return box("Project", rows, w, h, color, asof_note(d, True))


def cnt(n: int, style=None):
    """A number: its style when above 0, dim at 0."""
    return str(n), (style if n > 0 else "dim")


def right_column(d: dict, w: int, h: int, color: bool) -> list[str]:
    pr, u, f, why = d["progress"], d["usage"], d["files"], d["blocked_why"]
    word = pr.get("word") or ""
    prog = [bar_segs(d["share"]), *([[(word, "dim")]] if word else []),
            *([[(f"audit added {count(pr['audit_added'])} tasks", "yellow")]] if count(pr.get("audit_added")) else []),
            [cnt(count(pr.get("done")), "value"), " done · ", cnt(count(pr.get("working")), "value"), " working"],
            [alert(count(pr.get("blocked")), "red"), " blocked · ", cnt(count(pr.get("waiting")), "dim"), " waiting"],
            [(f"{count(pr.get('phases_done'))} of {count(pr.get('phases_total'))}", "value"), " phases"]]
    use = []
    for label, key in (("5h", "five"), ("Week", "week"), ("Context", "context")):
        if num(u.get(key)) is not None:
            use.append([f"{label:<8}", *level_bar(u.get(key))])
        if key == "five" and u["reset_in"]:
            use.append([(f"Resets in {u['reset_in']}", "dim")])
    if u["tokens_text"]:
        use.append(f"Tokens  {u['tokens_text']}")
    use += [[(f"{m['name']:<9}", "blue"), f"{m['tokens_text']:>6} {round((num(m['share']) or 0) * 100):>3}%"]
            for m in u["models"]]
    if u["cost_text"]:
        use.append(["Cost    ", (u["cost_text"], "magenta")])
    use.append(f"Rate    {u['rate'] or '—'}")
    issues = []  # the counts of blocked and questions live in Progress and in the question group
    if why:
        old = bool(why.get("old"))  # W18a: the age shows; dim after the next successful session
        issues += [[(x, "dim" if old else "red")] for x in wrap2(
            f"{why['age']} {why['id']}: {why['why']}".strip(), w - 4)]
    issues += [["Warnings  ", alert(count(pr.get("warnings")), "yellow")]]
    issues += ["  " + cut(f"{x['id']} {x['why']}", w - 6) for x in pr["warned_why"][:3]]  # the reason of each warning
    if not pr["warned_why"]:
        issues += ["  " + x for x in wrap2(" ".join(pr["warned"]), w - 6)]  # the tasks that have a warning
    issues += [["Retries   ", cnt(count(pr.get("retries")), "yellow")]]
    issues += [[f"{k:<10}", (v, "green" if v == "OK" else "red")] for k, v in d["health"].items() if k != "words" and v]
    issues += [[(x, "red")] for x in wrap2(d["health"]["words"], w - 4)]
    boxes = [("Progress", prog), ("Usage", use)]
    if f is not None:
        boxes.append(("Files", [["Added     ", cnt(count(f.get("added")), "green")],
                                ["Modified  ", cnt(count(f.get("modified")))],
                                ["Deleted   ", cnt(count(f.get("deleted")), "red")],
                                *([["Lines +   ", cnt(count(f["plus"]), "green")], ["Lines -   ", cnt(count(f["minus"]), "red")],
                                   ["Tests +   ", cnt(count(f["tests"]))]] if f.get("plus") is not None else [])]))
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
            lines = lines + [""] * (need - 3 - len(lines)) + [[("Run: ", None), (tip, "value")]]
        out += box(title, lines, w, need, color, asof_note(d, False))
        left -= need
    return out + [" " * w] * left


def tasks_panel(d: dict, w: int, h: int, color: bool) -> list[str]:
    iw, tasks = w - 4, d["tasks"]
    rt = iw - 37 >= 13  # J13/4: Risk and Tries columns when the title keeps 13 cells
    detail = rt and iw - 56 >= 13 or not rt and iw - 44 >= 14
    tw = iw - 25 - (12 if rt else 0) - (19 if detail else 0)

    def line(n, title, status, time, det, style=None, sstyle=None, risk="", tries="", tstyle=None, rstyle=None,
             ystyle=None, model=0):
        parts = [(n.rjust(3), style), (" ", None), (fit(title, tw), style), (" ", None), (fit(status, 13), sstyle),
                 (" ", None), (fit(time, 6), tstyle or style)]
        parts += [(" ", None), (fit(risk, 5), rstyle or style), (" ", None), (tries.rjust(5), ystyle or style)] if rt else []
        if detail:  # the model name is blue, the rest of the cell keeps the row style
            cell = fit(det, 18)
            parts += [(" ", None), (cell[:model], "blue"), (cell[model:], style)]
        return parts
    rows = [line("#", "Task", "Status", "Time", "Detail", "dim", "dim", "Risk", "Tries")]
    other = d["project"]["other"]  # J13/15: the time in no task, so the tasks and this row add up to Elapsed
    room = h - 3 - (1 if other else 0)
    focus = next((i for i, t in enumerate(tasks) if t["status"] == "running"),
                 next((i for i, t in enumerate(tasks) if t["status"] != "done"), len(tasks) - 1))
    start = min(max(focus - room // 2, 0), max(len(tasks) - room, 0))
    spin = spin_cell(d)
    # W18b: only a live run has an active row (and a spinner in front of it); an ended or stopped run has none
    live = not (d["card"] and d["card"]["kind"] == "ended") and not (d["asof"] and d["asof"]["stopped"])         and not (d.get("spin") and d["spin"]["kind"] == "stopped")
    for t in tasks[start:start + room]:
        sym, word, st = STATUS.get(t["status"], ("○", t["status"] or "Pending", "dim"))
        risk, rstyle = RISK.get(t["risk"], (t["risk"][:4] or "—", None))
        on = t["status"] == "running" and live  # W18b: the task in work has a filled background and bold text, one accent
        n = t["n"]
        if on and spin and len(n) <= 2:  # and the spinner turns at the start of its row
            n = spin[0].split(" ")[0] + n.rjust(2)
        row = line(n, t["title"], f"{sym} {word}", t["time"], t["detail"],
                   "active" if on else None, "active" if on else st, risk, t["tries"] or "—",
                   "active" if on else "yellow" if t["slow"] else None, "active" if on else rstyle,
                   "active" if on else "yellow" if count(t["tries"]) >= 2 else None,
                   0 if t["detail"].endswith(" tries") and " · " not in t["detail"]
                   else len(t["detail"].partition(" · ")[0]))
        if on:
            row = [(x, "active" if st_ in (None, "blue") else st_) for x, st_ in row]
        rows.append(row)
    if other:
        rows.append(line("", "Other: decide, research, docs, audit, waits", "", other, "", "dim", "dim"))
    return box("Tasks", rows, w, h, color, asof_note(d, False))


def live_panel(d: dict, w: int, h: int, color: bool) -> list[str]:
    rows = []
    for e in d["live"][-(h - 2):]:
        if e["kind"] == "blank":
            rows.append("")
        elif e["kind"] in ("heading", "goal"):
            rows.append([(e["text"], KIND[e["kind"]])])
        else:
            took = e.get("took")
            text = fit(e["text"], w - 4 - 7 - 7) if took else e["text"]
            if e["kind"] == "step" and "test" in text.lower():  # a test run is cyan
                body = [(text, "cyan")]
            elif e["kind"] == "step":  # the verb is grey, what it works on stays white
                k = len(text.split(" ", 1)[0]) + 1
                body = [(text[:k], "dim"), (text[k:], None)]
            else:
                body = [(text, "dim yellow" if e["kind"] == "wait" else KIND.get(e["kind"]))]
            rows.append([(fit(e["at"], 5), "dim"), "  ", *body, *([(" " + took.rjust(6), "dim")] if took else [])])
    return box("Live output", rows or [[("No output yet.", "dim")]], w, h, color, asof_note(d, False))


def status_bar(d: dict, cols: int, color: bool) -> str:
    """J13/13: project │ branch │ state │ task │ progress │ left │ 5h │ model │ blocked │ tok │ cost │ age. Under 100
    columns only the core items stay; then items drop from the right, the data age last. Wide cells are never wrapped."""
    p, pr, u, now, a = d["project"], d["progress"], d["usage"], d["now"] or {}, d["asof"]
    wide = cols >= MIN_COLS
    total, active, blocked, five = count(pr.get("total")), count(pr.get("active")), count(pr.get("blocked")), num(u.get("five"))
    task = f"Task {active}/{total}" if active > 0 else f"Done {count(pr.get('done'))}/{total}"
    if wide and active > 0 and count(now.get("attempt")) and count(now.get("max_attempts")):
        task += f" Try {count(now['attempt'])}/{count(now['max_attempts'])}"
    st = p["state"]
    state = (f"Stopped {p['word']}".strip() if p.get("word") else "Stopped", "dim") \
        if p["status"] and p["status"] != "running" or a and a["stopped"] else \
        (({"Commit": "Merge", "Block": "Wait"}.get(st, st)), "cyan")
    sp = spin_cell(d)  # J13/18: the spinner sits before the state word; a stopped run says so instead of the word
    c = d["card"]
    state_cells = [(f"{c['sym']} {c['word']}", c["tone"]), (f" {c['at']}" if c["at"] else "", "dim")]         if c and c["kind"] == "ended" else [(sp[0], sp[1]), (" ", None), state] if sp and d["spin"]["kind"] != "stopped" else \
        [sp] + ([(" ", None), (p["word"], "dim")] if p.get("word") else []) if sp else [state]
    age = (f"{a['age']}s" if a["age"] < 60 else f"{a['age'] // 60}m", "yellow" if a["age"] > 30 else "dim") \
        if a and a["age"] is not None and not a["stopped"] else ("", None)
    q = count(pr.get("questions"))
    blk = [(f"Blocked {blocked}", "red" if blocked > 0 else "dim")] + ([(" ", None), (f"Q {q}", "red" if q > 0 else "dim")] if wide else [])
    # (cells, core): core items stay under 100 columns
    items = [([(p["name"], None)], True), ([(p["branch"], None)], False), (state_cells, True),
             ([(task, "value")] if total else [], True), (bar_segs(d["share"]) if pr else [], True),
             ([(f"Left{':' if p['eta'].startswith('after') else ''} {p['eta']}", None)] if p["eta"] else [], True),
             ([(f"5h {round(five * 100)}%", "yellow" if five >= 0.75 else None)] if five is not None else [], False),
             ([(now.get("model") or p["model"], "blue")], False), (blk if pr else [], True),
             ([(f"Tok {u['tokens_text']}", None)] if u["tokens_text"] else [], False),
             ([(u["cost_text"], "magenta")], False), ([age], True)]
    items = [(c, core) for c, core in items if (core or wide) and any(t for t, _ in c)]
    tail = [items.pop()] if age[0] else []  # the data age drops last
    while sum(sum(len(t) for t, _ in c) + 3 for c, _ in items + tail) - 2 > cols and len(items) > 1:
        # from the right; the items that stay under 100 columns go last
        items.pop(next((i for i in range(len(items) - 1, 0, -1) if not items[i][1]), len(items) - 1))
    line = [(" ", None)]
    for c, _ in items + tail:
        line += ([(" │ ", "dim")] if len(line) > 1 else []) + c
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
    now = one(sub("project").get("now"), ("n", "title", "attempt", "max_attempts", "time", "model", "since"))
    if now:  # W18b: the work time and when it was read
        now.update({k: float(sub("project")["now"][k]) if isinstance(sub("project")["now"].get(k), (int, float)) else None
                    for k in ("work", "work_at")})
    sp = sub("spin")
    spin = ({"kind": clean(sp.get("kind")), "text": clean(sp.get("text")), "age": count(sp["age"]) if isinstance(
        sp.get("age"), (int, float)) else None,
        "data_age": count(sp["data_age"]) if isinstance(sp.get("data_age"), (int, float)) else None,
        "utf": sp.get("utf", True) is not False, "clock": float(sp["clock"]) if isinstance(sp.get("clock"), (int, float))
        else 0.0} if sp else None)
    size = data.get("size") if isinstance(data.get("size"), dict) else None
    return {
        "project": {**{k: clean(p.get(k)) for k in ("name", "branch", "model", "started", "status", "tone", "stale",
                                                    "state_words", "state", "elapsed", "eta", "next", "last_commit",
                                                    "last_commit_age", "other", "runner", "login", "resets",
                                                    "last_error", "word", "error_age", "version", "run_line",
                                                    "end_title")},
                    "stale_min": count(p.get("stale_min")), "commit_stalled": bool(p.get("commit_stalled")),
                    "error_old": bool(p.get("error_old")),
                    "since_ts": float(p["since_ts"]) if isinstance(p.get("since_ts"), (int, float)) else None,
                    "wait": ({"text": clean(w.get("text")), "since": float(w.get("since") or 0),
                              "secs": count(w.get("secs"))} if isinstance(w := p.get("wait"), dict) else None)},
        "spin": spin, "card": dash_card.norm(data.get("card"), clean),
        "you": ({"text": clean(y.get("text")), "reply": clean(y.get("reply"))}
                if isinstance(y := data.get("you"), dict) and y.get("text") else None),
        "input": clean(data["input"]) if isinstance(data.get("input"), str) else None,
        "progress": {**pr, "word": clean(pr.get("word")), "warned": [clean(x) for x in (pr.get("warned") if isinstance(pr.get("warned"), list) else [])][:6],
                     "warned_why": [x for x in (one(r, ("id", "why")) for r in pr.get("warned_why") or []) if x]},
        "share": num(share) or 0.0, "now": now, "size": size,
        "phases": [{"id": clean(r.get("id")), "status": clean(r.get("status")), "done": count(r.get("done")),
                    "total": count(r.get("total"))} for r in listed("phases") if isinstance(r, dict)],
        "next": [(clean(t[0]), clean(t[1]) if len(t) > 1 else "") for t in listed("next")
                 if isinstance(t, (list, tuple)) and t],
        "needs_you": [x for x in (one(r, ("id", "title")) for r in data.get("needs_you") or []) if x],
        "blocked_why": one(data.get("blocked_why"), ("id", "why", "age", "old")),
        "tasks": [{**r, "slow": bool(o.get("slow"))} for r, o in zip(
            rows("tasks", ("n", "id", "title", "status", "time", "detail", "risk", "tries")),
            [x for x in data.get("tasks") or [] if isinstance(x, dict)])],
        "live": rows("live", ("at", "text", "kind", "took")),
        "usage": {**u, "tokens_text": clean(u.get("tokens_text")), "cost_text": cost_text,
                  "reset_in": clean(u.get("reset_in")), "rate": clean(u.get("rate")),
                  "models": [{"name": clean(m.get("name"))[:9], "tokens_text": clean(m.get("tokens_text")),
                              "share": m.get("share")} for m in models]},
        "asof": ({"age": count(a["age"]) if isinstance(a.get("age"), (int, float)) else None,
                  "stopped": clean(a.get("stopped"))} if (a := sub("asof")) else None),
        "files": data["files"] if isinstance(data.get("files"), dict) else None,
        "health": {"Git": clean(sub("health").get("git")), "Checks": clean(sub("health").get("checks")),
                   "words": clean(sub("health").get("words"))},
    }


def you_line(y: dict, cols: int, color) -> str:
    """W48a: what the person typed and the reply, one line at the top; it grows while the reply streams."""
    return render(fit_segs([(" You: ", "dim"), (y["text"], "value"), ("  Reply: ", "dim"), (y["reply"] or "...", None)],
                           cols), color)


def input_row(text: str, cols: int, color) -> str:
    """W48a: the typing row; the end of a long text stays in view."""
    room = cols - 4
    if not text:
        return render(fit_segs([(" > ", "dim"), ("type a question or a command, Enter sends, Esc clears", "dim")], cols), color)
    return render(fit_segs([(" > ", "dim"), (text[-(room - 1):] + "_", "value")], cols), color)


def frame(data: dict, cols: int, rows: int, color: bool = False) -> list[str]:
    if cols < MIN_COLS or rows < MIN_ROWS:
        raise ValueError(f"the window must be at least {MIN_COLS}x{MIN_ROWS}")
    d = normalize(data)
    cardh = dash_card.height(d, cols)  # W18b: the Now card is the first block under the title bar
    inp = d["input"] is not None  # W48a: one input row above the bar, one You / Reply line above the card
    body = rows - 1 - cardh - inp - bool(d["you"])
    top = max(8, round(body * 0.45))
    mid = tasks_panel(d, cols - LEFT_W - RIGHT_W, top, color) + live_panel(d, cols - LEFT_W - RIGHT_W, body - top, color)
    cells = [a + b + c for a, b, c in zip(left_panel(d, LEFT_W, body, color, cols < dash_card.MID), mid,
                                          right_column(d, RIGHT_W, body, color))]
    return ([you_line(d["you"], cols, color)] if d["you"] else []) + (dash_card.box(d, cols, color) if cardh else []) \
        + cells + ([input_row(d["input"], cols, color)] if inp else []) + [status_bar(d, cols, color)]
