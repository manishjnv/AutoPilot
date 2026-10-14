"""W35: find the project's plan document by its content (checkboxes, steps, plan headings), not by its name."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", ".agent", "dist", "build", "__pycache__"}
EXTS = (".md", ".txt", ".rst")
READ_CAP = 200_000  # bytes read per file
MIN_SCORE = 6  # below this a file is not a plan
CLEAR_WIN = 1.2  # the top score must be this many times the next one to be used without a question
WORDS = ("phase", "milestone", "sprint", "step", "task")

_BOX = re.compile(r"^\s*[-*+]\s+\[[ xX]\]", re.M)
_STEP = re.compile(r"^\s*\d+[.)]\s+\S", re.M)
_MD_HEAD = re.compile(r"^\s*#{1,6}\s+.*?\b(phase|milestone|sprint|step|task)s?\b", re.M | re.I)
_TXT_HEAD = re.compile(r"^\s*(phase|milestone|sprint|step|task)s?\s*[\dIVX]+\b", re.M | re.I)


class Candidate(NamedTuple):
    path: str  # posix path relative to the root
    score: float
    reason: str  # '38 checkboxes, 12 phase headings'


def score_text(text: str) -> tuple[float, str]:
    """Score one document: (0, '') when it does not look like a plan."""
    boxes, steps = len(_BOX.findall(text)), len(_STEP.findall(text))
    heads = [m.group(1).lower() for m in _MD_HEAD.finditer(text)] + \
        [m.group(1).lower() for m in _TXT_HEAD.finditer(text)]
    score = boxes * 2 + len(heads) * 3 + steps * 0.5
    if boxes + len(heads) < 2 or score < MIN_SCORE:
        return 0, ""
    score += min(len(text) / 10_000, 2)  # size: a longer plan wins a tie
    parts = [f"{boxes} checkboxes"] if boxes else []
    if heads:
        word = max(WORDS, key=heads.count)
        parts.append(f"{len(heads)} {word} headings")
    if steps:
        parts.append(f"{steps} numbered steps")
    return round(score, 1), ", ".join(parts)


def _files(root: Path):
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)  # pruned: never enter node_modules and friends
        for f in sorted(fns):
            if f.lower().endswith(EXTS):
                yield Path(dp) / f


def _read(f: Path) -> str:
    try:
        with open(f, "rb") as fh:
            return fh.read(READ_CAP).decode("utf-8", errors="replace")
    except OSError:
        return ""


def plan_candidates(root) -> list[Candidate]:
    """Every .md/.txt/.rst file that looks like a plan, best first (pure: reads files, writes nothing)."""
    root, out = Path(root), []
    for f in _files(root):
        score, reason = score_text(_read(f))
        if score:
            out.append(Candidate(f.relative_to(root).as_posix(), score, reason))
    return sorted(out, key=lambda c: (-c.score, c.path))


def _line(c: Candidate) -> str:
    return f"{c.path} ({c.reason})"


def choose_plan(root, cands: list[Candidate] | None = None) -> Path | None:
    """The plan to start from: one clear winner is used, close ones give one question (no terminal: the top one)."""
    root = Path(root)
    cands = plan_candidates(root) if cands is None else cands
    if not cands:
        return None
    if len(cands) == 1 or cands[0].score >= CLEAR_WIN * cands[1].score:
        print(f"plan found: {_line(cands[0])}")
        return root / cands[0].path
    top = cands[:3]
    if not sys.stdin.isatty():
        print(f"plan found: {_line(top[0])}; also close: {', '.join(c.path for c in top[1:])}")
        return root / top[0].path
    print("several files look like the plan:")
    for i, c in enumerate(top, 1):
        print(f"  {i}. {_line(c)}")
    try:
        ans = input(f"which one is the plan? [1-{len(top)}, Enter = 1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = ""
    pick = top[int(ans) - 1] if ans.isdigit() and 1 <= int(ans) <= len(top) else top[0]
    print(f"plan found: {_line(pick)}")
    return root / pick.path


def candidates_block(root, cands: list[Candidate] | None = None, lines: int = 5) -> str:
    """The top three candidates with their scores and first lines, for the discovery pack ('' = none)."""
    root = Path(root)
    out = []
    for c in (plan_candidates(root) if cands is None else cands)[:3]:
        head = _read(root / c.path).splitlines()[:lines]
        out.append(f"- {c.path} (score {c.score}: {c.reason})")
        if head:
            out.append("  ```\n" + "\n".join("  " + x for x in head) + "\n  ```")
    return "\n".join(out)
