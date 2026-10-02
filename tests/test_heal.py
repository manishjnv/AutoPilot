"""Self-healing: outages of the machinery (CLI, login, network) are healed and retried, never counted as attempts;
broken plans, state databases, config and project environments are repaired instead of stopping the run."""
from pathlib import Path

from autopilot.backends import SessionRequest, SessionResult, detect_infra
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project, phases_basic
from test_backend import stub_claude

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}


class Outage(FakeBackend):
    """The first `n` sessions hit an infra failure of `kind`, then everything works."""

    def __init__(self, kind, n):
        super().__init__()
        self.kind, self.n = kind, n

    def run(self, req):
        if self.n:
            self.n -= 1
            return SessionResult(ok=False, error=f"{self.kind} trouble", infra=self.kind)
        return super().run(req)


def test_an_outage_is_retried_and_never_counts_as_an_attempt(tmp_path):
    sleeps = []
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], BASE), backend=Outage("network", 3),
                        sleep=sleeps.append)
    assert orch.run() == "plan complete"
    assert orch.state.task("P01-T01")["attempts"] == 1 and sleeps[:3] == [60, 300, 900]
    heals = [e["message"] for e in orch.state.events(100) if e["kind"] == "heal"]
    assert any("unreachable" in h for h in heals) and any("run again after 3" in h for h in heals)


def test_lost_login_tells_the_owner_how_to_fix_it(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], BASE), backend=Outage("auth", 1),
                        sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert any("/login" in e["message"] for e in orch.state.events(100) if e["kind"] == "heal")


def test_the_stop_file_ends_a_heal_wait(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], BASE)

    def sleep(_):
        (root / ".agent" / "STOP").write_text("stop")
    orch = Orchestrator(root, backend=Outage("network", 99), sleep=sleep)
    assert orch.run() == "stopped by .agent/STOP file"


def test_a_broken_plan_is_restored_from_git(tmp_path):
    from test_autopilot import git
    root = make_project(tmp_path, phases_basic()[:1], BASE)
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    (root / ".agent" / "plan.yaml").write_text("phases: [unclosed\n")  # a bad hand edit
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert (root / ".agent" / "logs" / "plan.yaml.broken").read_text() == "phases: [unclosed\n"
    assert any("restored the version from commit" in e["message"] for e in orch.state.events(100))


def test_a_corrupt_state_database_is_restored_and_recovered_from_git(tmp_path):
    from autopilot.state import State
    root = make_project(tmp_path, phases_basic()[:1], BASE)
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"  # both tasks done and merged; the run start took a backup (no tasks yet)
    orch.state.close()
    db = root / ".agent" / "state.db"
    for extra in ("-wal", "-shm"):
        (root / ".agent" / f"state.db{extra}").unlink(missing_ok=True)
    db.write_bytes(b"this is not a database" * 100)
    orch2 = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch2.state.healed and "restored the backup" in orch2.state.healed
    assert orch2.run() == "plan complete"
    assert orch2.state.task("P01-T01")["note"] == "recovered from git after a state restore"  # not built twice
    assert not [c for c in orch2.backend.calls if c[0].startswith("P01-")]
    assert list((root / ".agent").glob("state.db-corrupt-*")) and isinstance(State(db), State)


def test_deploy_enabled_without_a_command_is_switched_off_not_fatal(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], {**BASE, "deploy": {"staging": {"enabled": True}}}),
                        backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert any("staging deploys are off" in e["message"] for e in orch.state.events(50) if e["kind"] == "heal")


def _tool_cmd(marker):
    """A check that fails like a missing tool unless `marker` exists."""
    return (f"python -c \"import os,sys; ok=os.path.exists(r'{marker}'); "
            f"print('' if ok else 'mytool: command not found'); sys.exit(0 if ok else 127)\"")


def test_a_tool_that_vanished_is_reinstalled_by_setup_not_blamed_on_the_task(tmp_path):
    marker = tmp_path / "tool-installed"
    cfg = {**BASE, "commands": {"setup": [f"python -c \"open(r'{marker}', 'w').close()\""],
                                "lint": [_tool_cmd(marker)]}}

    class VenvBreaks(FakeBackend):
        def run(self, req):
            marker.unlink(missing_ok=True)  # e.g. the agent recreated the virtualenv
            return super().run(req)
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], cfg), backend=VenvBreaks(), sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert orch.state.task("P01-T01")["attempts"] == 1 and not orch.env_repair_tried


