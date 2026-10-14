"""W48a: answers to common questions with no model. Each reply names its source and stays under 40 words."""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path
from statistics import median

from . import AGENT_DIR


def _secs(a, b):
    try:
        return (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds()
    except (TypeError, ValueError):
        return None


def _ago(a):
    return _secs(a, dt.datetime.now().isoformat(timespec="seconds"))


def session_median(state) -> float | None:
    """Median length in seconds of the finished, good task sessions of this state; None when there are none."""
    rows = state.db.execute("SELECT started_at, ended_at FROM sessions WHERE kind='task' AND ok=1 "
                            "AND ended_at IS NOT NULL").fetchall()
    vals = [s for r in rows if (s := _secs(r[0], r[1])) is not None and s > 0]
    return median(vals) if vals else None


def mins(sec) -> str:
    return "an unknown time" if sec is None else f"about {max(1, round(sec / 60))} min"


class _Facts:
    def __init__(self, root: Path):
        from .config import Config
        from .plan import Plan
        from .report import run_journal
        from .state import State
        self.root, self.run = Path(root), run_journal(root)
        self.cfg = Config.load(root)
        self.plan = Plan.load(self.root / AGENT_DIR / "plan.yaml")
        self.state = State(self.root / AGENT_DIR / "state.db")
        self.status = self.state.status_map()

    def count(self, *sts):
        return sum(1 for t in self.plan.all_tasks() if self.status.get(t.id, "pending") in sts)

    def title(self, tid):
        t = next((t for t in self.plan.all_tasks() if t.id == tid), None)
        return t.title if t else ""


def _now(f):
    r = f.run
    if r.get("status") != "running":
        return f"No run is active (outcome: {r.get('outcome') or 'none'}) [from run.json]"
    t = r.get("task")
    return f"Now: {r.get('current') or 'idle'}" + (f" ({f.title(t)})" if t else "") + \
        f", model {r.get('model') or '?'} [from run.json]"


def _slow(f):
    m, t = session_median(f.state), f.run.get("task")
    since = _ago(f.run.get("current_at") or f.run.get("updated_at"))
    if not t or m is None or since is None:
        return "Not enough finished sessions to say what is slow [from state.db]"
    return (f"{t} has run {mins(since)}; the median session is {mins(m)}. "
            f"{'It is slow.' if since > 2 * m else 'It is normal.'} [from state.db]")


def _next(f):
    try:
        t = f.plan.next_ready(dict(f.status), f.cfg.get("scheduling.phase_dependency", "soft"))
    except Exception:  # noqa: BLE001 - a plan in the middle of a change
        t = None
    return f"Next: {t.id} {t.title} [from plan.yaml]" if t else "No task is ready to start [from plan.yaml]"


def _cost(f):
    cap = float(f.cfg.get("budget_usd.total", 0) or 0)
    return f"Cost so far: ${f.state.cost():.2f} of ${cap:g} cap [from state.db]"


def _end(f):
    from . import forecast
    done, pend = [], []
    for t in f.plan.all_tasks():
        st = f.status.get(t.id, "pending")
        if st == "done":
            done.append((t.risk, float((f.state.task(t.id)["cost"]) or 0)))
        elif st in ("pending", "running"):
            pend.append(t.risk)
    if not pend:
        return "No task is left [from state.db]"
    m = session_median(f.state)
    if m is None:
        return f"{len(pend)} tasks left; no finished session yet, so no forecast [from state.db]"
    at = dt.datetime.now() + dt.timedelta(seconds=m * len(pend))
    end = forecast.project(f.state.cost(), done, pend)
    return (f"{len(pend)} tasks left; end about {at:%a %H:%M}" + (f", cost about ${end:.0f}" if end else "")
            + " [forecast from state.db]")


def _error(f):
    r = f.state.db.execute("SELECT task_id, error FROM sessions WHERE ok=0 AND error<>'' ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return "No session error yet [from state.db]"
    return f"Last error ({r[0] or 'run'}): {' '.join(str(r[1]).split())[:140]} [from state.db]"


def _stuck(f):
    r = f.run
    if r.get("status") != "running":
        return "No run is active [from run.json]"
    beat = _ago(r.get("heartbeat_at") or r.get("beat_at") or r.get("updated_at"))
    if beat is not None and beat < 300:
        return f"The run is alive: its last sign of life was {mins(beat)} ago [from run.json]"
    return f"No sign of life for {mins(beat)}; it may be stuck. Try: stop now [from run.json]"


def _model(f):
    return f"Model now: {f.run.get('model') or 'none'} [from run.json]"


def _count(f):
    return f"{f.count('done')} done, {f.count('pending', 'running')} left, {f.count('blocked')} blocked [from state.db]"


def _window(f):
    from .report import open_window
    five = open_window(f.state)
    if not five:
        return "No usage window figure now [from state.db]"
    return (f"The 5-hour window is {round(100 * five['pct'])}% used; it resets "
            f"{dt.datetime.fromtimestamp(five['reset']):%H:%M} [from state.db]")


def _failed(f):
    r = f.state.db.execute("SELECT id, last_error FROM tasks WHERE last_error IS NOT NULL AND last_error<>'' "
                           "ORDER BY updated_at DESC LIMIT 1").fetchone()
    return (f"Last failed task: {r[0]}, {' '.join(str(r[1]).split())[:120]} [from state.db]" if r
            else "No task failed [from state.db]")


def _elapsed(f):
    s = _ago(f.run.get("started_at"))
    return f"This run started {mins(s)} ago [from run.json]" if s is not None else "No run start is known [from run.json]"


def _phase(f):
    t = f.run.get("task")
    row = f.state.task(t) if t else None
    return f"Phase: {row['phase']} [from state.db]" if row else "No task runs, so no phase [from state.db]"


def _who(f):
    env = f.cfg.get("agent.env", {})
    d = (env.get("CLAUDE_CONFIG_DIR") if isinstance(env, dict) else None) or os.environ.get("CLAUDE_CONFIG_DIR") \
        or str(Path("~/.claude").expanduser())
    return f"Login folder: {d} [from config]"


def _stop(f):
    return "Type: stop (before the next session) or stop now (ends the session at once) [from help]"


# order matters: the first pattern that matches wins
PATTERNS = [
    (r"who am i|logged in|log ?in\b|account|config folder", _who),
    (r"how (do i|to|can i) stop|how.*(cancel|halt)", _stop),
    (r"what failed|failed (last|task)|which task failed", _failed),
    (r"last error|error|went wrong", _error),
    (r"stuck|hung|frozen|alive|still working", _stuck),
    (r"reset|usage window|quota|rate limit", _window),
    (r"how long.*(run|been|go)|running for|elapsed|since when", _elapsed),
    (r"when.*(end|finish|done|over|complete)|how long.*(left|more|remain)|\beta\b|end time", _end),
    (r"time (is )?left|how much time", _end),
    (r"cost|spent|spend|money|how much|price|dollar", _cost),
    (r"slow|taking so long|too long", _slow),
    (r"which model|what model|\bmodel\b|opus|sonnet|haiku", _model),
    (r"which phase|what phase|\bphase\b", _phase),
    (r"how many|progress|left|remain|done so far", _count),
    (r"what.*next|next task|comes next|after this", _next),
    (r"what.*(run|doing|going on|happening)|\bnow\b|status|current", _now),
]


def answer(root, text: str) -> str | None:
    """The local reply for `text`, or None when no pattern matches (or the project cannot be read)."""
    low = " ".join(text.lower().split())
    for rx, fn in PATTERNS:
        if re.search(rx, low):
            try:
                return fn(_Facts(root))
            except Exception:  # noqa: BLE001 - a half-written file never breaks the reply
                return None
    return None


def fallback(root) -> str:
    """Best local reply when no pattern matches: the state of the run, and what can be asked."""
    try:
        return _now(_Facts(root)) + ". Ask: cost, next, stuck, end time."
    except Exception:  # noqa: BLE001
        return "I cannot read this project now. Ask: cost, next, stuck, end time."
