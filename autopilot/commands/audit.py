"""W8: `ap audit --history` reads the local Claude Code history and prices repeated failing commands. Offline, writes nothing."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# Public API rates in USD per million tokens (input, output), checked 2026-10. Unknown model = Sonnet.
RATES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
REPEAT_MIN = 3
EXIT_RE = re.compile(r"exit code:?\s*([1-9]\d*)", re.I)
KEYS = ("sessions", "in", "out", "calls", "repeats", "cost", "retry")


def rate(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    return next((v for k, v in RATES.items() if k in m), RATES["sonnet"])


def _blocks(msg: dict) -> list[dict]:
    c = msg.get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _failed(b: dict) -> bool:
    if b.get("is_error") is True:
        return True
    c = b.get("content")
    if isinstance(c, list):
        c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return isinstance(c, str) and bool(EXIT_RE.search(c))


def _int(v) -> int:
    return v if isinstance(v, int) else 0


def read_session(path: Path) -> dict | None:
    """Tokens, cost, tool calls and repeats of one session file; None when it cannot be read."""
    tin = tout = calls = 0
    cost = 0.0
    cmds: dict[str, str] = {}  # tool_use id -> Bash command
    fails: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        msg = d.get("message") if isinstance(d, dict) else None
        if not isinstance(msg, dict):
            continue
        u = msg.get("usage")
        if isinstance(u, dict):
            i, o = _int(u.get("input_tokens")), _int(u.get("output_tokens"))
            ri, ro = rate(str(msg.get("model") or ""))
            tin, tout, cost = tin + i, tout + o, cost + (i * ri + o * ro) / 1e6
        for b in _blocks(msg):
            if b.get("type") == "tool_use":
                calls += 1
                inp = b.get("input")
                cmd = inp.get("command") if isinstance(inp, dict) else None
                if b.get("name") == "Bash" and isinstance(cmd, str) and isinstance(b.get("id"), str):
                    cmds[b["id"]] = cmd
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in cmds and _failed(b):
                c = cmds[b["tool_use_id"]]
                fails[c] = fails.get(c, 0) + 1
    rep = [n for n in fails.values() if n >= REPEAT_MIN]
    share = sum(rep) / calls if calls else 0.0
    return {"in": tin, "out": tout, "calls": calls, "repeats": len(rep), "cost": cost, "retry": cost * share}


def label(folder: str) -> str:
    """The project folder name with the encoded home prefix removed."""
    home = re.sub(r"[^A-Za-z0-9]", "-", str(Path.home()))
    name = folder[len(home):] if folder.startswith(home) else folder
    return name.lstrip("-") or folder


def cmd_history(args) -> int:
    root = Path(getattr(args, "home", None) or "~/.claude").expanduser() / "projects"
    cutoff = time.time() - max(int(getattr(args, "days", 30)), 0) * 86400
    rows: dict[str, dict] = {}
    for f in sorted(root.glob("*/*.jsonl")) if root.is_dir() else []:
        try:
            if f.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        s = read_session(f)
        if s is None:
            continue
        r = rows.setdefault(label(f.parent.name), dict.fromkeys(KEYS, 0))
        r["sessions"] += 1
        for k in KEYS[1:]:
            r[k] += s[k]
    if not rows:
        print("No Claude Code history found.")
        return 0

    def fmt(name: str, r: dict) -> str:
        return f"{name[:32]:<32} {r['sessions']:>8} {r['in']:>10} {r['out']:>9} {r['calls']:>10} {r['repeats']:>7} {r['retry']:>8.2f}"

    print(f"{'Project':<32} {'Sessions':>8} {'Input':>10} {'Output':>9} {'Tool calls':>10} {'Repeats':>7} {'Retry $':>8}")
    for name, r in sorted(rows.items()):
        print(fmt(name, r))
    t = {k: sum(r[k] for r in rows.values()) for k in KEYS}
    print(fmt("Total", t))
    print(f"Retries cost about ${t['retry']:.2f} of ${t['cost']:.2f}.")
    return 0
