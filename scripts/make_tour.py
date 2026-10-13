"""One-off: convert examples/self-build into examples/tour/events.jsonl (the `ap tour` recording).

Run from the repository root: python scripts/make_tour.py [source_dir] [out_file]. The output is deterministic.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PATHS = re.compile(r"[A-Za-z]:[\/]+Users[\/][^\s`'\"]*|/(?:home|Users|mnt)/[^\s`'\"]*")
MAIL = re.compile(r"\S*@\S*")


def clean(text: str) -> str:
    """Scrub any path or address shape; the file holds no '@'. Nothing here depends on the host that runs the script,
    so a regenerated file is byte-equal on every machine (the test compares it with the committed copy)."""
    return MAIL.sub("(address)", PATHS.sub("(path)", text)).replace("@", "")


def section(md: str, name: str) -> list[str]:
    m = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return [ln[2:].strip() for ln in (m.group(1).splitlines() if m else []) if ln.startswith("- ")]


def head(md: str, key: str) -> str:
    m = re.search(rf"^- {key}: (.*)$", md, re.M)
    return m.group(1).strip() if m else ""


def build(src: Path) -> list[dict]:
    ev: list[dict] = []
    clock = [0.0]

    def add(kind: str, message: str, task_id: str = "", state: str = "", gap: float = 2.0, **usage):
        clock[0] = round(clock[0] + gap, 1)
        ev.append({"t": clock[0], "kind": kind, "message": clean(message)[:300], "task_id": task_id,
                   "state": state, "usage": usage})

    add("run_start", "Run started", state="running", gap=0.5)
    for pdir in sorted(p for p in (src / "history").iterdir() if p.is_dir()):
        phase = (pdir / "PHASE.md")
        ptxt = phase.read_text(encoding="utf-8").replace("\r\n", "\n") if phase.exists() else ""  # a Windows checkout may carry CRLF
        title = ptxt.splitlines()[0].lstrip("# ").strip() if ptxt else pdir.name
        add("phase_start", title, state="running", gap=3.0)
        total = 0.0
        for f in sorted(pdir.glob(f"{pdir.name}-T*.md")):
            md = f.read_text(encoding="utf-8").replace("\r\n", "\n")
            tid = f.stem
            ttl = md.splitlines()[0].split("—", 1)[-1].strip()
            cost = float(head(md, "Cost").lstrip("$") or 0)
            total += cost
            add("task_start", f"{tid} {ttl}", tid, "running", gap=4.0)
            add("session", f"Session on {head(md, 'Model')}, risk {head(md, 'Risk')}", tid, "running")
            for c in section(md, "Acceptance criteria")[:4]:
                add("criterion", c, tid, "running", gap=3.0)
            files = section(md, "Files changed")
            add("files", f"{len(files)} files changed: " + ", ".join(files[:4]), tid, "running", gap=5.0)
            add("gate", "Gate: tests, secret scan, protected files", tid, "checking", gap=6.0)
            add("task_done", f"{tid} done", tid, "done", gap=2.0, cost_usd=cost)
        add("phase_done", f"{pdir.name} closed", state="done", gap=2.0, cost_usd=round(total, 2))
    feats = json.loads((src / "features.json").read_text(encoding="utf-8")).get("features", [])
    for ft in feats:
        add("feature", f"{ft['id']} {ft['title']}: {'passes' if ft.get('passes') else 'fails'}",
            state="done" if ft.get("passes") else "failed", gap=4.0)
    cost = round(sum(e["usage"].get("cost_usd", 0) for e in ev if e["kind"] == "task_done"), 2)
    add("run_end", "VERIFIED" if all(f.get("passes") for f in feats) else "BLOCKED", state="done", gap=2.0,
        cost_usd=cost)
    return ev


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples" / "self-build"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "examples" / "tour" / "events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e, ensure_ascii=True, sort_keys=True) for e in build(src)]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(lines)} events -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
