"""W18a: the watch screen shows what the run waits for and ticks while it works."""
import argparse
import io
import json
import os
import re
import time
from types import SimpleNamespace

from autopilot import cli
from autopilot.backends import SessionRequest, claude_cli
from autopilot.cli import main as cli_main
from autopilot.dash_term import frame
from autopilot.dashboard import dashboard_data, spinner
from autopilot.orchestrator import Orchestrator
from autopilot.state import now
from test_autopilot import FakeBackend, make_project, phases_basic
from test_dash_term import data as term_data

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}
SLOW = "python -c \"import time; time.sleep(1.2)\""
ONE = [{"id": "P01", "title": "One", "tasks": [{"id": "P01-T01", "title": "a", "risk": "low"}]}]


def built(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.run()
    return orch


def test_run_file_holds_the_gate_line_while_a_slow_test_runs(tmp_path, monkeypatch):
    """Every `current` written to run.json is recorded at the write (a file poll misses the short `gate: merge`)."""
    root = make_project(tmp_path, ONE, {**BASE, "commands": {"test": [SLOW]}})
    seen, real = [], Orchestrator._journal

    def journal(self, **kw):
        real(self, **kw)
        if "current" in kw:
            seen.append((kw["current"], json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8")).get("current")))
    monkeypatch.setattr(Orchestrator, "_journal", journal)
    Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run()
    texts = [c for c, _ in seen]
    assert any(x.startswith("gate: tests (python") for x in texts), texts
    assert "gate: merge" in texts
    assert all(c == on_disk for c, on_disk in seen if c.startswith("gate:"))  # the run file holds the line


def test_a_fake_runner_streaming_every_2_s_keeps_heartbeat_at_moving(tmp_path, monkeypatch):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    clock, stamps = [0.0], []

    def stream(cmd, on_line=None, **kw):
        for _ in range(11):  # one event every 2 s for 20 s
            clock[0] += 2
            on_line('{"type":"system"}\n')
        return SimpleNamespace(stdout="", stderr="", rc=0, ended=False, timed_out=False, stopped="")
    monkeypatch.setattr(claude_cli, "stream_proc", stream)
    monkeypatch.setattr(claude_cli, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    req = SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path),
                         on_event=lambda: (stamps.append(clock[0]), orch._journal(heartbeat_at=now())))
    claude_cli.ClaudeCLIBackend(orch.cfg).run(req)
    assert stamps == [2.0, 12.0, 22.0]  # at most one stamp every 10 s
    run = json.loads((orch.ad / "run.json").read_text(encoding="utf-8"))
    assert run["heartbeat_at"] and "updated_at" not in run  # a heartbeat is not a change of the data


def test_a_heartbeat_40_s_old_shows_the_pause_and_a_fresh_one_keeps_it_turning():
    t = 1_000_000.0
    d = term_data()
    d["asof"] = {"age": 5, "live": True, "mtime": t - 600, "pulse": t - 40, "stopped": "", "wait_text": ""}
    sp = spinner(d, d["asof"]["mtime"], t)
    assert sp["kind"] == "stale" and "no change 40s" in sp["text"]
    assert spinner({**d, "asof": {**d["asof"], "pulse": t - 5}}, t - 600, t)["kind"] == "run"  # the heartbeat, not the file
    d["spin"] = sp
    assert "no change 40s" in "\n".join(frame(d, 133, 37, False))
    gate = spinner({**d, "asof": {**d["asof"], "wait_text": "gate: tests (pytest -q)"}}, t - 600, t)
    assert gate["kind"] == "stale" and "gate: tests (pytest -q)" in gate["text"] and "no change" not in gate["text"]


def test_elapsed_and_the_waiting_line_tick_on_the_window_clock():
    t = 1_000_000.0
    d = term_data()
    d["project"].update(since_ts=t - 125, wait={"text": "Bash (pytest -q)", "since": t - 190, "secs": 190})
    d["asof"] = {"age": 1, "live": True, "mtime": t - 1, "pulse": t - 1, "stopped": ""}
    d["spin"] = {"kind": "run", "text": "⠋", "age": 1, "clock": t, "data_age": 1}
    one = "\n".join(frame(d, 133, 37, False))
    d["spin"] = {**d["spin"], "clock": t + 5}
    two = "\n".join(frame(d, 133, 37, False))
    assert "Elapsed  : 2m05s" in one and "Elapsed  : 2m10s" in two
    assert "Waiting for: Bash" in one and "3m 10s" in one and "3m 15s" in two  # the long line wraps in the panel


def test_the_error_carries_its_age_and_goes_dim_after_a_good_session(tmp_path):
    orch = built(tmp_path)
    orch.state.set_task("P02-T01", status="pending", last_error="boom: the test failed")
    run = {"status": "running", "state": "Code", "task": "P02-T01", "attempt": 1, "pid": os.getpid()}
    p = dashboard_data(orch.cfg, orch.plan, orch.state, run)["project"]
    assert p["error_age"].endswith(" ago") and not p["error_old"]
    plain = "\n".join(frame(dashboard_data(orch.cfg, orch.plan, orch.state, run), 133, 37, False))
    assert re.search(r"Error\s+: \d+m ago: boom", plain)
    orch.state.db.execute("INSERT INTO sessions(kind, ok, ended_at) VALUES('task', 1, '2999-01-01T00:00:00')")
    assert dashboard_data(orch.cfg, orch.plan, orch.state, run)["project"]["error_old"] is True


def test_the_version_and_the_run_number_show(tmp_path, capsys):
    orch = built(tmp_path)
    capsys.readouterr()
    cli_main(["status", "-C", str(orch.root)])
    first = capsys.readouterr().out.splitlines()[0]
    assert re.match(r"Autopilot \d+\.\d+\.\d+ \(\w+\)", first)
    run = json.loads((orch.ad / "run.json").read_text(encoding="utf-8"))
    assert run["version"].startswith("Autopilot ")
    d = dashboard_data(orch.cfg, orch.plan, orch.state, {"status": "finished"})
    assert re.match(r"Run 1 \(since \d\d:\d\d\)$", d["project"]["run_line"]) and d["project"]["version"] == run["version"]
    plain = "\n".join(frame(d, 133, 37, False))
    assert "Autopilot " in plain and "Run 1 (since" in plain


class Tty(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return True


def watch(tmp_path, monkeypatch, sizes, env_no_color=True):
    orch = built(tmp_path)
    run_file = orch.ad / "run.json"
    out = Tty()
    monkeypatch.setattr(cli.sys, "stdout", out)
    monkeypatch.setattr(cli, "enable_vt", lambda: True)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.delenv("AUTOPILOT_PLAIN", raising=False)
    if env_no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    calls = [0]

    def size_fn():
        calls[0] += 1
        if calls[0] >= 6:  # the build ends
            run_file.write_text(json.dumps({**json.loads(run_file.read_text(encoding="utf-8")), "status": "finished"}))
        return os.terminal_size(sizes(calls[0]))
    args = argparse.Namespace(path=str(orch.root), simple=False, detail=False, scroll=False, hold=False, lines=20,
                              size_fn=size_fn)
    assert cli.cmd_watch(args) == 0
    return out.getvalue()


def test_watch_with_no_color_draws_the_panels_in_bold_and_dim_only(tmp_path, monkeypatch):
    text = watch(tmp_path, monkeypatch, lambda n: (133, 37))
    plain = re.sub(r"\[[0-9;?]*[a-zA-Z]", "", text)
    assert "┌─ Project" in plain and "Widen the window" not in plain
    assert not re.search(r"\x1b\[(3[0-7]|9[0-7]|1;36)m", text)  # no colour code at all
    assert "\x1b[2m" in text  # dim


def test_a_small_window_that_grows_gets_the_panels_on_the_next_tick(tmp_path, monkeypatch):
    text = watch(tmp_path, monkeypatch, lambda n: (80, 20) if n <= 1 else (133, 37))
    plain = re.sub(r"\[[0-9;?]*[a-zA-Z]", "", text)
    assert plain.index("Widen the window for the panels.") < plain.index("┌─ Project")
