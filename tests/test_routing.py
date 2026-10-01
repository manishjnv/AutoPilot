"""U5 role-based routing (model + effort per role) and U6 signal-based escalation."""
from pathlib import Path

from autopilot.backends import SessionResult
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator, model_rank
from test_autopilot import FakeBackend, make_project, phases_basic

NO_AUDIT = {"audit": {"completion_audit": False}}
NO_DECIDE = {"decide": {"enabled": False}}


class Recorder(FakeBackend):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.reqs = []

    def run(self, req):
        self.reqs.append(req)
        return super().run(req)


def one_phase(*risks):
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"t{i}", "risk": r} for i, r in enumerate(risks, 1)]}]


def run(tmp_path, phases, fake=None, cfg=None):
    root = make_project(tmp_path, phases, {**NO_DECIDE, **(cfg or {})})
    fake = fake or Recorder()
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    return orch, orch.run(), fake


# ---------------------------------------------------------------- U5
def test_task_effort_follows_risk_and_audit_runs_high(tmp_path):
    orch, outcome, fake = run(tmp_path, one_phase("low", "medium", "high", "critical"))
    assert outcome == "app complete"
    tasks = [(r.model, r.effort) for r in fake.reqs if "implement task" in r.prompt]
    assert tasks == [("haiku", "low"), ("sonnet", "medium"), ("opus", "medium"), ("opus", "high")]
    audit = [r for r in fake.reqs if "implementation audit" in r.prompt][0]
    assert audit.model == "opus" and audit.effort == "high"


def test_role_effort_can_be_blanked(tmp_path):
    _, _, fake = run(tmp_path, one_phase("low"), cfg={**NO_AUDIT, "models": {"effort": {"low": ""}}})
    assert fake.reqs[0].effort == ""  # falls back to agent.effort / the CLI default in the backend


def test_subagent_model_env_is_opt_in(tmp_path):
    cfg = Config.load(tmp_path)
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in ClaudeCLIBackend(cfg).env()
    cfg.data["models"]["subagent"] = "haiku"
    assert ClaudeCLIBackend(cfg).env()["CLAUDE_CODE_SUBAGENT_MODEL"] == "haiku"


def test_model_rank():
    assert [model_rank(m) for m in ("haiku", "claude-sonnet-5-5", "OPUS", "my-litellm-model")] == [0, 1, 2, 1]


# ---------------------------------------------------------------- U6
class Behave(Recorder):
    """Per attempt of P01-T01: 'timeout', 'big' (many files, then fail the gate), or a FakeBackend action."""

    def __init__(self, actions):
        super().__init__()
        self.actions = actions

    def run(self, req):
        self.reqs.append(req)
        if "implement task P01-T01" in req.prompt:
            n = sum(1 for r in self.reqs if "implement task P01-T01" in r.prompt) - 1
            act = self.actions[min(n, len(self.actions) - 1)]
            if act == "timeout":
                self.calls.append(("P01-T01", req.model))
                return SessionResult(ok=False, error="session timed out after 1s", timed_out=True)
            if act == "big":
                self.calls.append(("P01-T01", req.model))
                for i in range(7):
                    (Path(req.cwd) / f"big{i}.txt").write_text("x\n")
                (Path(req.cwd) / "BROKEN").write_text("x")
                return SessionResult(ok=True, report={"status": "done", "summary": "big"})
            self.behaviours["P01-T01"] = [act]
        return FakeBackend.run(self, req)


def models_used(fake):
    return [r.model for r in fake.reqs if "implement task P01-T01" in r.prompt]


def test_timeout_skips_to_a_stronger_model(tmp_path):
    _, _, fake = run(tmp_path, one_phase("medium"), Behave(["timeout", "ok"]), NO_AUDIT)
    assert models_used(fake) == ["sonnet", "opus"]  # ladder says sonnet again; the timeout escalates


def test_large_failed_change_escalates(tmp_path):
    _, _, fake = run(tmp_path, one_phase("medium"), Behave(["big", "ok"]), NO_AUDIT)
    assert models_used(fake) == ["sonnet", "opus"]


def test_small_failure_follows_the_ladder(tmp_path):
    _, _, fake = run(tmp_path, one_phase("medium"), Behave(["break", "ok"]), NO_AUDIT)
    assert models_used(fake) == ["sonnet", "sonnet"]


def test_escalation_can_be_turned_off(tmp_path):
    cfg = {**NO_AUDIT, "escalate": {"on_timeout": False, "max_diff_lines": 0, "max_diff_files": 0}}
    _, _, fake = run(tmp_path, one_phase("medium"), Behave(["timeout", "ok"]), cfg)
    assert models_used(fake) == ["sonnet", "sonnet"]


def test_load_bearing_scope_uses_the_high_ladder(tmp_path):
    phases = [{"id": "P01", "title": "One", "tasks": [
        {"id": "P01-T01", "title": "auth", "risk": "low", "files_in_scope": ["src/auth/**"]}]}]
    _, _, fake = run(tmp_path, phases, Behave(["ok"]), {**NO_AUDIT, "escalate": {"load_bearing": ["src/auth/**"]}})
    assert models_used(fake) == ["opus"] and fake.reqs[0].effort == "medium"  # high ladder + high-risk effort


def test_never_route_down_after_failing_higher(tmp_path):
    root = make_project(tmp_path, one_phase("low"), {**NO_DECIDE, **NO_AUDIT})
    orch = Orchestrator(root, backend=Recorder(), sleep=lambda s: None)
    assert orch.model_for("low", 0) == "haiku"
    assert orch.model_for("low", 0, floor=model_rank("opus")) == "opus"
    assert orch.model_for("critical", 5, floor=3) == "opus"  # nothing stronger: the strongest on the ladder


def test_fixer_single_model_still_works(tmp_path):
    root = make_project(tmp_path, phases_basic(), {**NO_DECIDE, "models": {"fixer": "opus"}})
    first = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None, max_sessions=1)
    first.run()
    (root / "BROKEN").write_text("x")
    fake = FakeBackend()
    Orchestrator(root, backend=fake, sleep=lambda s: None).run()
    assert ("fixer", "opus") in fake.calls
