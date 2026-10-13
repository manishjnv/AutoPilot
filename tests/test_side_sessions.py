"""W26: decide sessions only for critical tasks by default; replans on Sonnet unless a pending task is load-bearing."""
from autopilot import config
from autopilot.orchestrator import Orchestrator
from test_autopilot import make_project
from test_decide import Recorder, phases

CFG = {"audit": {"completion_audit": False}}  # no decide key: the template default applies


def go(tmp_path, plan, cfg=None):
    root = make_project(tmp_path, plan, {**CFG, **(cfg or {})})
    fake = Recorder()
    return fake, Orchestrator(root, backend=fake, sleep=lambda s: None)


def test_template_defaults():
    assert config.defaults()["decide"]["risks"] == ["critical"]
    assert config.defaults()["models"]["replanner"] == "sonnet"


def test_high_task_runs_no_decide_session(tmp_path):
    fake, orch = go(tmp_path, phases({"risk": "high"}))
    assert orch.run() == "plan complete"
    assert "decide" not in [c[0] for c in fake.calls]


def test_critical_task_still_decides(tmp_path):
    fake, orch = go(tmp_path, phases({"risk": "critical"}))
    assert orch.run() == "plan complete"
    assert [c[0] for c in fake.calls if c[0] == "decide"] == ["decide"]


def _replan_models(tmp_path, scope):
    fake, orch = go(tmp_path, phases({"risk": "low", "files_in_scope": scope}),
                    {"escalate": {"load_bearing": ["src/auth/**"]}})
    orch.run()  # makes the first commit on main
    orch.state.set_task("P01-T01", status="pending")
    orch.replan("test")
    return [c[1] for c in fake.calls if c[0] == "replan"]


def test_replan_model_follows_load_bearing(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert _replan_models(tmp_path / "a", ["src/auth/login.py"]) == ["opus"]
    assert _replan_models(tmp_path / "b", ["src/docs/x.md"]) == ["sonnet"]
