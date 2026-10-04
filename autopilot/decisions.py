"""docs/NEEDS-YOU.md: the questions for the owner in simple words (ASD-STE100), rendered from the decisions table.
The text says what happened, what the problem is, what the agent asks, what waits, and how to answer."""
from __future__ import annotations

import json
import re

HEAD = re.compile(r"^## (D-\d+) · .* · (OPEN|ANSWERED|DONE)[ \t]*$", re.M)
LABEL = {"OPEN": "OPEN", "ANSWERED": "ANSWERED", "APPLIED": "DONE"}
STATUS = {"OPEN": "Open. This question waits for your answer.",
          "ANSWERED": "Answered. Autopilot uses your answer when it starts this task again.",
          "APPLIED": "Complete. Autopilot used your answer."}
QUESTION = "The agent could not complete this task. How must it continue?"
OLD_QUESTION = "I could not finish this feature and cannot decide how to proceed on my own. What should I do?"
INTRO = [
    "# Questions for you", "",
    "Autopilot cannot decide these points alone. It continues with all other tasks while the questions wait.", "",
    "## How to answer", "",
    "1. Open a terminal in the project folder.",
    "2. Run `ap answer`.",
    "3. Type your answer for each question, then press Enter.", "",
    "Write the answer in your own words, as an instruction for the agent. Example: `Try again. Keep all the tests.`", "",
    "To answer one question in one command, run `ap answer D-001 \"your answer\"`.",
    "If no build is active, you can also write the answer after \"Your answer:\" in this file. Then commit the file.", ""]


def _line(v) -> str:
    return " ".join(str(v or "").split())


def problems(why) -> list[str]:
    """The reasons as a list, one sentence each. The gate writes 'PROBLEM: ...' for each one."""
    out = []
    for part in (p.strip() for p in re.split(r"\bPROBLEM:\s*", _line(why))):
        m = re.match(r"(test|assertion) count dropped in (\S+): (\d+) -> (\d+)$", part)
        if m:
            part = f"The number of {m.group(1)}s in `{m.group(2)}` decreased from {m.group(3)} to {m.group(4)}."
        if part:
            out.append(part)
    return out


def explain(d) -> list[str]:
    """One question as markdown list items in simple words. An empty field gives no line."""
    done = re.match(r"(\d+) attempts by the agent$", _line(d["checked"]))
    happened = f"The agent made {done.group(1)} attempts. The checks did not pass." if done else _line(d["checked"])
    question = _line(d["question"])
    why, blocks = problems(d["why"]), json.loads(d["blocks"] or "[]")
    out = [f"- **What happened:** {happened}"] if happened else []
    if len(why) == 1:
        out.append(f"- **The problem:** {why[0]}")
    elif why:
        out += ["- **The problem:**"] + [f"  - {p}" for p in why]
    out.append(f"- **The question:** {QUESTION if question == OLD_QUESTION else question}")
    if _line(d["suggestion"]):
        out.append(f"- **Suggestion from the agent:** {_line(d['suggestion'])}")
    out.append(f"- **What waits:** {', '.join(blocks)}. All other tasks continue." if blocks else
               "- **What waits:** No task waits.")
    return out


def render(state) -> str:
    out = list(INTRO)
    for d in state.decisions():
        out += [f"## {d['id']} · {_line(d['title'])} · {LABEL.get(d['status'], d['status'])}", "",
                f"- **Status:** {STATUS.get(d['status'], d['status'])}", *explain(d),
                f"- Your answer: {(d['answer'] or '').strip()}".rstrip(), ""]
    return "\n".join(out)


def parse_answers(text: str) -> dict[str, str]:
    parts = HEAD.split(text)  # [preamble, id, status, body, id, status, body, ...]
    out = {}
    for did, status, body in zip(parts[1::3], parts[2::3], parts[3::3]):
        m = re.search(r"^- Your answer:[ \t]*(.*?)\s*(?=^## |\Z)", body, re.M | re.S)
        if status == "OPEN" and m and m.group(1).strip():
            out[did] = m.group(1).strip()
    return out
