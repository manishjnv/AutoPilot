"""O9: three growth numbers at every phase close (duplicate blocks, files over the O2 budget, layer violations),
kept in `.agent/quality_baseline.json` under `growth`. A rise inserts ONE [consolidate] task at the head of the next phase."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

from .gate import GROWTH_LINES, _count_lines
from .layers import code_files, read_layers, violations
from .plan import Plan, PlanError, insert_task

WINDOW = 6
COUNTS = ("dup_blocks", "over_budget", "violations")


def dup_blocks(root: Path, files) -> tuple[int, list[str]]:
    """(number of 6-line windows that appear in two or more files, the file pairs); whitespace is normalised."""
    seen: dict[str, set[str]] = {}
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        lines = [l for l in (" ".join(l.split()) for l in text.splitlines()) if l]
        for i in range(len(lines) - WINDOW + 1):
            w = "\n".join(lines[i:i + WINDOW])
            if len(w) >= 60:  # ponytail: a window of braces and `end`s is not a block
                seen.setdefault(w, set()).add(rel)
    shared = [fs for fs in seen.values() if len(fs) > 1]
    return len(shared), sorted({f"{a} ~ {b}" for fs in shared for a, b in itertools.combinations(sorted(fs), 2)})


def measure(root) -> dict:
    """The three numbers plus the lists behind them."""
    root = Path(root)
    files = code_files(root)
    n, pairs = dup_blocks(root, files)
    over = [f for f in files if _count_lines(root / f) > GROWTH_LINES]
    layers = read_layers(root)
    viol = violations(root, files, layers) if layers else []
    return {"dup_blocks": n, "over_budget": len(over), "violations": len(viol), "_lists": (pairs, over, viol)}


def _text(lists) -> str:
    heads = ("Duplicate blocks (files that share them)", "Files over the line budget", "Layer violations")
    return "\n".join(f"{h}:\n" + "\n".join(f"- {x}" for x in v[:20]) + (f"\n- and {len(v) - 20} more" if len(v) > 20 else "")
                     for h, v in zip(heads, lists) if v)


def _files(lists) -> list[str]:
    """The files the lists name: the scope of the consolidate task."""
    pairs, over, viol = lists
    return sorted({f for p in pairs for f in p.split(" ~ ")} | set(over) | {v.split(" -> ")[0] for v in viol})


def consolidate(root, plan_path, phase_id: str) -> str | None:
    """Record the numbers for `phase_id`; when one grew against the last close, insert the task. Returns its id."""
    root = Path(root)
    path = root / ".agent" / "quality_baseline.json"
    try:
        base = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        base = {}
    growth = base.setdefault("growth", {})
    now = measure(root)
    lists = now.pop("_lists")
    prev = list(growth.values())[-1] if growth else None
    tid = None
    phases = [p for p in Plan.load(plan_path).phases if not p.priority]
    ids = [p.id for p in phases]
    later = phases[ids.index(phase_id) + 1:] if phase_id in ids else []
    text = _text(lists)
    last = next((g["listed"] for g in reversed(list(growth.values())) if g.get("listed")), None)
    if prev and later and text != last and any(now[k] > prev.get(k, 0) for k in COUNTS):
        task = {"id": f"{later[0].id}-T00", "title": "[consolidate] merge duplicate code, split big files, fix layer violations",
                "risk": "medium", "description": "Code grew in a way that costs later. Fix exactly this list:\n" + text,
                "acceptance_criteria": ["Every item in the list is fixed, or the task report says why it stays",
                                        "No behaviour changes; the existing tests pass"],
                "files_in_scope": _files(lists)}
        try:
            insert_task(plan_path, later[0].id, task)
            tid, now["listed"] = task["id"], text
        except PlanError:  # the id exists already: a consolidate task for that phase is in the plan
            pass
    growth[phase_id] = now
    path.write_text(json.dumps(base, indent=0) + "\n", encoding="utf-8")  # phase order matters: no sort_keys
    return tid
