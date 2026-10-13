"""W43: the budget forecast, the soft cap on a subscription, the hard cap on api, and `ap budget`."""
import pytest

from autopilot import forecast
from autopilot.cli import main as cli_main
from autopilot.orchestrator import Orchestrator, Stop

from test_autopilot import FakeBackend, make_project, phases_basic


def events(orch, kind):
    return [r["message"] for r in orch.state.events(500) if r["kind"] == kind]


def budget_decisions(orch):
    return [d for d in orch.state.decisions() if d["kind"] == "budget"]


# ---------------------------------------------------------------- the pure forecast
def test_project_uses_the_median_of_the_same_risk():
    done = [("low", 1.0), ("low", 3.0), ("low", 2.0), ("high", 10.0)]
    assert forecast.project(5.0, done, ["low", "high", "high"]) == pytest.approx(5 + 2 + 10 + 10)


def test_project_falls_back_to_all_finished_tasks():
    done = [("low", 1.0), ("high", 5.0), ("medium", 3.0)]
    assert forecast.project(9.0, done, ["critical"]) == pytest.approx(9 + 3)


def test_project_is_none_without_a_finished_task():
    assert forecast.project(2.0, [], ["low"]) is None
    assert forecast.project(2.0, [("low", 1.0)], []) == pytest.approx(2.0)


def test_line_format():
    assert forecast.line(18.4, 35.2, 20.0) == "$18.40 spent, about $35 at the end, cap $20"


# ---------------------------------------------------------------- runs
def test_projection_past_the_cap_sends_one_event(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 1000}, "audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch.reload_plan()
    sid = orch.state.start_session("task", "P01-T01", "P01", 1, "sonnet")
    orch.state.end_session(sid, cost=600.0, ok=True)
    orch.state.set_task("P01-T01", status="done")
    orch.forecast_budget()
    orch.forecast_budget()  # once per run
    assert events(orch, "budget_forecast") == ["$600.00 spent, about $1800 at the end, cap $1000"]


def test_fake_run_sends_exactly_one_forecast_event(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.7}, "review": {"scope": "critical"},
                                                    "audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"  # no pending work at the cap: nothing to ask
    assert orch.state.cost() >= 0.7
    (msg,) = events(orch, "budget_forecast")
    assert msg.startswith("$0.25 spent, about $") and msg.endswith(", cap $0.7")
    assert budget_decisions(orch) == []


def test_no_forecast_event_below_the_cap(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 1000}, "audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert events(orch, "budget_forecast") == []


def test_subscription_at_the_cap_asks_and_does_not_stop(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.01}, "usage": {"billing": "subscription"}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    out = orch.run()
    assert "total budget" not in out and "cost cap $0.01 reached" in out
    assert orch.state.status_map()["P01-T01"] == "done"  # the active task finished past the cap
    assert orch.state.status_map()["P01-T02"] == "pending"  # no new paid work
    (d,) = budget_decisions(orch)
    assert d["status"] == "OPEN" and "Raise the cost cap to $" in d["question"] and d["suggestion"].startswith("ap budget ")
    assert orch.state.get_meta("outcome") == "BLOCKED"


def test_api_at_the_cap_stops(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.01}, "usage": {"billing": "api"}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert "total budget" in orch.run()
    assert orch.state.get_meta("outcome") == "BUDGET_STOP"
    assert budget_decisions(orch) == []


def _answer_when_asked(orch, text):
    """A sleep that answers the open budget question, as the owner would in NEEDS-YOU.md."""
    def sleep(_secs):
        cur = orch.state.open_decision(kind="budget")
        if cur:
            orch.state.answer_decision(cur["id"], text)
    return sleep


def test_answer_stop_ends_the_run_without_asking_again(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.01}, "needs_you": {"wait": True}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch._nap = _answer_when_asked(orch, "stop")
    out = orch.run()
    assert "the owner chose to stop" in out
    assert orch.state.get_meta("outcome") == "BUDGET_STOP"
    (d,) = budget_decisions(orch)  # no second budget question
    assert d["status"] == "APPLIED"


def test_answer_with_a_number_raises_the_cap_and_the_run_goes_on(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.01}, "needs_you": {"wait": True},
                                                    "audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch._nap = _answer_when_asked(orch, "raise it to 40")
    assert orch.run() == "plan complete"
    assert forecast.read_total(root / ".agent" / "project.yaml") == 40
    (d,) = budget_decisions(orch)
    assert d["status"] == "APPLIED"


def test_small_ap_budget_raise_asks_again_and_never_stops(tmp_path):
    """`ap budget` raises the cap by less than one task's cost: the question is closed at once, the next task runs
    past the new cap, and the run asks again instead of ending BUDGET_STOP."""
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.01}, "needs_you": {"wait": True},
                                                    "audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    caps = []

    def sleep(_secs):
        if orch.state.open_decision(kind="budget"):
            cap = round(orch.state.cost() + 0.05, 4) if not caps else 100
            caps.append(cap)
            assert cli_main(["budget", str(cap), "-C", str(root)]) == 0
    orch._nap = sleep
    assert orch.run() == "plan complete"
    assert orch.state.get_meta("outcome") == "VERIFIED"
    assert len(caps) == 2
    first, second = sorted(budget_decisions(orch), key=lambda d: d["id"])
    assert first["status"] == "APPLIED" and first["answer"] == f"cap raised to ${caps[0]:g}"
    assert second["status"] == "APPLIED" and second["answer"] == "cap raised to $100"


# ---------------------------------------------------------------- ap budget
YAML = """name: demo  # the project
budget_usd:   # money
  per_session: 8   # one session
  total: 20   # the whole run
  daily: 0
gate:
  total: 3   # not the budget
"""


def test_ap_budget_changes_the_value_and_keeps_comments(tmp_path, capsys):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.01}, "usage": {"billing": "api"}})
    proj = root / ".agent" / "project.yaml"
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    sid = orch.state.start_session("task", None, None, 1, "sonnet")
    orch.state.end_session(sid, cost=0.5, ok=True)
    with pytest.raises(Stop):
        orch.check_stop()
    proj.write_text(YAML, encoding="utf-8")
    assert cli_main(["budget", "40", "-C", str(root)]) == 0
    assert "$40" in capsys.readouterr().out
    assert proj.read_text(encoding="utf-8") == YAML.replace("total: 20   # the whole run", "total: 40   # the whole run")
    orch.check_stop()  # a live run reads the new cap
    assert orch.cfg.get("budget_usd.total") == 40


def test_ap_budget_rejects_zero_and_adds_a_missing_key(tmp_path):
    root = make_project(tmp_path, phases_basic())
    proj = root / ".agent" / "project.yaml"
    assert cli_main(["budget", "0", "-C", str(root)]) == 1
    proj.write_text("name: demo\n# end\n", encoding="utf-8")
    assert cli_main(["budget", "12.5", "-C", str(root)]) == 0
    assert proj.read_text(encoding="utf-8") == "name: demo\n# end\nbudget_usd:\n  total: 12.5\n"
    proj.write_text("budget_usd:\n  daily: 3  # a day\nname: x\n", encoding="utf-8")
    assert forecast.write_total(proj, 7)
    assert proj.read_text(encoding="utf-8") == "budget_usd:\n  total: 7\n  daily: 3  # a day\nname: x\n"
    assert forecast.read_total(proj) == 7
