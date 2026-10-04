"""J1 and J3: the screen in plain words (ASD-STE100 words, short sentences), and color. The log file keeps its
technical lines; this module only changes what a person sees in `watch`. Nothing here is read by the run itself."""
from __future__ import annotations

import os
import re

COLORS = {"red": "31", "green": "32", "yellow": "33", "cyan": "36", "bold": "1", "dim": "2", "count": "1;36"}


def colors_on(stream) -> bool:
    """Color only on a real terminal, and never when the user said no (NO_COLOR, AUTOPILOT_PLAIN)."""
    if os.environ.get("NO_COLOR") or os.environ.get("AUTOPILOT_PLAIN"):
        return False
    try:
        if not stream.isatty():
            return False
    except Exception:  # noqa: BLE001
        return False
    from . import cli
    return cli.enable_vt()


def paint(text: str, color: str, on: bool) -> str:
    return f"\x1b[{COLORS[color]}m{text}\x1b[0m" if on and text else text


# one color for one kind of fact, on every line of the screen
TINT = re.compile(r"(?P<bold>\b(?:Build|Progress|Usage|Health)(?=: ))|(?P<count>\b\d+ of \d+\b|\b\d+/\d+\b)"
                  r"|(?P<green>No problems\.|Build complete\.|All checks passed\.|\bOK\b|\bComplete\b)"
                  r"|(?P<red>\d+ tasks? (?:is|are) blocked\.|[1-9]\d* blocked\b|\bStopped\b|The build stopped\.|The checks failed\.)"
                  r"|(?P<yellow>Waits for your answer\.|\b[Aa]ttempt \d+|\bTry \d+|[1-9]\d* questions?\b)"
                  r"|(?P<dim>Time: [^.]+\.)"
                  r"|(?:(?<=Writes )|(?<=Reads )|(?<=Changes ))(?P<cyan>(?!the |its |a |\d)\S+?)(?=\.(?: |$))")


def tint(text: str, on: bool) -> str:
    """Color the facts inside a plain line: counts, file names, good and bad results. Off: the text as it is."""
    if not on:
        return text
    return TINT.sub(lambda m: paint(m.group(), m.lastgroup, True), text)


def _name(path: str) -> str:
    return re.split(r"[\\/]", path.strip().strip('"'))[-1] or "a file"


# first match wins; the raw command is never shown
SHELL = [(r"\b(pytest|unittest|jest|vitest|go test|cargo test|npm test)\b", "Runs the tests."),
         (r"\b(ruff|flake8|eslint|pylint|clippy)\b|\blint\b", "Checks the code style."),
         (r"\b(mypy|pyright|tsc)\b", "Checks the types."),
         (r"\buv (sync|pip|add)\b|\bpip3? install\b|\bnpm (i|ci|install)\b|\bcargo build\b|\bgo mod\b", "Installs the tools."),
         (r"\bgit (status|diff|log|show)\b", "Reads the changes."),
         (r"^\s*(python3?|node|py) (-c\b|- )", "Runs a short script."),
         (r"^\s*(cd [^&;]+(&&|;)\s*)?(ls|dir|cat|head|tail|find|tree|wc|type|pwd)\b", "Reads the project files.")]


def sentence(act: str) -> str:
    """One activity of a session ('Write path', 'Bash command', a quoted remark) as a short sentence. The model's
    own remarks give '' (left out). An unknown tool gives a neutral sentence, never the raw text."""
    act = act.strip()
    if not act or act.startswith('"'):
        return ""
    tool, _, rest = act.partition(" ")
    if tool in ("Write", "NotebookEdit"):
        return f"Writes {_name(rest)}."
    if tool in ("Edit", "MultiEdit"):
        return f"Changes {_name(rest)}."
    if tool == "Read":
        return f"Reads {_name(rest)}."
    if tool in ("Grep", "Glob"):
        return "Searches the project."
    if tool in ("WebSearch", "WebFetch"):
        return "Searches the web."
    if tool in ("Task", "Agent"):
        return "Uses a helper agent."
    if tool == "TodoWrite":
        return ""
    if tool == "StructuredOutput":
        return "Writes its report."
    if tool in ("Bash", "PowerShell"):
        return next((text for rx, text in SHELL if re.search(rx, rest)), "Runs a command.")
    return "Uses a tool."


