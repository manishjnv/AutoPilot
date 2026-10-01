"""U4: keep a share of the subscription's 5-hour window for the owner; learn the window size from a limit hit."""
import time

from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}


def tasks(n, risk="medium"):
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"t{i}", "risk": risk} for i in range(1, n + 1)]}]


def run(tmp_path, phases, cfg, fake=None):
    slept = []
    orch = Orchestrator(make_project(tmp_path, phases, {**BASE, **cfg}), backend=fake or FakeBackend(), sleep=slept.append)
    assert orch.run() == "plan complete"
    windows = [e["message"] for e in orch.state.events(200) if e["kind"] == "window"]
    return orch, slept, windows


def test_reserve_pauses_until_the_window_resets(tmp_path):
    # each task costs $0.25: 4 tasks = $1.00 >= 85% of a $1 window, so the 5th waits for the next window
    orch, slept, windows = run(tmp_path, tasks(5), {"usage": {"window_usd": 1.0}})
    assert len(windows) == 1 and "keeping 15% of it for you" in windows[0]
    assert len(slept) == 1 and 4.9 * 3600 < slept[0] <= 5 * 3600 + 120
    assert orch.state.status_map()["P01-T05"] == "done"


def test_api_billing_never_pauses(tmp_path):
    _, slept, _ = run(tmp_path, tasks(5), {"usage": {"window_usd": 1.0, "billing": "api"}})
    assert slept == []


def test_unknown_window_size_never_pauses(tmp_path):
    _, slept, _ = run(tmp_path, tasks(5), {})  # size not set and never learned
    assert slept == []


def test_opus_heavy_sessions_wait_for_a_fresh_window(tmp_path):
    phases = tasks(2) + [{"id": "P02", "title": "Two", "tasks": [{"id": "P02-T01", "title": "risky", "risk": "high"}]}]
    cfg = {"usage": {"window_usd": 1.0, "opus_by_pct": 50}, "decide": {"enabled": True}}
    _, slept, windows = run(tmp_path, phases, cfg)  # $0.50 spent >= 50% of the usable $0.85 before the decide session
    assert len(windows) == 1 and "Opus-heavy work waits for a fresh window" in windows[0] and len(slept) == 1


def test_a_limit_hit_teaches_the_window_size(tmp_path):
    reset = time.time() + 3600

    class Limited(FakeBackend):
        def run(self, req):
            if "implement task P01-T03" in req.prompt and not any(c[0] == "P01-T03" for c in self.calls):
                self.calls.append(("P01-T03", req.model))
                return SessionResult(ok=False, error="You've hit your session limit · resets 3pm", rate_limited=True,
                                     reset_at=reset)
            return super().run(req)
    orch, _, _ = run(tmp_path, tasks(3), {}, Limited())
    assert orch.state.get_meta("window_capacity_usd") == 0.5  # two $0.25 tasks were spent in that window
    assert orch.state.get_meta("window_start") in (0, reset - 5 * 3600)