def test_a_broken_environment_gets_one_repair_session(tmp_path):
    cfg = {**BASE, "commands": {"setup": ["python -c \"import os,sys; sys.exit(0 if os.path.exists('requirements.txt') else 1)\""],
                                "lint": [_tool_cmd("requirements.txt")]}}

    class Repairs(FakeBackend):
        repairs = 0

        def run(self, req):
            if req.prompt.startswith("# Assignment: repair the project's environment"):
                Repairs.repairs += 1
                (Path(req.cwd) / "requirements.txt").write_text("mytool\n")
                if self.sneaky:  # a repair that also slips in app code is thrown away whole
                    (Path(req.cwd) / "src").mkdir(exist_ok=True)
                    (Path(req.cwd) / "src" / "backdoor.py").write_text("x = 1\n")
                return SessionResult(ok=True, report={"status": "done", "summary": "declared mytool", "rca": {
                    "symptom": "mytool missing", "root_cause": "not declared", "fix": "requirements.txt:1",
                    "prevention": "declare tools"}})
            return super().run(req)
    for sneaky in (False, True):
        Repairs.repairs, Repairs.sneaky = 0, sneaky
        (tmp_path / str(sneaky)).mkdir()
        root = make_project(tmp_path / str(sneaky), phases_basic()[:1], cfg)
        orch = Orchestrator(root, backend=Repairs(), sleep=lambda s: None)
        outcome = orch.run()
        assert Repairs.repairs == 1
        if not sneaky:
            assert outcome == "plan complete" and orch.state.task("P01-T01")["attempts"] == 1  # lost attempt not counted
            assert (root / "requirements.txt").exists() and "repair project environment" in (root / "docs" / "RCA.md").read_text()
        else:
            assert not (root / "src" / "backdoor.py").exists() and not (root / "requirements.txt").exists()
            assert any("not a tooling or dependency file: src/backdoor.py" in e["message"]
                       for e in orch.state.events(200) if e["kind"] == "heal")


def test_env_problem_ignores_ordinary_test_failures(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], {**BASE, "commands": {"test": ["python -m pytest -q"]}}),
                        backend=FakeBackend(), sleep=lambda s: None)
    assert orch.env_problem("/usr/bin/python: No module named pytest")
    assert orch.env_problem("'ruff' is not recognized as an internal or external command")
    assert not orch.env_problem("E   ModuleNotFoundError: No module named 'myapp.utils'")  # the agent's own code
    assert not orch.env_problem("FAILED tests/test_x.py::test_y - AssertionError")


TWO_INDEPENDENT = [{"id": "P01", "title": "One", "tasks": [
    {"id": "P01-T01", "title": "a", "risk": "low"}, {"id": "P01-T02", "title": "b", "risk": "low"}]}]


def crashing(root, where, times):
    """An orchestrator factory whose `where` ('task' = inside P01-T01, 'loop' = between tasks) raises `times` times."""
    left = [times]

    class Crashy(Orchestrator):
        def execute_task(self, task):
            if where == "task" and task.id == "P01-T01" and left[0]:
                left[0] -= 1
                raise RuntimeError("boom in a task")
            return super().execute_task(task)

        def close_finished_phases(self):
            if where == "loop" and left[0]:
                left[0] -= 1
                raise KeyError("boom between tasks")
            return super().close_finished_phases()
    return lambda: Crashy(root, backend=FakeBackend(), sleep=lambda s: None)


def test_a_crash_writes_a_report_and_restarts_from_state(tmp_path):
    from autopilot.orchestrator import run_supervised
    root = make_project(tmp_path, TWO_INDEPENDENT, BASE)
    sleeps = []
    assert run_supervised(root, crashing(root, "task", 1), sleep=sleeps.append) == "plan complete"
    reports = list((root / ".agent" / "logs" / "crashes").glob("*.md"))
    assert len(reports) == 1 and sleeps == [60]
    text = reports[0].read_text()
    assert "RuntimeError: boom in a task" in text and "Task in flight: P01-T01" in text and "Signature:" in text


def test_the_same_crash_three_times_in_a_task_parks_only_that_task(tmp_path):
    from autopilot.orchestrator import run_supervised
    from autopilot.state import State
    root = make_project(tmp_path, TWO_INDEPENDENT, BASE)
    outcome = run_supervised(root, crashing(root, "task", 99), sleep=lambda s: None)
    state = State(root / ".agent" / "state.db")
    assert state.task("P01-T02")["status"] == "done"  # the rest of the plan was built
    assert state.task("P01-T01")["status"] == "blocked" and "crashed 3 times" in state.task("P01-T01")["last_error"]
    assert outcome.startswith("stalled")  # the parked task now waits on a NEEDS-YOU decision


def test_a_repeating_crash_outside_any_task_ends_with_the_report(tmp_path):
    from autopilot.orchestrator import run_supervised
    root = make_project(tmp_path, TWO_INDEPENDENT, BASE)
    outcome = run_supervised(root, crashing(root, "loop", 99), sleep=lambda s: None)
    assert outcome.startswith("crashed: KeyError") and ".agent/logs/crashes/" in outcome


def test_infra_is_read_from_the_cli_messages_only():
    assert detect_infra("Invalid API key · Please run /login") == "auth"
    assert detect_infra("API Error: Connection error.") == "network"
    assert detect_infra("request to https://api.anthropic.com failed, reason: getaddrinfo ENOTFOUND") == "network"
    assert detect_infra("API Error: 503 upstream unavailable") == "network"
    assert detect_infra("I added retry logic for ECONNRESET and an Invalid API key message") == ""  # prose
    assert detect_infra("tests failed") == ""


def test_a_cli_that_prints_nothing_is_an_infra_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, ""))  # seen: a broken npm install
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert not res.ok and res.infra == "cli" and res.error
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", str(tmp_path / "missing"))
    assert ClaudeCLIBackend(Config.load(tmp_path)).run(
        SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path))).infra == "cli"