VERIFY = {"Runs the tests.": "tests", "Checks the code style.": "code style", "Checks the types.": "types"}
LOOK = ("Reads the project files.", "Searches the project.", "Reads the changes.")
QUIET = ("Runs a command.", "Runs a short script.", "Uses a tool.")


def step(act: str):
    """J6: (kind, name, sentence) of one activity, or None. 'look' (reads and searches), 'edit' (writes and changes)
    and 'verify' (tests, style, types) make one work cycle, which is one line on the screen; any other sentence is a
    kind of its own."""
    text = sentence(act)
    if not text:
        return None
    m = re.match(r"(Writes|Changes|Reads) (?!the |its |a )(.+)\.$", text)
    if m:
        return ("look" if m.group(1) == "Reads" else "edit", m.group(2), text)
    if text in LOOK:
        return ("look", "", text)
    if text in VERIFY:
        return ("verify", VERIFY[text], text)
    return (text, "", text)


HEADINGS = [("writing PLAN.md", "The plan"), ("onboarding", "The task list"),
            ("functional check", "Test of the features"), ("audit", "Review of the full project"),
            ("repair", "Repair of the tools"), ("research", "Research"), ("fixer", "Repair of the main branch"),
            ("replan", "Change of the plan"), ("decide", "Design decision"), ("review", "Review of a task"),
            ("triage", "Bug report")]
STEP = re.compile(r"^\d{4}-\d\d-\d\d (\d\d:\d\d):\d\d \w+\s+▸ (.+?) · (.+) · \d+m\d\ds\s*$")
EVENT = re.compile(r"^\d{4}-\d\d-\d\d (\d\d:\d\d):\d\d \w+ (.+)$")


def _minutes(start: str, end: str) -> int:
    a, b = (int(x[:2]) * 60 + int(x[3:]) for x in (start, end))
    return (b - a) % 1440


def ending(outcome) -> str:
    """The last line of the view, from the outcome of the run."""
    outcome = str(outcome or "?")
    return ("The build is complete." if outcome == "plan complete" else
            "The build stopped. You asked for the stop." if "STOP file" in outcome else
            f"The build stopped. Reason: {outcome}.")


