"""W37: a run.json that says `running` with a dead pid shows DEAD, not ON; the run writes a heartbeat."""
import json
import os
import subprocess
import sys
import time

from autopilot.dashboard import dashboard_data
from autopilot.orchestrator import Orchestrator
from autopilot.proc import pid_alive
from autopilot.report import next_steps, run_alive, status_line
from test_autopilot import FakeBackend, make_project, phases_basic

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


def exited_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def project(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.reload_plan()
    return orch


def running(**kw):
    return {"status": "running", "state": "Code", "updated_at": "2026-10-13T15:28:40", "git": "OK", "build": "OK", **kw}


def test_pid_alive_knows_itself_a_dead_child_and_a_missing_pid(tmp_path):
    assert pid_alive(os.getpid())
    assert not pid_alive(exited_pid())
    assert pid_alive(None) and pid_alive("x")


def test_dead_pid_gives_dead_since_the_time_of_the_last_beat(tmp_path):
    run = running(pid=exited_pid(), beat_at="2026-10-13T15:31:02")
    assert run_alive(run) == (False, "15:31")
    assert run_alive({**run, "beat_at": ""}) == (False, "15:28")


def test_dead_run_shows_dead_since_and_ap_start(tmp_path):
    orch = project(tmp_path)
    line = status_line(orch.cfg, orch.plan, orch.state, running(pid=exited_pid(), beat_at="2026-10-13T15:31:02"))
    assert line.startswith("DEAD since 15:31")
    assert "ON" not in line.split("│")[0]
    tips = next_steps(orch.cfg.root, run_alive(running(pid=exited_pid()))[0])
    assert tips[0].startswith("ap start")
    data = dashboard_data(orch.cfg, orch.plan, orch.state, running(pid=exited_pid(), beat_at="2026-10-13T15:31:02"))
    assert data["asof"]["live"] is False and data["asof"]["dead_since"] == "15:31"
    assert data["line"].startswith("DEAD since 15:31")


def test_live_pid_and_no_pid_still_show_on(tmp_path):
    orch = project(tmp_path)
    for run in (running(pid=os.getpid()), running()):
        assert status_line(orch.cfg, orch.plan, orch.state, run).startswith("ON")
        assert dashboard_data(orch.cfg, orch.plan, orch.state, run)["asof"]["live"] is True


def test_heartbeat_writes_beat_at_and_leaves_updated_at(tmp_path):
    orch = project(tmp_path)
    orch._journal(status="running", pid=os.getpid())
    path = orch.ad / "run.json"
    before = json.loads(path.read_text(encoding="utf-8"))
    orch.beat_interval = 0.05
    orch._start_heartbeat()
    try:
        for _ in range(100):
            time.sleep(0.05)
            after = json.loads(path.read_text(encoding="utf-8"))
            if after.get("beat_at"):
                break
    finally:
        orch._beat_stop.set()
    assert after["beat_at"] and after["status"] == "running"
    assert after["updated_at"] == before["updated_at"]
    assert after["beat_at"] >= before["updated_at"]
