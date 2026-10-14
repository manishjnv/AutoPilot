"""W18b: the Now card of the watch screen, drawn as text. A task, an end-phase step or the end of the run in one card
at the top of the window (120 columns and wider) or as a group in the left column (under 120). Pure functions of the
plain dict that dashboard.py builds (`card`) and of the window clock: the time, the fill of the running segment and
the shimmer come from `clock`, so the card moves every second while the data file changes once in a while.
dash_term.py calls height(), box() and group()."""
from __future__ import annotations

from . import dash_live

WIDE, MID = 160, 120  # 160+: two inner lines; 120 to 159: four; under 120: the six-line group in the left column
SEP = (" ── ", "dim")


def norm(c, clean) -> dict | None:
    """Every key present, every string clean, odd types replaced."""
    if not isinstance(c, dict) or c.get("kind") not in ("task", "end", "ended"):
        return None
    num = lambda k: float(c[k]) if isinstance(c.get(k), (int, float)) else None  # noqa: E731
    cnt = lambda k: int(c[k]) if isinstance(c.get(k), (int, float)) else 0  # noqa: E731
    steps = [clean(x) for x in c.get("steps") or []][:5]
    w = [float(x) for x in c.get("weights") or [] if isinstance(x, (int, float))]
    e, d, wt = c.get("eta"), c.get("diff"), c.get("wait")
    return {"kind": c["kind"], **{k: clean(c.get(k)) for k in ("title", "what", "then", "model", "first_start", "why",
                                                               "word", "sym", "tone", "at", "elapsed")},
            **{k: cnt(k) for k in ("n", "attempt", "max_attempts", "step", "tokens", "done", "total", "retries", "findings")},
            **{k: num(k) for k in ("work", "work_at", "since", "step_eta", "cost")},
            "steps": steps, "weights": w if len(w) == len(steps) else [1 / max(len(steps), 1)] * len(steps),
            "eta": ({"lo": num2(e, "lo"), "mid": num2(e, "mid"), "hi": num2(e, "hi"), "basis": clean(e.get("basis"))}
                    if isinstance(e, dict) else {"lo": None, "mid": None, "hi": None, "basis": ""}),
            "diff": ({k: int(d.get(k) or 0) for k in ("plus", "minus", "files", "tests")} if isinstance(d, dict) else None),
            "wait": ({"kind": clean(wt.get("kind")), "text": clean(wt.get("text")), "since": float(wt.get("since") or 0),
                      "secs": cnt2(wt, "secs")} if isinstance(wt, dict) else None),
            "pending": [{"what": clean(x.get("what")), "how": clean(x.get("how"))}
                        for x in c.get("pending") or [] if isinstance(x, dict)]}


def num2(d, k):
    return float(d[k]) if isinstance(d.get(k), (int, float)) else None


def cnt2(d, k) -> int:
    return int(d[k]) if isinstance(d.get(k), (int, float)) else 0


def clip(parts: list, w: int) -> list:
    """Pieces cut to w cells, '...' at the end of the cut; no padding."""
    if sum(len(t) for t, _ in parts) <= w:
        return parts
    out, keep = [], max(w - 3, 0)
    for t, st in parts:
        if keep <= 0:
            break
        out.append((t[:keep], st))
        keep -= len(t[:keep])
    return out + [("..."[:w], out[-1][1] if out else None)]


def length(parts) -> int:
    return sum(len(t) for t, _ in parts)


def join(items: list, sep=(" · ", "dim")) -> list:
    out = []
    for it in items:
        if it:
            out += ([sep] if out else []) + it
    return out


# ---------------------------------------------------------------- the facts as text
def minutes(s: float) -> str:
    return f"{max(1, round(s / 60))}m" if s < 5400 else f"{s / 3600:.1f}h"


def eta_text(e: dict) -> str:
    if e["lo"] is not None and e["hi"] is not None:
        a, b = minutes(e["lo"]), minutes(e["hi"])
        rng = a if a == b else f"{a[:-1]} to {b}" if a[-1] == b[-1] else f"{a} to {b}"
        return f"ETA {rng} ({e['basis']})"
    return f"ETA ~{minutes(e['mid'])} ({e['basis']})" if e["mid"] else f"ETA unknown ({e['basis']})"


def clock_of(d: dict):
    sp = d.get("spin")
    return sp["clock"] if sp and sp.get("clock") else None


def work_text(c: dict, clock) -> str:
    """The work time of the task, ticking on the window clock; the same count as the Tasks table (W42)."""
    from .dash_term import ticking
    secs = (c["work"] or 0) + (clock - c["work_at"] if clock and c["work_at"] else 0)
    return ticking(secs) + (f" (first start {c['first_start']})" if c["first_start"] else "")


