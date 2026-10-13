import sys
import os
import time

import pytest

from autopilot import proc
from autopilot.proc import exclusive_lock, run_proc, safe_env

PY = sys.executable


def test_utf8_roundtrip():
    p = run_proc([PY, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], input="⚠ ⚑ ✓ — ok")
    assert p.rc == 0 and p.stdout == "⚠ ⚑ ✓ — ok"


def test_timeout_kills_whole_tree():
    # the child starts a grandchild that would hold the output pipes for 60s
    code = (f"import subprocess; subprocess.Popen([{PY!r}, '-c', 'import time; time.sleep(60)']); "
            "import time; time.sleep(60)")
    t0 = time.time()
    p = run_proc([PY, "-c", code], timeout=2)
    assert p.timed_out and p.rc == 124
    assert time.time() - t0 < 25


def test_missing_program_raises_oserror():
    with pytest.raises(OSError):
        run_proc(["definitely-not-a-real-program-xyz"])


def test_exclusive_lock(tmp_path):
    path = tmp_path / "run.lock"
    with exclusive_lock(path):
        with pytest.raises(BlockingIOError):
            with exclusive_lock(path):
                pass
    with exclusive_lock(path):  # released after the first holder exits
        pass


def test_safe_env_drops_secrets(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TG_TOKEN", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    env = safe_env(passthrough=["DATABASE_URL"], extra={"FOO": 1})
    assert "AUTOPILOT_TG_TOKEN" not in env
    assert env["DATABASE_URL"] == "postgres://x" and env["ANTHROPIC_API_KEY"] == "k" and env["FOO"] == "1"


def test_python_tool_folders_are_on_path_for_checks_and_sessions(monkeypatch, tmp_path):
    from autopilot import proc
    tools = tmp_path / "Scripts"
    tools.mkdir()
    monkeypatch.setattr(proc, "python_tool_dirs", lambda: [str(tools)])
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    env = proc.safe_env()
    key = next(k for k in env if k.upper() == "PATH")
    assert env[key].split(os.pathsep) == [str(tmp_path / "bin"), str(tools)]
    assert proc.with_tool_dirs(env)[key] == env[key]  # added once, never twice


def _grandchild_run(tmp_path):
    pidfile = tmp_path / "gc.pid"
    child = ("import os, subprocess, sys, time; "
             f"g = subprocess.Popen([{PY!r}, '-c', 'import time; time.sleep(60)']); "
             f"open({str(pidfile)!r}, 'w').write(str(g.pid)); time.sleep(60)")
    p = run_proc([PY, "-c", child], timeout=3)
    return p, int(pidfile.read_text())


def _gone(pid):
    for _ in range(50):
        if not proc.pid_alive(pid):
            return True
        time.sleep(0.2)
    return False


def test_timeout_ends_the_grandchild(tmp_path):
    p, gc = _grandchild_run(tmp_path)
    assert p.timed_out
    assert _gone(gc)
    if proc.WINDOWS:
        started = proc.subprocess.Popen([PY, "-c", "import time; time.sleep(5)"])
        try:
            proc._attach_job(started)
            assert started._ap_job
            proc._kill_tree(started)
            assert started.wait(timeout=10) is not None
        finally:
            proc._close_job(started)
            assert started._ap_job is None


def test_job_failure_keeps_the_timeout_path(monkeypatch, tmp_path):
    def boom(p):
        raise OSError("no job")
    monkeypatch.setattr(proc, "_make_job", boom)
    monkeypatch.setattr(proc, "_job_warned", False)
    p = run_proc([PY, "-c", "import time; time.sleep(60)"], timeout=1)
    assert p.timed_out and p.rc == 124
