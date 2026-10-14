"""W46: a session ends at its final answer; a background job it left running ends with it."""
import time

from autopilot.backends import SessionRequest
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config
from autopilot.proc import pid_alive
from test_backend import stub_claude

RESULT = "print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'all done'}), flush=True)\n"


def run(tmp_path, monkeypatch, body):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    t = time.monotonic()
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    return res, time.monotonic() - t


def test_session_is_ended_at_its_final_answer_with_its_child(tmp_path, monkeypatch):
    pidfile = tmp_path / "child.pid"
    body = (RESULT + "import subprocess, sys, time\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
            "time.sleep(60)\n")
    res, secs = run(tmp_path, monkeypatch, body)
    assert res.ok and res.text == "all done" and not res.timed_out and not res.stuck and secs < 15
    pid = int(pidfile.read_text())
    for _ in range(50):
        if not pid_alive(pid):
            break
        time.sleep(0.1)
    assert not pid_alive(pid)


def test_session_that_exits_by_itself_is_unchanged(tmp_path, monkeypatch):
    res, secs = run(tmp_path, monkeypatch, RESULT)
    assert res.ok and res.text == "all done" and secs < 10