def progress(c: dict, clock) -> tuple:
    """(index of the running step, its fill 0..0.95, percent 0..99). The running step never completes early."""
    idx = min(max(c["step"], 0), max(len(c["steps"]) - 1, 0))
    elapsed = max(0.0, clock - c["since"]) if clock and c["since"] else 0.0
    frac = min(elapsed / c["step_eta"], 0.95) if c["step_eta"] else min(elapsed / (elapsed + 60), 0.95)
    pct = int(100 * (sum(c["weights"][:idx]) + c["weights"][idx] * frac)) if c["steps"] else 0
    return idx, frac, min(pct, 99)


def sofar(c: dict) -> list:
    from .report import _n
    d = c["diff"]
    bits = []
    if d:
        bits.append([(f"+{d['plus']}", "green"), (" / ", None), (f"-{d['minus']}", "red"), (" lines", None)])
        bits.append([(f"{d['files']} file{'' if d['files'] == 1 else 's'}", None)])
        if d["tests"]:
            bits.append([(f"{d['tests']} new test{'' if d['tests'] == 1 else 's'}", None)])
    bits.append([(f"{_n(c['tokens'])} tokens", None)])
    bits.append([(f"${c['cost'] or 0:.2f}", "magenta")])
    return [("So far: ", "dim"), *join(bits)]


def step_part(c: dict, clock, utf: bool) -> list:
    """W53: the current step with a small bar filled by its time against the median for that step; with no median
    only the elapsed time and no fill."""
    if not c["steps"] or not clock or not c["since"]:
        return []
    idx, frac, _ = progress(c, clock)
    secs = max(0.0, clock - c["since"])
    txt = dash_live.span(secs)
    if not c["step_eta"]:
        return [(f"{c['steps'][idx]} ", "cyan"), (txt, None)]
    f = int(frac * 8)
    b = ("█" * f + "░" * (8 - f)) if utf else "[" + "=" * f + " " * (8 - f) + "]"
    return [(f"{c['steps'][idx]} ", "cyan"), (b, "cyan"), (f" {txt} of ~{minutes(c['step_eta'])}", None)]


def findings_part(c: dict) -> list:
    return [(f"{c['findings']} finding{'' if c['findings'] == 1 else 's'} noted", None)] if c["kind"] == "end" else []


def last_line(c: dict, clock) -> list:
    w = c["wait"]
    if not w or not w["text"]:
        return []
    secs = (clock - w["since"]) if clock and w["since"] else w["secs"]
    if w["kind"] == "gate":
        return [("Waiting for: ", "dim"), (f"{w['text']}, {dash_live.span(secs)}", None)]
    return [("Last: ", "dim"), (f"{w['text']} (running {dash_live.span(secs)[:-4] if secs >= 60 else dash_live.span(secs)})", None)]


def try_part(c: dict, short: bool = False) -> list:
    if c["kind"] != "task" or not c["attempt"]:
        return []
    m = c["max_attempts"]
    last = bool(m and c["attempt"] >= m)
    return [(f"try {c['attempt']}/{m}" if short and m else f"try {c['attempt']}" + (f" of {m}" if m else ""),
             "yellow" if last else None)]


def who(c: dict, short: bool = False) -> list:
    return join([[(c["model"], "blue")] if c["model"] else [], try_part(c, short)])


def why_part(c: dict) -> list:
    return [(f"why: {c['why']}", "yellow")] if c.get("why") else []


def head_text(c: dict, total: int) -> str:
    if c["kind"] == "end":
        return f"{c['title']} · {c['what']} · {c['then']}"
    return f"Task {c['n']} of {total}" if total else f"Task {c['n']}"


# ---------------------------------------------------------------- the bar
def cells(weights: list, room: int) -> list[int]:
    """Whole cells for each step from its weight; no step has fewer than two; the sum is exactly `room`."""
    n = len(weights)
    ks = [max(2, int(room * w)) for w in weights]
    while sum(ks) < room:
        ks[max(range(n), key=lambda i: weights[i] * room - ks[i])] += 1
    while sum(ks) > room and max(ks) > 2:
        ks[ks.index(max(ks))] -= 1
    return ks


