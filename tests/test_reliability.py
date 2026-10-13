"""P2 reliability: resume a failed attempt's session, stream-json stuck detection, structured output, max turns."""
import json
import sys
import time

from autopilot.backends import SessionRequest, SessionResult, since
from autopilot.backends.claude_cli import ClaudeCLIBackend, first_session_id, result_event, stuck_watch
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from autopilot.proc import stream_proc
from autopilot.schemas import REPORTS
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
    root = make_project(tmp_path, phases, {**NO_AUDIT, "models": {"ladder": {"low": ["haiku", "sonnet", "opus"]}}})
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


# ---------------------------------------------------------------- stream-json + stuck detection
def tool_line(name="Bash", **inp):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})


def test_stuck_watch_needs_consecutive_repeats():
    w = stuck_watch(4)
    for cmd in ["ls", "ls", "ls", "pytest", "ls", "ls", "ls"]:
        assert w(tool_line(command=cmd)) == ""
    assert "repeated the same action 4 times" in w(tool_line(command="ls"))
    off = stuck_watch(0)
    assert all(off(tool_line(command="ls")) == "" for _ in range(10))


def test_repeated_final_report_is_not_stuck(tmp_path, monkeypatch):
    assert all(stuck_watch(4)(tool_line("StructuredOutput", status="done")) == "" for _ in range(6))
    line = tool_line("StructuredOutput", status="done")
    body = ("print(json.dumps({'type': 'system', 'session_id': 'sx'}), flush=True)\n"
            f"for _ in range(4): print({line!r}, flush=True)\n"
            "print(json.dumps({'type': 'result', 'result': '', 'session_id': 'sx', "
            "'structured_output': {'status': 'done', 'summary': 'x'}}), flush=True)\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert res.ok and not res.stuck and res.report.get("status") == "done"


def test_system_prompt_asks_for_one_final_report():
    from autopilot.context import PROMPTS
    assert "Call the final report once, at the end." in (PROMPTS / "system.md").read_text(encoding="utf-8")


def test_result_event_is_the_last_result_line():
    raw = "\n".join([json.dumps({"type": "system", "subtype": "init", "session_id": "s9"}), tool_line(command="ls"),
                     json.dumps({"type": "result", "result": "fine", "session_id": "s9"}), "trailing noise"])
    assert result_event(raw)["result"] == "fine" and first_session_id(raw) == "s9"
    assert result_event('{"result": "plain json mode"}')["result"] == "plain json mode"
    assert result_event("not json") == {}


def test_stream_proc_kills_when_on_line_says_so(tmp_path):
    script = "import sys,time\nfor i in range(1000):\n    print(i, flush=True)\n    time.sleep(0.01)\n"
    seen = []
    t0 = time.time()
    p = stream_proc([sys.executable, "-c", script], input="ignored", timeout=60,
                    on_line=lambda line: seen.append(line) or ("enough" if len(seen) == 3 else ""))
    assert p.stopped == "enough" and time.time() - t0 < 30 and p.stdout.startswith("0\n1\n2\n")


def test_stuck_session_is_killed_and_logged(tmp_path, monkeypatch):
    line = tool_line(command="npm test")
    body = (f"print(json.dumps({{'type': 'system', 'session_id': 'sx'}}), flush=True)\n"
            f"for _ in range(4): print({line!r}, flush=True)\n"
            "import time; time.sleep(60)\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    log = tmp_path / "s.log"
    t0 = time.time()
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(
        SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path), log_path=str(log)))
    assert time.time() - t0 < 45
    assert not res.ok and res.stuck and "npm test" in res.error and res.session_id == "sx"
    assert log.read_text(encoding="utf-8").count('"tool_use"') == 4


def test_stuck_attempt_goes_straight_to_unstick(tmp_path):
    root = make_project(tmp_path, ONE_TASK, NO_AUDIT)

    class Looper(FakeBackend):
        def run(self, req):
            if "implement task P01-T01" in req.prompt and not any(c[0] == "P01-T01" for c in self.calls):
                self.calls.append(("P01-T01", req.model))
                return SessionResult(ok=False, error="stuck: the agent repeated the same action 4 times", stuck=True)
            return super().run(req)

    fake = Looper()
    assert Orchestrator(root, backend=fake, sleep=lambda s: None).run() == "plan complete"
    assert [c[0] for c in fake.calls] == ["P01-T01", "unstick", "P01-T01"]  # unstick after ONE attempt, not two


