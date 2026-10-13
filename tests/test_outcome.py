"""W3: one outcome word at the end of every run (state meta, run_end event, notification, title, ap status)."""
from autopilot.cli import main as cli_main
from autopilot.orchestrator import Orchestrator, Stop, outcome_word
from autopilot.plan import Plan
from autopilot.report import run_journal, status_line
from autopilot.state import State

from test_autopilot import FakeBackend, make_project, phases_basic


def events(orch, kind):
    return [r["message"] for r in orch.state.events(500) if r["kind"] == kind]


def test_complete_plan_is_verified(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"  # the return value stays as it was
    assert orch.state.get_meta("outcome") == "VERIFIED"
    assert events(orch, "run_done")[0].startswith("VERIFIED plan complete — ")
    assert events(orch, "run_end") == ["VERIFIED plan complete"]
    run = run_journal(root)
    assert run["word"] == "VERIFIED" and run["outcome"] == "plan complete"
    assert status_line(orch.cfg, orch.plan, orch.state, run).startswith("Done VERIFIED │")


def test_parked_task_is_blocked(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(behaviours={"P01-T01": ["blocked"]}), sleep=lambda s: None)
    out = orch.run()
    assert orch.state.status_map()["P01-T01"] == "blocked"
    assert orch.state.get_meta("outcome") == "BLOCKED"
    assert events(orch, "run_end") == [f"BLOCKED {out}"]


def test_budget_cap_is_budget_stop(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.01}, "usage": {"billing": "api"}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert "total budget" in orch.run()
    assert orch.state.get_meta("outcome") == "BUDGET_STOP"
    assert events(orch, "budget")[0].startswith("BUDGET_STOP total budget")


def test_stop_file_is_stopped(tmp_path):
    root = make_project(tmp_path, phases_basic())
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    (root / ".agent" / "STOP").write_text("", encoding="utf-8")
    assert "STOP file" in orch.run()
    assert orch.state.get_meta("outcome") == "STOPPED"
    assert events(orch, "run_done")[0].startswith("STOPPED stopped by")
    assert not events(orch, "budget")


def test_outcome_word_rules():
    assert outcome_word("", False, Stop("the service is down", fatal=True, word="STALLED")) == "STALLED"
    assert outcome_word("", False, Stop("login ran out", fatal=True)) == "FAILED"
    assert outcome_word("", True, Stop("session limit reached (1)")) == "BUDGET_STOP"
    assert outcome_word("", True, Stop("stopped by .agent/STOP file", word="STOPPED")) == "STOPPED"
    assert outcome_word("fatal: invalid plan", True) == "FAILED"
    assert outcome_word("crashed: ValueError (see x)", False) == "FAILED"
    assert outcome_word("plan complete", True) == "BLOCKED"
    assert outcome_word("app complete", False) == "VERIFIED"
    assert outcome_word("plan complete (audit found no actionable gaps)", False) == "VERIFIED"
    assert outcome_word("stalled: 2 tasks wait on skipped or blocked work", False) == "STALLED"


def test_new_run_clears_the_word_and_title_without_word(tmp_path):
    root = make_project(tmp_path, phases_basic())
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch.state.set_meta("outcome", "FAILED")
    orch.run()
    assert orch.state.get_meta("outcome") == "VERIFIED"
    plan = Plan.load(root / ".agent" / "plan.yaml")
    line = status_line(orch.cfg, plan, orch.state, {"status": "finished"})
    assert line.startswith("Done │")  # an older run.json without `word` keeps the plain head


def test_status_prints_outcome_only_when_set(tmp_path, capsys):
    root = make_project(tmp_path, phases_basic())
    assert cli_main(["status", "-C", str(root)]) == 0
    assert "outcome:" not in capsys.readouterr().out
    state = State(root / ".agent" / "state.db")
    state.set_meta("outcome", "BLOCKED")
    state.db.close()
    assert cli_main(["status", "-C", str(root)]) == 0
    assert "outcome: BLOCKED" in capsys.readouterr().out


def test_interrupted_run_is_stopped(tmp_path):
    root = make_project(tmp_path, phases_basic())
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    def boom():
        raise KeyboardInterrupt
    orch.loop = boom
    try:
        orch._run()
    except KeyboardInterrupt:
        pass
    assert orch.state.get_meta("outcome") == "STOPPED"
    assert events(orch, "run_end") == ["STOPPED interrupted"]
    assert run_journal(root)["word"] == "STOPPED"


def test_dashboard_data_and_bar_carry_the_word(tmp_path):
    from autopilot.dash_term import normalize, status_bar
    from autopilot.dashboard import dashboard_data
    root = make_project(tmp_path, phases_basic())
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch.reload_plan()
    run = {"status": "finished", "word": "BUDGET_STOP", "updated_at": "2026-10-11T12:50:09"}
    data = dashboard_data(orch.cfg, orch.plan, orch.state, run)
    assert data["project"]["word"] == "BUDGET_STOP"
    bar = status_bar(normalize(data), 160, False)
    assert "Stopped BUDGET_STOP" in bar or ("stopped" in bar and "BUDGET_STOP" in bar)