def bar(c: dict, width: int, clock, utf: bool, labels: bool = True) -> list:
    """The segmented bar. A finished step is full and green, the running step fills in the accent colour by its time
    against its ETA (never to its last cell) with one brighter cell that slides across the fill once a second, a step
    not started is dim. ASCII: [====>   ] with the > sliding."""
    steps = c["steps"]
    n = len(steps)
    if not n:
        return []
    idx, frac, _ = progress(c, clock)
    names = [("✓" if i < idx else "") + steps[i] for i in range(n)] if labels else [""] * n
    room = width - (n - 1) - sum(len(x) + (1 if x else 0) for x in names)
    if room < 2 * n:  # no room for the names: blocks only
        names, room = [""] * n, width - (n - 1)
    ks = cells(c["weights"], max(room, 2 * n))
    out = []
    for i, (name, k) in enumerate(zip(names, ks)):
        st = "green" if i < idx else "cyan" if i == idx else "dim"
        out += [(" ", None)] if i else []
        out += [(name + (" " if name else ""), st)] if name else []
        if i < idx:
            out.append((("█" * k) if utf else "[" + "=" * (k - 2) + "]", "green"))
        elif i > idx:
            out.append((("░" * k) if utf else "[" + " " * (k - 2) + "]", "dim"))
        else:
            tick = int(clock or 0)
            if utf:
                f = min(k - 1, int(frac * k))
                fill = ["█"] * f
                if f >= 2:
                    fill[tick % f] = "▓"
                out += [("".join(fill), "cyan"), ("░" * (k - f), "dim")]
            else:
                inner = k - 2
                f = min(inner - 1, int(frac * inner))
                fill = ["="] * f + [">"]
                if f >= 1:
                    fill[tick % f], fill[f] = ">", "="
                out += [("[" + "".join(fill) + " " * (inner - f - 1) + "]", "cyan")]
    return out


# ---------------------------------------------------------------- the frame of the card
def right_end(d: dict) -> list:
    """The data age and the spinner at the right end of the border: the only moving parts."""
    from .dash_term import SPIN_STYLE, asof_note
    sp, c = d.get("spin"), d["card"]
    if c["kind"] == "ended":
        return [(f"stopped {c['at']}" if c["at"] else "stopped", "dim")]
    if not sp or not sp.get("text"):
        note = asof_note(d, True, True)
        return [note] if note else [("data —", "dim")]
    if sp["kind"] == "stopped":
        return [(sp["text"], "red")]
    age = sp["age"] if sp.get("data_age") is None else sp["data_age"]
    stale = sp["kind"] == "stale" or (age or 0) > 30
    txt = "data —" if age is None else f"data {age}s" if age < 60 else f"data {age // 60}m"
    return [(txt + (" stale" if stale else ""), "yellow" if stale else "dim"), (" ", None),
            (sp["text"].split(" ")[0], SPIN_STYLE.get(sp["kind"], "cyan"))]


