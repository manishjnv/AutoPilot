"""J1 and J3: the screen in plain words (ASD-STE100 words, short sentences), and color. The log file keeps its technical lines; this module only
changes what a person sees in `watch`. Nothing here is read by the run itself."""
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
TINT = re.compile(r"(?P<count>\b\d+ of \d+\b)|(?P<green>No problems\.|Build complete\.|All checks passed\.)"
                  r"|(?P<red>\d+ tasks? (?:is|are) blocked\.|The build stopped\.|The checks failed\.)"
                  r"|(?P<yellow>Waits for your answer\.|\battempt \d+)|(?P<dim>Time: [^.]+\.)"
                  r"|(?:(?<=Writes )|(?<=Reads )|(?<=Changes ))(?P<cyan>(?!the |its |a )\S+?)(?=\.(?: |$))")


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


HEADINGS = [("writing PLAN.md", "The plan"), ("onboarding", "The task list"),
            ("functional check", "Test of the features"), ("audit", "Review of the full project"),
            ("repair", "Repair of the tools"), ("research", "Research"), ("fixer", "Repair of the main branch"),
            ("replan", "Change of the plan"), ("decide", "Design decision"), ("review", "Review of a task"),
            ("triage", "Bug report")]
STEP = re.compile(r"^\d{4}-\d\d-\d\d (\d\d:\d\d):\d\d \w+\s+▸ (.+?) · (.+) · \d+m\d\ds\s*$")
EVENT = re.compile(r"^\d{4}-\d\d-\d\d (\d\d:\d\d):\d\d \w+ (.+)$")


class SimpleView:
    """Turns log lines into what a beginner reads: one heading for each job, then one short sentence for each
    step. `names` maps a task id to (number, total, title). feed(line) gives the lines to print (often none)."""

    def __init__(self, names: dict | None = None, color: bool = False):
        self.names, self.color, self.label, self.last = names or {}, color, None, None

    def heading(self, label: str) -> str:
        m = re.match(r"^(\S+-T\d+)\b\s*(.*?)\s*(\[[^\]]*\])?$", label)
        if m:
            n, total, title = self.names.get(m.group(1), (None, None, m.group(2)))
            return f"Task {n} of {total}: {title}" if n else f"Task {m.group(1)}: {title}".rstrip(": ")
        plain = re.sub(r"\s*\[[^\]]*\]$", "", label)
        return next((text for key, text in HEADINGS if key in plain), plain[:1].upper() + plain[1:])

    def feed(self, line: str) -> list[str]:
        m = STEP.match(line.rstrip("\n"))
        if m:
            at, label, act = m.groups()
            text = " ".join(dict.fromkeys(s for s in (sentence(a) for a in act.split("; ")) if s))
            out = []
            key = re.sub(r"\s*\[[^\]]*\]$", "", label)
            if key != self.label:
                self.label, self.last = key, None
                head, sep, title = self.heading(label).partition(": ")
                out += ["", paint(head + sep, "count", self.color) + paint(title, "bold", self.color) if sep
                        else paint(head, "bold", self.color)]
            if text and text != self.last:
                self.last = text
                out.append(f"{paint(at, 'dim', self.color)}  {tint(text, self.color)}")
            return out
        m = EVENT.match(line.rstrip("\n"))
        if not m:
            return []
        at, text = m.groups()
        at = paint(at, "dim", self.color)
        if re.match(r"task \S+ attempt \d+ failed", text):
            return [f"{at}  " + paint("The checks failed. Autopilot tries again.", "red", self.color)]
        if re.match(r"task \S+ done\b", text):
            self.last = None
            return [f"{at}  " + paint("The task is complete. All checks passed.", "green", self.color)]
        ph = re.match(r"closing phase (\S+)", text)
        if ph:
            return [f"{at}  " + paint(f"Phase {ph.group(1)} is complete.", "green", self.color)]
        note = re.match(r"\[Autopilot · [^\]]*\] (\w+): (.*)", text)
        if note and note.group(1) in ("needs_you", "window", "rate_limit", "heal", "run_done", "fatal", "budget"):
            tone = "red" if note.group(1) == "fatal" else "yellow"
            return [f"{at}  " + paint(note.group(2)[:160], tone, self.color)]
        return []
