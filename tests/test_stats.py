"""M3: `autopilot stats`, the publishable numbers of a run."""
from autopilot.cli import main as cli_main
from autopilot.orchestrator import Orchestrator
from autopilot.report import proof_stats
from test_autopilot import FakeBackend, make_project, phases_basic

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


def test_stats_after_a_run(tmp_path, capsys):
    root = make_project(tmp_path, phases_basic()[:1], BASE)
    orch = Orchestrator(root, backend=FakeBackend({"P01-T01": ["break", "ok"]}), sleep=lambda s: None)
    orch.run()
    out = proof_stats(orch.cfg, orch.plan, orch.state)
    assert "| Tasks finished | 2 of 2 (100%) |" in out
    assert "| Passed the gate on the first try | 1 of 2 (50%) |" in out  # P01-T01 needed a retry
    assert "| Tasks stuck (blocked) | 0 |" in out and "| Owner: hours spent | (fill in) |" in out
    assert "Wall-clock" in out and out.rstrip().splitlines()[-1].startswith("Tokens:")
    assert cli_main(["stats", "-C", str(root)]) in (0, None) and "Tasks finished" in capsys.readouterr().out


def test_stats_before_any_run(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.reload_plan()
    out = proof_stats(orch.cfg, orch.plan, orch.state)
    assert "| Tasks finished | 0 of 3 (0%) |" in out and "| Agent sessions | 0 |" in out and "? |" in out
