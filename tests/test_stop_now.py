"""W39: `ap stop --now` ends the task session at once, keeps its files on the task branch and the next start resumes."""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from autopilot import proc
from autopilot.backends import SessionResult
from autopilot.cli import main as cli_main
from autopilot.orchestrator import OWNER_RESUME, Orchestrator
from test_autopilot import make_project
from test_reliability import NO_AUDIT, ONE_TASK, Resumable

SLEEPER = ("import pathlib, time\n"
           "p = pathlib.Path('src'); p.mkdir(exist_ok=True)\n"
           "(p / 'fake_example.py').write_text('x = 1\\n')\n"
           "time.sleep(120)\n")


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def sleeper_project(tmp_path):
    script = tmp_path / "fake_agent.py"
    script.write_text(SLEEPER)
    cmd = f'"{sys.executable}" "{script}"'
    return make_project(tmp_path, ONE_TASK, {**NO_AUDIT, "agent": {"backend": "command", "command": cmd}})


def stop_when_written(root, args):
    """Wait for the fake agent's file, then run `ap stop` with `args`; returns the time of the stop."""
    at = []

    def go():
        for _ in range(600):
            if (root / "src" / "fake_example.py").exists():
                break
            time.sleep(0.1)
        at.append(time.monotonic())
        cli_main(["stop", "-C", str(root), *args])

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t, at


class Recorder(Resumable):
    """Records each prompt and whether the cut session's file is on disk when the session starts."""

    def __init__(self, behaviours):
        super().__init__(behaviours)
        self.had_file = []

    def run(self, req):
        self.had_file.append((Path(req.cwd) / "src" / "fake_example.py").exists())
        return super().run(req)


def test_run_proc_ends_at_once_when_the_armed_check_fires(tmp_path):
    t0 = time.monotonic()
    with proc.stop_when(lambda: True):
        p = proc.run_proc([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path)
    assert p.stopped == proc.OWNER_STOP and time.monotonic() - t0 < 30
    assert proc._STOP_CHECK is None  # disarmed after the block


def test_stop_now_ends_the_run_keeps_the_files_and_the_next_start_resumes(tmp_path):
    root = sleeper_project(tmp_path)
    orch = Orchestrator(root, sleep=lambda s: None)
    t, at = stop_when_written(root, ["--now"])
    outcome = orch.run()
    took = time.monotonic() - at[0]
    t.join(5)
    assert took < 30, took
    assert (root / ".agent" / "STOP").read_text().strip() == "now"
    assert json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8"))["word"] == "STOPPED"
    assert "stopped by the owner" in outcome
    row = orch.state.task("P01-T01")
    assert row["attempts"] == 0 and row["status"] == "pending" and row["note"] == "cut by the owner, resume"
    shown = git(root, "show", "autopilot/P01-T01:src/fake_example.py")
    assert shown.returncode == 0 and "x = 1" in shown.stdout
    orch.state.db.close()

    (root / ".agent" / "STOP").unlink()
    fake = Recorder({"P01-T01": ["ok"]})
    nxt = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert nxt.run() == "plan complete"
    assert fake.had_file[0] and OWNER_RESUME in fake.reqs[0].prompt
    assert nxt.state.task("P01-T01")["attempts"] == 1
    assert "x = 1" in git(root, "show", "main:src/fake_example.py").stdout


def test_a_stop_in_a_continued_session_still_keeps_the_files(tmp_path):
    """The owner stops the retry that continues attempt 1's session: no fresh fallback session, the files are kept."""
    root = make_project(tmp_path, ONE_TASK, NO_AUDIT)

    class CutOnResume(Resumable):
        def run(self, req):
            if not req.resume:
                return super().run(req)
            self.reqs.append(req)
            (Path(req.cwd) / "src").mkdir(exist_ok=True)
            (Path(req.cwd) / "src" / "fake_example.py").write_text("x = 1\n")
            (Path(req.cwd) / ".agent" / "STOP").write_text("now\n")
            assert proc._STOP_CHECK()  # the armed check sees the STOP file, as proc's watcher would
            return SessionResult(ok=False, error=proc.OWNER_STOP)  # killed: no turns reported

    fake = CutOnResume({"P01-T01": ["break", "ok"]})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert "stopped by the owner" in orch.run()
    assert [bool(r.resume) for r in fake.reqs] == [False, True]  # no fresh session after the cut
    row = orch.state.task("P01-T01")
    assert row["attempts"] == 1 and row["note"] == "cut by the owner, resume"
    assert git(root, "show", "autopilot/P01-T01:src/fake_example.py").returncode == 0


def test_a_second_stop_within_60_seconds_counts_as_now(tmp_path, capsys):
    root = make_project(tmp_path, ONE_TASK, NO_AUDIT)
    stop = root / ".agent" / "STOP"
    (root / ".agent" / "run.json").write_text(json.dumps({"session_at": "2026-10-14T10:00:00"}))
    cli_main(["stop", "-C", str(root)])
    assert stop.read_text().strip() == "stop requested"
    out = capsys.readouterr().out
    assert "the current session has run" in out and "`ap stop --now`" in out
    cli_main(["stop", "-C", str(root)])
    assert stop.read_text().strip() == "now"
    old = time.time() - 120
    stop.write_text("stop requested\n")
    os.utime(stop, (old, old))
    cli_main(["stop", "-C", str(root)])  # the first stop was over 60 s ago: still a plain stop
    assert stop.read_text().strip() == "stop requested"


def test_claude_session_stopped_by_the_owner_is_not_stuck(tmp_path, monkeypatch):
    from autopilot.backends import SessionRequest
    from autopilot.backends.claude_cli import ClaudeCLIBackend
    from autopilot.config import Config
    from test_backend import stub_claude
    body = ("print(json.dumps({'type': 'system', 'session_id': 'sx'}), flush=True)\n"
            "import time; time.sleep(60)\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    t0 = time.monotonic()
    with proc.stop_when(lambda: True):
        res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert time.monotonic() - t0 < 30
    assert res.error == proc.OWNER_STOP and not res.ok and not res.stuck and res.session_id == "sx"
