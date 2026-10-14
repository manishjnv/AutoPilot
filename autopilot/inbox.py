"""W48a/b: every line a person types to a running ap goes through `.agent/inbox.jsonl` and gets a reply at once.

File format, append-only, one JSON object per line:
  the line typed:  {"t": time, "id": id, "text": text, "kind": "command" | "question"}
  a reply:         {"t": time, "id": id, "reply": text, "partial": bool}   (a later reply line replaces an earlier one;
                   a partial line holds all the text so far, the last line of an id has partial false)
A command is a line whose first word is an ap command; any other line is a question. The orchestrator loop does not
read this file: hints, answers and the budget still apply at task boundaries, through the same state as the CLI.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import uuid
from pathlib import Path

from . import AGENT_DIR

COMMANDS = ("stop", "hint", "skip", "answer", "budget", "change", "status")
HELPER_LIMIT = 20       # model calls per run
HELPER_WORDS = 60       # words in a model answer
HELPER_CHARS = 8000     # about 2000 tokens of context
LIMIT_TEXT = "(helper limit)"
_write = threading.Lock()


def _file(root) -> Path:
    return Path(root) / AGENT_DIR / "inbox.jsonl"


def _append(root, rec: dict):
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    p = _file(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _write, open(p, "a", encoding="utf-8") as f:  # one write call per line: appends do not interleave
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _rows(root) -> list[dict]:
    try:
        lines = _file(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        with contextlib.suppress(ValueError):
            rec = json.loads(ln)
            if isinstance(rec, dict):
                out.append(rec)
    return out


def latest(root) -> dict | None:
    """What the screens show: the newest line typed with its newest reply,
    {"id", "text", "kind", "reply", "partial"}; reply is "" and partial true until the first reply line.
    None when nothing was typed."""
    rows = _rows(root)
    ask = next((r for r in reversed(rows) if "text" in r), None)
    if not ask:
        return None
    rep = next((r for r in reversed(rows) if r.get("id") == ask["id"] and "reply" in r), None)
    return {"id": ask["id"], "text": ask["text"], "kind": ask.get("kind", ""),
            "reply": rep["reply"] if rep else "", "partial": rep.get("partial", False) if rep else True}


def recent(root, secs: float = 60) -> dict | None:
    """latest(), but only for `secs` seconds after the last line was written (the screens' You / Reply line)."""
    try:
        if time.time() - _file(root).stat().st_mtime > secs:
            return None
    except OSError:
        return None
    return latest(root)


def wait_reply(root, rid: str, timeout: float = 15, poll: float = 0.1) -> str | None:
    """The final reply of line `rid`, or None when it does not come within `timeout` seconds."""
    end = time.monotonic() + timeout
    while True:
        cur = latest(root)
        if cur and cur["id"] == rid and cur["reply"] and not cur["partial"]:
            return cur["reply"]
        if time.monotonic() >= end:
            return None
        time.sleep(poll)


# ---------- commands ----------
def _median_eta(state) -> str:
    from .answers import mins, session_median
    return mins(session_median(state))


def _command(root, word: str, rest: str) -> str:
    from .config import Config
    from .plan import Plan
    from .report import run_journal
    from .state import State
    root = Path(root)
    state = State(root / AGENT_DIR / "state.db")
    run = run_journal(root)
    first, _, tail = rest.partition(" ")
    if word == "hint":
        ok, msg = state.add_hint(Plan.load(root / AGENT_DIR / "plan.yaml"), first, tail)
        return f"hint for {first.upper()}, next session, {_median_eta(state)}" if ok and "blocked" not in msg else msg
    if word == "skip":
        ids = rest.split()
        if not ids:
            return "skip needs a task id."
        for tid in ids:
            state.set_task(tid.upper(), status="skipped", note="skipped by user")
        return f"{', '.join(i.upper() for i in ids)} skipped, at the next task start, {_median_eta(state)}"
    if word == "answer":
        if not first or not tail.strip():
            return "answer needs an id and text."
        if state.answer_decision(first, tail.strip()):
            return f"{first} answered; the run applies it at the next task, {_median_eta(state)}"
        return f"{first} is not an open question."
    if word == "budget":
        from . import forecast
        try:
            usd = float(first)
        except ValueError:
            return "budget needs a number of dollars."
        if usd <= 0 or not forecast.write_total(root / AGENT_DIR / "project.yaml", usd):
            return "The cost cap was not changed."
        return f"cost cap ${usd:g}, used before the next task, {_median_eta(state)}"
    if word == "stop":
        now = first == "now"
        (root / AGENT_DIR / "STOP").write_text("now\n" if now else "stop requested\n")
        return "stop now: the session ends at once" if now else f"stop: before the next session, {_median_eta(state)}"
    if word == "change":
        if not rest.strip():
            return "change needs text."
        from .docs import Documenter
        Documenter(Config.load(root)).backlog_add(rest)
        row = state.task(run.get("task") or "")
        return f"change: next replan, after {row['phase'] if row else 'the current phase'}"
    from .answers import answer
    return answer(root, "status") or "No status."  # status


# ---------- the helper call ----------
def _context(root, run: dict) -> str:
    """About 2000 tokens: the task row, the run summary and the last 30 log lines, scrubbed."""
    import os

    from .log_scrub import scrub_secrets
    from .state import State
    root = Path(root)
    state = State(root / AGENT_DIR / "state.db")
    tid = run.get("task") or ""
    row = state.task(tid) if tid else None
    parts = [f"Run: state {run.get('state')}, now {run.get('current')}, model {run.get('model')}, "
             f"sessions {run.get('sessions')}, cost ${state.cost():.2f}, build {run.get('build')}, git {run.get('git')}"]
    if row:
        parts.append(f"Task {tid}: status {row['status']}, attempts {row['attempts']}, "
                     f"last error {' '.join(str(row['last_error'] or '').split())[:300]}")
    logs = sorted((root / AGENT_DIR / "logs" / "sessions").glob("*.log"), key=lambda p: p.stat().st_mtime) \
        if (root / AGENT_DIR / "logs" / "sessions").is_dir() else []
    if logs:
        tail = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        secrets = {k: v for k, v in os.environ.items() if v and len(v) > 7 and any(w in k for w in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
        parts.append("Last log lines:\n" + scrub_secrets("\n".join(ln[:300] for ln in tail), secrets))
    return "\n".join(parts)[-HELPER_CHARS:]


def _cap_words(text: str, n: int = HELPER_WORDS) -> str:
    w = text.split()
    return " ".join(w[:n]) + ("..." if len(w) > n else "")


def _count_call(root, run: dict) -> int:
    """Calls so far in this run, counting this one; the count lives in the state and restarts with a new run."""
    from .state import State
    state = State(Path(root) / AGENT_DIR / "state.db")
    cur = state.get_meta("helper_calls", {}) or {}
    n = (cur.get("n", 0) if cur.get("run") == run.get("run_id") else 0) + 1
    state.set_meta("helper_calls", {"run": run.get("run_id"), "n": n})
    return n


def _helper(root, rid: str, text: str, fallback: str, backend):
    """Runs in a thread: one model call at a time (a lock file), the partial text goes to the inbox as it comes."""
    from .backends import SessionRequest, get_backend
    from .config import Config
    from .proc import exclusive_lock
    from .report import run_journal
    root = Path(root)
    final = fallback
    try:
        lock, end = root / AGENT_DIR / "helper.lock", time.monotonic() + 120
        while True:  # the next question waits for the one before it
            try:
                with exclusive_lock(lock):
                    run = run_journal(root)
                    if _count_call(root, run) > HELPER_LIMIT:
                        final = f"{fallback} {LIMIT_TEXT}"
                        break
                    cfg = Config.load(root)
                    seen: list[str] = []

                    def on_text(piece: str):
                        seen.append(piece)
                        _append(root, {"id": rid, "reply": _cap_words("".join(seen)), "partial": True})

                    req = SessionRequest(
                        prompt=("Answer the question in at most 60 words, in simple words, from this context only. "
                                "If the context does not say, say so.\n\n" + _context(root, run) + f"\n\nQuestion: {text}"),
                        model=cfg.get("models.helper", "haiku"), cwd=str(root), timeout_sec=60, read_only=True,
                        no_tools=True, on_text=on_text, label="inbox helper")
                    res = (backend or get_backend(cfg)).run(req)
                    if res.ok and (res.text or "".join(seen)).strip():
                        final = _cap_words((res.text or "".join(seen)).strip())
                    break
            except BlockingIOError:
                if time.monotonic() > end:
                    break
                time.sleep(0.2)
    except Exception:  # noqa: BLE001 - any failure gives the local reply, never a blank line
        final = fallback
    _append(root, {"id": rid, "reply": final, "partial": False})


def record(root, text: str, reply: str):
    """W53: a command typed in a shell (`ap hint ...`) goes into the inbox with its reply, as the watch row does."""
    from .signals import redact
    rid = uuid.uuid4().hex[:8]
    _append(root, {"id": rid, "text": redact(" ".join(text.split())), "kind": "command"})
    _append(root, {"id": rid, "reply": redact(reply), "partial": False})


def spawn_helper(root, rid: str, text: str, fb: str):
    """W53: the helper call as its own process, so a short-lived shell does not take it down when it exits."""
    import os
    import subprocess
    import sys
    import tempfile
    code = "import sys; sys.path[:] = [p for p in sys.path if p]; from autopilot import inbox; inbox._helper(*sys.argv[1:5], None)"
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=tempfile.gettempdir(),
              env={**os.environ, "PYTHONSAFEPATH": "1"})  # never the checkout: a planted autopilot/ package must not load
    if os.name == "nt":
        subprocess.Popen([sys.executable, "-c", code, str(root), rid, text, fb],  # noqa: S603
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP, **kw)
    else:
        subprocess.Popen([sys.executable, "-c", code, str(root), rid, text, fb], start_new_session=True, **kw)  # noqa: S603


def submit(root, text: str, backend=None, spawn=None) -> tuple[str, threading.Thread | None]:
    """Take one typed line: write it, answer a command or a local question at once, else start the helper thread.
    Returns (id, thread); the thread is None when the final reply is already written."""
    from .answers import answer, fallback
    root, text = Path(root), " ".join(text.split())
    rid = uuid.uuid4().hex[:8]
    word, _, rest = text.partition(" ")
    kind = "command" if word.lower() in COMMANDS else "question"
    _append(root, {"id": rid, "text": text, "kind": kind})
    if kind == "command":
        try:
            reply = _command(root, word.lower(), rest.strip())
        except Exception as exc:  # noqa: BLE001
            reply = f"{word} did not work: {exc}"
        _append(root, {"id": rid, "reply": reply, "partial": False})
        return rid, None
    local = answer(root, text)
    if local:
        _append(root, {"id": rid, "reply": local, "partial": False})
        return rid, None
    if spawn:
        spawn(root, rid, text, fallback(root))
        return rid, None
    th = threading.Thread(target=_helper, args=(root, rid, text, fallback(root), backend), daemon=True)
    th.start()
    return rid, th


def cmd_line(root, text: str, wait: float = 15, backend=None, spawn=None) -> int:
    """`ap <anything>`: send the line, print the reply, wait up to `wait` seconds for it. The model call runs as a
    detached process (W53): when it is slow the local reply is printed and the model reply still lands in the inbox."""
    rid, th = submit(root, text, backend, spawn or (None if backend else spawn_helper))
    reply = wait_reply(root, rid, wait)
    slow = reply is None
    if slow:  # the helper is slow: give the local reply
        from .answers import fallback
        reply = fallback(root)
        _append(root, {"id": rid, "reply": reply, "partial": False})
    print(f"You: {' '.join(text.split())}\nReply: {reply}")
    if slow:
        print("(the full answer lands in ap watch)")
    return 0