class SimpleView:
    """Turns log lines into what a beginner reads: one heading for each job (with the goal of a task), one line for
    each group of steps, one result line for each task. `names` maps a task id to (number, total, title[, goal]).
    feed(line) gives the lines that are final. The group in work is not final: open_line() shows it as it is now
    (a terminal draws it again in place), close() ends it. `width`: a line that is longer loses its file names."""

    def __init__(self, names: dict | None = None, color: bool = False, width: int | None = None):
        self.names, self.color, self.width = names or {}, color, width
        self.label, self.group, self.start, self.files, self.fails = None, None, None, set(), 0

    def heading(self, label: str) -> list[str]:
        m = re.match(r"^(\S+-T\d+)\b\s*(.*?)\s*(\[[^\]]*\])?$", label)
        if not m:
            plain = re.sub(r"\s*\[[^\]]*\]$", "", label)
            text = next((text for key, text in HEADINGS if key in plain), plain[:1].upper() + plain[1:])
            return [paint(text, "bold", self.color)]
        n, total, title, goal = (*self.names.get(m.group(1), (None, None, m.group(2))), "")[:4]
        if not n:
            return [paint(f"Task {m.group(1)}: {title}".rstrip(": "), "bold", self.color)]
        head = paint(f"Task {n} of {total}: ", "count", self.color) + paint(title, "bold", self.color)
        goal = re.split(r"(?<=[.!?:])\s", " ".join(str(goal).split()))[0].rstrip(":")  # the first sentence only
        goal = goal if len(goal) <= 100 else goal[:99].rsplit(" ", 1)[0] + " ..."
        goal += "" if not goal or goal[-1] in ".!?" else "."
        return [head] + ([paint(f"Goal: {goal}", "dim", self.color)] if goal else [])

    def open_line(self) -> str | None:
        g = self.group
        if not g:
            return None
        if g["kind"] != "cycle":
            return f"{paint(g['at'], 'dim', self.color)}  {g['kind']}"
        look, edit, verify, first = g["look"], g["edit"], g["verify"], g["first"]
        shown = edit or look  # a cycle that changes files does not list what it read first

        def build(names: bool) -> str:
            verb = "Changes" if edit else "Reads"
            parts = [first["edit"] if len(edit) == 1 else f"Reads {look[0]}." if not edit and len(look) == 1 else
                     f"{verb} {len(shown)} files" + (f": {', '.join(shown)}." if names else ".") if shown else
                     first.get("look", "")]
            if verify:
                parts.append(first["verify"] if len(verify) == 1 else f"Checks the work: {', '.join(verify)}.")
            return " ".join(x for x in parts if x)
        text = build(True)
        if self.width and len(text) + 7 > self.width:
            text = build(False)
        if self.color and shown and ", ".join(shown) in text:
            text = text.replace(", ".join(shown), ", ".join(paint(x, "cyan", True) for x in shown), 1)
        return f"{paint(g['at'], 'dim', self.color)}  {text}"

    def close(self) -> list[str]:
        line, self.group = self.open_line(), None
        return [line] if line else []

    def feed(self, line: str) -> list[str]:
        m = STEP.match(line.rstrip("\n"))
        if m:
            at, label, act = m.groups()
            out = []
            key = re.sub(r"\s*\[[^\]]*\]$", "", label)
            if key != self.label:
                out += self.close()
                self.label, self.start, self.files, self.fails = key, at, set(), 0
                out += ["", *self.heading(label)]
            # "; " also stands inside a shell command: a piece that does not start with a tool name is its rest
            acts = [a for a in act.split("; ") if a[:1] == '"' or (a[:1].isupper() and a.split(" ")[0].isalnum())]
            for kind, name, text in filter(None, (step(a) for a in acts)):
                g = self.group
                if kind in ("look", "edit", "verify"):  # one cycle: read and change in any order, then check
                    if not g or g["kind"] != "cycle" or (kind != "verify" and g["verify"]):
                        out += self.close()
                        g = self.group = {"kind": "cycle", "at": at, "look": [], "edit": [], "verify": [], "first": {}}
                    if name and name not in g[kind]:
                        g[kind].append(name)
                    g["first"].setdefault(kind, text)
                    if kind == "edit":
                        self.files.add(name)
                elif g and g["kind"] == "cycle" and text in QUIET:
                    continue  # a command with no known purpose says nothing new inside a cycle
                elif not g or g["kind"] != text:
                    out += self.close()
                    self.group = {"kind": text, "at": at}
            return out
        m = EVENT.match(line.rstrip("\n"))
        if not m:
            return []
        at, text = m.groups()
        stamp = paint(at, "dim", self.color)
        if re.match(r"task \S+ attempt \d+ failed", text):
            self.fails += 1
            return self.close() + [f"{stamp}  " + paint("The checks failed. Autopilot tries again.", "red", self.color)]
        if re.match(r"task \S+ done\b", text):
            mins = _minutes(self.start, at) if self.start else 0
            more = "".join(f" {x}" for x in (f"Files changed: {len(self.files)}." if self.files else "",
                                              f"Time: {mins}m." if mins else "",
                                              f"Attempts: {self.fails + 1}." if self.fails else "") if x)
            out = self.close() + [f"{stamp}  " + paint("The task is complete. All checks passed." + more, "green", self.color)]
            self.start, self.files, self.fails = None, set(), 0
            return out
        ph = re.match(r"closing phase (\S+)", text)
        if ph:
            return self.close() + [f"{stamp}  " + paint(f"Phase {ph.group(1)} is complete.", "green", self.color)]
        note = re.match(r"\[Autopilot · [^\]]*\] (\w+): (.*)", text)
        if note and note.group(1) in ("needs_you", "window", "rate_limit", "heal", "run_done", "fatal", "budget"):
            tone = "red" if note.group(1) == "fatal" else "yellow"
            words = ("The build stopped. You asked for the stop." if "STOP file" in note.group(2) else
                     "A question waits for you. Run: ap answer" if note.group(1) == "needs_you" else note.group(2)[:160])
            return self.close() + [f"{stamp}  " + paint(words, tone, self.color)]
        return []