def top(d: dict, ctext: list, cols: int, color) -> str:
    """┌─ Now ──── <stable facts, centred> ──── data 1s ⠋ ┐ : one terminal row; the text is cut, never wrapped."""
    from .dash_term import render
    right = right_end(d)
    region = cols - (length(right) + 10)
    ctext = clip(ctext, max(region - 2 - 4, 0)) if ctext else []
    if ctext:
        a = max((region - length(ctext) - 2) // 2, 2)
        b = max(region - length(ctext) - 2 - a, 1)
        mid = [("─" * a + " ", "dim"), *ctext, (" " + "─" * b, "dim")]
    else:
        mid = [("─" * region, "dim")]
    return render([("┌─", "dim"), (" Now ", "active"), *mid, (" ", None), *right, (" ┐", "dim")], color)


def inner(lines: list, cols: int, color) -> list[str]:
    from .dash_term import fit_segs, render
    return [render([("│ ", "dim"), *fit_segs(x, cols - 4), (" │", "dim")], color) for x in lines]


def ended_lines(c: dict, limit: int = 6) -> list:
    """The final summary: the counts, then what is still pending with its command or person."""
    bits = [[(f"{c['done']} of {c['total']} tasks done", "green" if c["done"] == c["total"] else "yellow")],
            [(f"{c['retries']} retr{'y' if c['retries'] == 1 else 'ies'}", None)],
            [(f"${c['cost']:.2f}", "magenta")], [(c["elapsed"], None)] if c["elapsed"] else []]
    out = [[*join(bits)]]
    pend = c["pending"]
    if not pend:
        return out + [[("Nothing is pending.", "dim")]]
    shown = pend if len(pend) <= limit else pend[:limit - 1]
    out += [[("Open: ", "yellow"), (x["what"], None), ("  →  ", "dim"), (x["how"], "value")] for x in shown]
    return out + ([[(f"… {len(pend) - len(shown)} more", "dim")]] if len(shown) < len(pend) else [])


def height(d: dict, cols: int) -> int:
    c = d.get("card")
    if not c or cols < MID:
        return 0
    if c["kind"] == "ended":
        return 2 + len(ended_lines(c))
    return 4 if cols >= WIDE else 6


def box(d: dict, cols: int, color) -> list[str]:
    """The full-width card (120 columns and wider), height(d, cols) rows."""
    c, total = d["card"], d["progress"].get("total") or 0
    clock, utf = clock_of(d), (d.get("spin") or {}).get("utf", True)
    iw = cols - 4
    from .dash_term import render
    bottom = render([("└" + "─" * (cols - 2) + "┘", "dim")], color)
    if c["kind"] == "ended":
        return [top(d, [("Run ended", None), SEP, (c["word"], c["tone"])], cols, color),
                *inner(ended_lines(c), cols, color), bottom]
    head = head_text(c, total)
    pct = f" about {progress(c, clock)[2]}%"
    time_ = [(work_text(c, clock), None)]
    eta = [(eta_text(c["eta"]), "dim")]
    dont = [("do not close", "yellow")] if c["kind"] == "end" else []
    rest = join([time_, eta, dont, why_part(c)])
    if cols < MID:  # the six-line form of the contract: the border, then five lines
        l1 = [(f"{head} · ", None), (c["title"], "bold")] if c["kind"] == "task" else [(head, "bold")]
        lines = [l1, join([who(c), time_, eta, dont, why_part(c)]), [*bar(c, iw - len(pct), clock, utf), (pct, "value")],
                 sofar(c), last_line(c, clock) or [("", None)]]
        return [top(d, [], cols, color), *inner(lines, cols, color), bottom]
    facts = join([who(c, True)]) if c["kind"] == "task" else who(c)
    if cols >= WIDE:
        room = cols - (length(right_end(d)) + 10) - 6 - length(facts) - 2 * len(SEP[0])  # the facts are cut last
        if c["kind"] == "task":
            ctext = join([[(head, None)], clip([(c["title"], "bold")], max(room - len(head), 12)), facts], SEP)
        else:
            ctext = join([clip([(head, None)], max(room, 12)), facts], SEP)
        line1 = [*join([time_, eta]), (" · ", "dim")]
        line1 += bar(c, max(iw - length(line1) - len(pct), 20), clock, utf) + [(pct, "value")]
        line2 = join([step_part(c, clock, utf), findings_part(c), sofar(c), last_line(c, clock), dont, why_part(c)])
        lines = [line1, line2]
    else:
        ctext = join([[(head, None)] if c["kind"] == "task" else [(c["title"], None)], facts], SEP)
        l1 = [(c["title"] if c["kind"] == "task" else f"{c['what']} · {c['then']}", "bold")]
        lines = [l1, rest, [*bar(c, iw - len(pct), clock, utf), (pct, "value")], join([step_part(c, clock, utf), findings_part(c), sofar(c), last_line(c, clock)])]
    return [top(d, ctext, cols, color), *inner(lines, cols, color), bottom]


def group(d: dict, w: int) -> list:
    """The card as a group of the left column (under 120 columns): a rule line with the data age, then up to six lines."""
    c, total = d["card"], d["progress"].get("total") or 0
    clock, utf = clock_of(d), (d.get("spin") or {}).get("utf", True)
    right = right_end(d)
    ruled = [("── ", "dim"), (" Now ", "active"), (" ", None)]
    fill = max(w - 4 - length(ruled) - length(right) - 2, 1)
    rule = [*ruled, ("─" * fill + " ", "dim"), *right]
    iw = w - 4
    if c["kind"] == "ended":
        return [rule, [(f"Run ended: ", None), (c["word"], c["tone"])], *ended_lines(c, 3)[:5]]
    pct = f" {progress(c, clock)[2]}%"
    step = c["steps"][progress(c, clock)[0]] if c["steps"] else ""
    head = [(f"Task {c['n']} of {total}: {c['title']}" if c["kind"] == "task" else c["title"], "bold")]
    return [rule, clip(head, iw), clip(join([who(c, True), [(work_text(c, clock), None)]]), iw),
            clip(join([[(eta_text(c["eta"]), "dim")], why_part(c)]), iw),
            [*bar(c, iw - len(pct) - len(step) - 1, clock, utf, labels=False), (" " + step + pct, "value")],
            clip(sofar(c), iw), clip(last_line(c, clock) or [("", None)], iw)]
