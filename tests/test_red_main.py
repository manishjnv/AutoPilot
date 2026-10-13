"""W21: a red main is detected once per commit and stops the run before the next task; the test is named."""
from pathlib import Path

from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project, phases_basic

RED_CMD = ("python -c \"import pathlib,sys; b=pathlib.Path('BROKEN').exists(); "
           "print('FAILED tests/test_demo.py::test_broken' if b else 'ok'); sys.exit(1 if b else 0)\"")
CFG = {"commands": {"test": [RED_CMD]}, "unstick": {"enabled": False}, "decide": {"enabled": False},
       "retries": {"max_fixer_attempts": 1}, "audit": {"completion_audit": False}}


class GivesUp(FakeBackend):
    """Fixers give up and a corrective task reports blocked; every other session behaves as usual."""

    def run(self, req):
        if "repair the main branch" in req.prompt:
            self.calls.append(("fixer", req.model))
            return SessionResult(ok=True, cost=0.1, report={"status": "done", "summary": "could not"})
        if "implement task FIX" in req.prompt:
            self.calls.append(("FIX", req.model))
            return SessionResult(ok=True, cost=0.1, report={"status": "blocked", "blocker": "cannot fix"})
        return super().run(req)


def orch_for(root, fake=None):
    return Orchestrator(root, backend=fake or FakeBackend(), sleep=lambda s: None)


def one_task_done(tmp_path):
    root = make_project(tmp_path, phases_basic(), CFG)
    Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None, max_sessions=1).run()
    return root


def events(orch, kind):
    return [e["message"] for e in orch.state.events(300) if e["kind"] == kind]


def test_red_main_at_start_stops_naming_the_test(tmp_path):
    root = one_task_done(tmp_path)
    (root / "BROKEN").write_text("breakage introduced outside autopilot")
    fake = GivesUp()
    orch = orch_for(root, fake)
    out = orch.run()
    assert out.startswith("main is red") and "tests/test_demo.py::test_broken" in out
    assert orch.state.get_meta("outcome") == "FAILED"
    assert not any(c[0] in ("P01-T02", "P02-T01") for c in fake.calls)


def test_commit_that_turns_main_red_stops_the_next_task(tmp_path):
    root = make_project(tmp_path, phases_basic(), CFG)
    fake = GivesUp()
    orch = orch_for(root, fake)
    real = orch._commit_main

    def commit(message):
        if "merge" not in message and orch.state.task("P01-T02")["status"] == "done":  # the phase-close commit
            (root / "BROKEN").write_text("x")
        real(message)

    orch._commit_main = commit
    out = orch.run()
    assert out.startswith("main is red") and "tests/test_demo.py::test_broken" in out
    assert any("test_broken" in m for m in events(orch, "main_red"))
    assert "P01-T02" in [c[0] for c in fake.calls] and "P02-T01" not in [c[0] for c in fake.calls]


def test_same_sha_is_tested_once_and_merges_do_not_set_main_due(tmp_path):
    root = one_task_done(tmp_path)
    orch = orch_for(root)
    calls = []
    real = orch._red_test
    orch._red_test = lambda cwd: (calls.append(cwd), real(cwd))[1]
    orch.main_results.clear()
    orch.main_due = True
    orch.guard_main()
    orch.guard_main()
    assert len(calls) == 1 and orch.main_due is False
    assert orch.main_test() is None and len(calls) == 1
    orch.git.run("checkout", "-q", "-b", "autopilot/x")
    (Path(root) / "x.txt").write_text("x")
    orch.git.run("add", "-A")
    orch.git.run("commit", "-q", "-m", "x")
    orch.git.merge("autopilot/x", "main", "[autopilot] merge x")
    assert orch.main_due is False