# ---------------------------------------------------------------- structured output (--json-schema)
def test_schemas_are_consistent():
    for kind, s in REPORTS.items():
        assert s["type"] == "object" and set(s["required"]) <= set(s["properties"]), kind
        json.dumps(s)


def test_json_schema_flag_except_on_cmd_shim(tmp_path, monkeypatch):
    req = SessionRequest(prompt="x", model="sonnet", cwd=".", schema=REPORTS["task"])
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", "/usr/bin/claude")
    cmd = ClaudeCLIBackend(Config.load(tmp_path)).build_cmd(req)
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == REPORTS["task"]
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", "C:/x/claude.cmd")
    assert "--json-schema" not in ClaudeCLIBackend(Config.load(tmp_path)).build_cmd(req)


def test_structured_output_wins_over_text(tmp_path, monkeypatch):
    out = {"type": "result", "result": 'prose ```json\n{"status": "blocked"}\n```',
           "structured_output": {"status": "done", "summary": "validated"}}
    body = f"print({json.dumps(out)!r})\n"
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert res.report == {"status": "done", "summary": "validated"}


def test_each_session_kind_gets_its_schema(tmp_path):
    root = make_project(tmp_path, ONE_TASK)  # completion audit on

    class Recorder(FakeBackend):
        kinds = []

        def run(self, req):
            Recorder.kinds.append(req.schema)
            return super().run(req)

    assert Orchestrator(root, backend=Recorder(), sleep=lambda s: None).run() == "app complete"
    assert Recorder.kinds == [REPORTS["task"], REPORTS["audit"]]


# ---------------------------------------------------------------- --max-turns
def test_max_turns_flag(tmp_path):
    req = SessionRequest(prompt="x", model="sonnet", cwd=".")
    cmd = ClaudeCLIBackend(Config.load(tmp_path)).build_cmd(req)
    assert cmd[cmd.index("--max-turns") + 1] == "200"  # default
    cfg = Config.load(tmp_path)
    cfg.data["agent"]["max_turns"] = 0
    assert "--max-turns" not in ClaudeCLIBackend(cfg).build_cmd(req)


def test_turn_limit_is_a_clear_failure(tmp_path, monkeypatch):
    out = [{"type": "system", "subtype": "init", "session_id": "s1"},
           {"type": "result", "subtype": "error_max_turns", "session_id": "s1", "num_turns": 200, "total_cost_usd": 1.5}]
    body = "".join(f"print({json.dumps(e)!r})\n" for e in out)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert not res.ok and res.error.startswith("error_max_turns") and res.cost == 1.5 and res.num_turns == 200
    assert "session_id" not in res.text  # the event stream never leaks into text / error


# ---------- P10-T07: git discard survives a Windows file lock ----------
class _P:
    def __init__(self, rc=0, err=""):
        self.returncode, self.stderr, self.stdout = rc, err, ""


def _fake_git(tmp_path, monkeypatch, fail):
    """Git whose _git returns fail(args, n) -> _P; records every call."""
    from autopilot.gitops import Git
    g, calls = Git(tmp_path), []
    monkeypatch.setattr(g, "_git", lambda args: calls.append(list(args)) or fail(list(args), len(calls)))
    return g, calls


def test_discard_retries_once_on_lock(tmp_path, monkeypatch, caplog):
    hard = []

    def fail(a, n):
        if "--hard" in a:
            hard.append(a)
            return _P(1, "error: unable to unlink '.agent/plan.yaml': Permission denied") if len(hard) == 1 else _P()
        return _P()
    g, _ = _fake_git(tmp_path, monkeypatch, fail)
    with caplog.at_level("WARNING", logger="autopilot"):
        g.discard(sleep=lambda s: None)
    assert len(hard) == 2 and len([r for r in caplog.records if "retry" in r.message]) == 1


def test_discard_falls_back_after_three_locks(tmp_path, monkeypatch):
    def fail(a, n):
        return _P(1, "Unlink of file '.agent/plan.yaml' failed") if "--hard" in a else _P()
    g, calls = _fake_git(tmp_path, monkeypatch, fail)
    g.discard(sleep=lambda s: None)
    assert sum("--hard" in c for c in calls) == 3
    assert any(":(exclude).agent" in c for c in calls) and any("-e" in c and ".agent" in c for c in calls)


def test_discard_other_git_error_raises(tmp_path, monkeypatch):
    import pytest
    from autopilot.gitops import GitError
    g, _ = _fake_git(tmp_path, monkeypatch, lambda a, n: _P(128, "fatal: not a git repository"))
    with pytest.raises(GitError):
        g.discard(sleep=lambda s: None)
