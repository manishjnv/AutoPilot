"""W43: the budget forecast (pure math) and the one reader/writer of `budget_usd.total` in project.yaml."""

from __future__ import annotations

import os
import re
from pathlib import Path
from statistics import median

import yaml


def project(spent: float, done: list[tuple[str, float]], pending: list[str]) -> float | None:
    """Projected cost at the end of the plan: `spent` plus, for each pending task, the median cost of the finished
    tasks of its risk (of all finished tasks when that risk has none). None when no task has finished yet."""
    if not done:
        return None
    every = [c for _, c in done]
    by_risk: dict[str, list[float]] = {}
    for risk, cost in done:
        by_risk.setdefault(risk, []).append(cost)
    return spent + sum(median(by_risk.get(r) or every) for r in pending)


def line(spent: float, end: float, cap: float) -> str:
    return f"${spent:.2f} spent, about ${end:.0f} at the end, cap ${cap:g}"


def read_total(path: Path) -> float | None:
    """budget_usd.total of a project.yaml; None when the file, the YAML or the key is missing or broken."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return float(data["budget_usd"]["total"])
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError, AttributeError):
        return None


def write_total(path: Path, usd: float) -> bool:
    """Set budget_usd.total with a one-line text edit that keeps every comment. The new text is parsed first; when it
    would not give `usd`, nothing is written. The write is atomic (temp file + os.replace)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return False
    val = f"{usd:g}"
    head = re.search(r"(?m)^budget_usd:[ \t]*(?:#.*)?$", text)
    if head:
        end = re.search(r"(?m)^\S", text[head.end():])
        stop = head.end() + end.start() if end else len(text)
        block = text[head.end():stop]
        kid = re.search(r"(?m)^([ \t]+)[^\s#]", block)  # total counts only as a direct child of budget_usd
        m = kid and re.search(rf"(?m)^{re.escape(kid.group(1))}total:[ \t]*([^#\n]*?)[ \t]*(?:#.*)?$", block)
        if m:
            block = block[:m.start(1)] + val + block[m.end(1):]
        else:
            nxt = re.search(r"(?m)^([ \t]+)\S", block)
            block = f"\n{nxt.group(1) if nxt else '  '}total: {val}" + block
        new = text[:head.end()] + block + text[stop:]
    else:
        sep = "" if not text or text.endswith("\n") else "\n"
        new = f"{text}{sep}budget_usd:\n  total: {val}\n"
    try:
        ok = float(((yaml.safe_load(new) or {}).get("budget_usd") or {}).get("total")) == float(val)
    except (yaml.YAMLError, AttributeError, TypeError, ValueError):
        ok = False
    if not ok:
        return False
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(new, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return False
    return True
