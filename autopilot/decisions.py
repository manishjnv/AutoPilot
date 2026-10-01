"""docs/NEEDS-YOU.md: plain-words decision requests for the owner, rendered from the decisions table."""
from __future__ import annotations

import json
import re

HEAD = re.compile(r"^## (D-\d+) · .* · (OPEN|ANSWERED|DONE)[ \t]*$", re.M)
LABEL = {"OPEN": "OPEN", "ANSWERED": "ANSWERED", "APPLIED": "DONE"}


def _line(v) -> str:
    return " ".join(str(v or "").split())


def render(state) -> str:
    out = ["# Needs you", "",
           "Autopilot keeps building everything else while these wait. Answer with `autopilot answer D-001 \"your answer\"`",
           "(works while a run is active), or, only when no run is active, write your answer after \"Your answer:\" and commit.",
           ""]
    for d in state.decisions():
        blocks = ", ".join(json.loads(d["blocks"] or "[]")) or "nothing else"
        out += [f"## {d['id']} · {_line(d['title'])} · {LABEL.get(d['status'], d['status'])}",
                f"- Question: {_line(d['question'])}", f"- What I checked: {_line(d['checked'])}",
                f"- Why I couldn't decide: {_line(d['why'])}", f"- My suggestion: {_line(d['suggestion'])}",
                f"- Blocked until answered: {blocks} (everything else continues)",
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
