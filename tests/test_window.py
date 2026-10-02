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


# ---- G1: the CLI's own usage figure (the stream's rate_limit_event), which also counts the owner's use ----

class Metered(FakeBackend):
    """Every session reports a usage figure: `pcts` in order, the last one repeating."""

    def __init__(self, pcts, reset=None, week=0.1):
        super().__init__()
        self.pcts, self.reset, self.week = list(pcts), reset or time.time() + 3600, week

    def run(self, req):
        res = super().run(req)
        pct = self.pcts.pop(0) if len(self.pcts) > 1 else self.pcts[0]
        res.window = {"five_hour": {"pct": pct, "reset": self.reset},
                      "seven_day": {"pct": self.week, "reset": self.reset + 86400}, "status": "allowed"}
        return res


def test_the_cli_usage_figure_pauses_at_the_reserve_without_a_known_window_size(tmp_path):
    fake = Metered([0.5, 0.86, 0.1])  # no usage.window_usd: the dollar estimate could never pause here
    orch, slept, windows = run(tmp_path, tasks(3), {}, fake)
    assert len(windows) == 1 and "86% of this usage window" in windows[0] and "keeping 15% of it for you" in windows[0]
    assert len(slept) == 1 and 3600 < slept[0] <= 3600 + 120  # until the reset the CLI gave, plus two minutes
    assert orch.state.status_map()["P01-T03"] == "done"


def test_the_cli_usage_figure_wins_over_the_dollar_estimate(tmp_path):
    # $1.25 of spend in a $1 window would pause on the estimate, but the CLI says only 20% is used
    _, slept, windows = run(tmp_path, tasks(5), {"usage": {"window_usd": 1.0}}, Metered([0.2]))
    assert slept == [] and windows == []


def test_an_expired_cli_figure_falls_back_to_the_dollar_estimate(tmp_path):
    fake = Metered([0.99], reset=time.time() - 10)  # that window is over: the figure says nothing about this one
    _, slept, windows = run(tmp_path, tasks(5), {"usage": {"window_usd": 1.0}}, fake)
    assert len(slept) == 1 and len(windows) == 1 and "$" in windows[0]


def test_a_cli_figure_with_an_impossible_reset_time_is_ignored(tmp_path):
    fake = Metered([0.99], reset=time.time() + 9 * 3600)  # a 5-hour window can't reset in 9 hours: a wrong clock
    _, slept, windows = run(tmp_path, tasks(3), {}, fake)
    assert slept == [] and windows == []


def test_weekly_limit_warns_once_and_never_pauses(tmp_path):
    _, slept, windows = run(tmp_path, tasks(3), {}, Metered([0.2], week=0.93))
    assert slept == [] and len(windows) == 1 and "93% of the weekly usage limit" in windows[0]


def test_report_and_run_summary_show_the_usage_window(tmp_path):
    from autopilot.report import build_report
    orch, _, _ = run(tmp_path, tasks(1), {}, Metered([0.4]))
    assert "Usage window: 40% of the 5-hour window" in build_report(orch.cfg, orch.plan, orch.state)
    done = [e["message"] for e in orch.state.events(200) if e["kind"] == "run_done"]
    assert "Usage window: 40%" in done[-1]
