"""P2 reliability: resume a failed attempt's session, stream-json stuck detection, structured output, max turns."""
from autopilot.backends import SessionRequest, SessionResult, since
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project
from test_backend import stub_claude

NO_AUDIT = {"audit": {"completion_audit": False}}
ONE_TASK = [{"id": "P01", "title": "One", "tasks": [{"id": "P01-T01", "title": "a", "risk": "medium"}]}]


def test_since_keeps_only_this_runs_share():
    base = {"cost": 1.0, "usage": {"sonnet": {"input": 100, "output": 10, "cost": 1.0}}, "num_turns": 5, "duration_ms": 9}
    tot = {"cost": 1.5, "usage": {"sonnet": {"input": 160, "output": 30, "cost": 1.5}, "haiku": {"input": 7, "cost": 0.1}},
           "num_turns": 8, "duration_ms": 4}
    assert since(tot, base) == {"cost": 0.5, "usage": {"sonnet": {"input": 60, "output": 20, "cost": 0.5},
                                                      "haiku": {"input": 7, "cost": 0.1}},
                                "num_turns": 3, "duration_ms": 0}


def test_build_cmd_resume_flag(tmp_path):
    b = ClaudeCLIBackend(Config.load(tmp_path))
    cmd = b.build_cmd(SessionRequest(prompt="x", model="sonnet", cwd=".", resume="abc"))
    assert cmd[cmd.index("--resume") + 1] == "abc"
    assert "--resume" not in b.build_cmd(SessionRequest(prompt="x", model="sonnet", cwd="."))


def test_resumed_cli_run_reports_only_its_own_cost(tmp_path, monkeypatch):
    body = ("print(json.dumps({'result': 'ok', 'session_id': 's1', 'total_cost_usd': 3.0, 'num_turns': 9,"
            " 'modelUsage': {'sonnet': {'inputTokens': 500, 'costUSD': 3.0}}}))\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    base = {"cost": 2.0, "usage": {"sonnet": {"input": 400, "cost": 2.0}}, "num_turns": 6}
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(
        SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path), resume="s1", resume_totals=base))
    assert res.ok and res.cost == 1.0 and res.num_turns == 3 and res.usage["sonnet"]["input"] == 100
    assert res.totals["cost"] == 3.0  # the next resume subtracts from the whole-session figure


class Resumable(FakeBackend):
    """Attempt 1 breaks the build; the retry must continue its session. Records every request."""
    supports_resume = True

    def __init__(self, behaviours, resume_fails=False):
        super().__init__(behaviours)
        self.reqs, self.resume_fails = [], resume_fails

    def run(self, req):
        self.reqs.append(req)
        if req.resume and self.resume_fails:
            return SessionResult(ok=False, error="No conversation found with session ID")
        res = super().run(req)
        n = len(self.reqs)
        res.session_id, res.totals = "sess-1", {"cost": 0.25 * n, "usage": {}, "num_turns": n, "duration_ms": 0}
        return res


def test_retry_resumes_failed_session_on_same_model(tmp_path):
    root = make_project(tmp_path, ONE_TASK, NO_AUDIT)
    fake = Resumable({"P01-T01": ["break", "ok"]})
    assert Orchestrator(root, backend=fake, sleep=lambda s: None).run() == "plan complete"
    first, second = fake.reqs
    assert not first.resume and first.prompt.startswith("# Assignment: implement task P01-T01")
    assert second.resume == "sess-1" and second.resume_totals["cost"] == 0.25
    assert second.prompt.startswith("# Assignment (continued): implement task P01-T01")
    assert "failed verification" in second.prompt and "## Project brain" not in second.prompt


def test_retry_on_a_new_model_starts_fresh(tmp_path):
    phases = [{"id": "P01", "title": "One", "tasks": [{"id": "P01-T01", "title": "a", "risk": "low"}]}]  # haiku->sonnet
    root = make_project(tmp_path, phases, NO_AUDIT)
    fake = Resumable({"P01-T01": ["break", "ok"]})
    assert Orchestrator(root, backend=fake, sleep=lambda s: None).run() == "plan complete"
    assert [r.resume for r in fake.reqs] == ["", ""] and fake.reqs[1].model == "sonnet"


def test_lost_session_falls_back_to_a_fresh_prompt(tmp_path):
    root = make_project(tmp_path, ONE_TASK, NO_AUDIT)
    fake = Resumable({"P01-T01": ["break", "ok"]}, resume_fails=True)
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert [bool(r.resume) for r in fake.reqs] == [False, True, False]
    assert orch.state.task("P01-T01")["attempts"] == 2  # the lost resume didn't cost an attempt


def test_resume_can_be_turned_off(tmp_path):
    root = make_project(tmp_path, ONE_TASK, {**NO_AUDIT, "retries": {"resume": False}})
    fake = Resumable({"P01-T01": ["break", "ok"]})
    assert Orchestrator(root, backend=fake, sleep=lambda s: None).run() == "plan complete"
    assert [r.resume for r in fake.reqs] == ["", ""]


def test_backend_without_resume_support_never_resumes(tmp_path):
    root = make_project(tmp_path, ONE_TASK, NO_AUDIT)
    assert Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).can_resume is False
