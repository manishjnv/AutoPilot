"""G8: one status line that is always on screen and always current (run, watch, page, status)."""
import datetime as dt
import io
import json
import os
import shutil
from pathlib import Path

from autopilot import cli
from autopilot.backends import SessionRequest
from autopilot.backends.claude_cli import ClaudeCLIBackend, usage_meter
from autopilot.cli import StatusBar
from autopilot.cli import main as cli_main
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from autopilot.report import status_line
from test_autopilot import FakeBackend, make_project, phases_basic
from test_backend import stub_claude
from test_window import Metered, tasks

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


class Usage(FakeBackend):
    """Task sessions that report tokens and the CLI's usage figure, like real ones."""

    def run(self, req):
        res = super().run(req)
        res.usage = {"claude-sonnet-5-5": {"input": 1000, "output": 500, "cache_read": 100000, "cache_write": 0, "cost": 0.25}}
        res.window = {"five_hour": {"pct": 0.4, "reset": dt.datetime.now().timestamp() + 3600}, "status": "allowed"}
        return res


def built(tmp_path, fake=None):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=fake or FakeBackend(), sleep=lambda s: None)
    orch.run()
    return orch


def running(**kw):
    started = (dt.datetime.now() - dt.timedelta(hours=3, minutes=24, seconds=5)).isoformat(timespec="seconds")
    return {"status": "running", "started_at": started, "state": "Code", "task": "P02-T01", "attempt": 2,
            "max_attempts": 3, "git": "OK", "build": "OK", **kw}


def test_status_line_shows_state_task_progress_cost_window_and_health(tmp_path):
    orch = built(tmp_path, Usage())
    line = status_line(orch.cfg, orch.plan, orch.state, running(), width=200)
    assert line.startswith("ON 3h24m │ Code │ P02-T01 Try 2/3 │ Task 3/3 100% │ Ph 2/2 │ Blk 0 │ Tok 30")
    assert line.endswith("│ Son 100% │ Cost $0.75 │ Win 40% │ Git OK Bld OK")


def test_narrow_terminals_drop_the_least_important_parts_first(tmp_path):
    orch = built(tmp_path, Usage())
    line = status_line(orch.cfg, orch.plan, orch.state, running(), width=200)
    for part in ("Git OK", "3h24m", "Son ", "Cost ", "Tok ", "Win ", "P02-T01"):  # the order they go in
        assert part in line
        line = status_line(orch.cfg, orch.plan, orch.state, running(), width=len(line) - 1)
        assert part not in line
    assert line == "ON │ Code │ Task 3/3 100% │ Ph 2/2 │ Blk 0"  # state, tasks, phases and blocked never go
    assert status_line(orch.cfg, orch.plan, orch.state, running(), width=5) == line


def test_status_line_for_no_run_a_waiting_run_and_a_finished_run(tmp_path):
    orch = built(tmp_path)
    idle = status_line(orch.cfg, orch.plan, orch.state, {}, width=200)
    assert idle.startswith("Idle │ Task 3/3 100% │ Ph 2/2 │ Blk 0")
    waiting = status_line(orch.cfg, orch.plan, orch.state, running(state="Wait", task=""), width=200)
    assert waiting.startswith("ON 3h24m │ Wait │ Task 3/3")
    done = status_line(orch.cfg, orch.plan, orch.state, {"status": "finished", "state": "Done"}, width=200)
    assert done.startswith("Done │ Task 3/3") and "Git" not in done  # no health for a run that is over


def test_tokens_of_the_session_in_flight_are_added(tmp_path):
    orch = built(tmp_path)  # the fake backend reports no tokens
    assert "Tok 5k" in status_line(orch.cfg, orch.plan, orch.state, running(live_tokens=5000), width=200)


# ---- the run keeps run.json current: that is what every view reads ----

def test_the_run_journal_says_state_task_try_and_health_while_a_session_runs(tmp_path):
    seen = []

    class Peek(FakeBackend):
        def run(self, req):
            req.on_tokens(5000)  # what the backend does as the stream arrives
            seen.append(json.loads((Path(req.cwd) / ".agent" / "run.json").read_text(encoding="utf-8")))
            return super().run(req)
    root = make_project(tmp_path, phases_basic(), BASE)
    orch = Orchestrator(root, backend=Peek({"P01-T01": ["break", "ok"]}), sleep=lambda s: None)
    orch.run()
    first, second = seen[0], seen[1]
    assert (first["state"], first["task"], first["attempt"], first["max_attempts"]) == ("Code", "P01-T01", 1, 3)
    assert (first["git"], first["build"], first["live_tokens"]) == ("OK", "OK", 5000)
    assert second["attempt"] == 2
    final = json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8"))
    assert final["state"] == "Done" and final["live_tokens"] == 0 and final["task"] == ""


def test_the_journal_moves_through_code_test_and_commit(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], BASE), backend=FakeBackend(), sleep=lambda s: None)
    states, journal = [], orch._journal

    def spy(**kw):
        if kw.get("state"):
            states.append(kw["state"])
        journal(**kw)
    orch._journal = spy
    orch.run()
    assert states[:3] == ["Code", "Test", "Commit"] and states[-1] == "Done"


def test_a_pause_shows_as_wait(tmp_path):
    seen = []
    orch = Orchestrator(make_project(tmp_path, tasks(3), BASE), backend=Metered([0.5, 0.86, 0.1]),
                        sleep=lambda s: seen.append(orch.run_info.get("state")))
    orch.run()
    assert seen == ["Wait"] and orch.run_info["state"] == "Done"


# ---- tokens while a session runs ----

def test_usage_meter_counts_tokens_as_the_stream_arrives():
    def msg(mid, tokens):
        return json.dumps({"type": "assistant", "message": {"id": mid, "usage": {
            "input_tokens": tokens, "output_tokens": 5, "cache_read_input_tokens": 100}}})
    feed = usage_meter()
    assert feed(msg("m1", 10)) == 115
    assert feed(msg("m1", 10)) == 115  # one message split over several events: counted once
    assert feed(msg("m2", 20)) == 240
    assert feed("not json") == 240 and feed(json.dumps({"type": "result"})) == 240


def test_backend_reports_tokens_while_the_session_runs(tmp_path, monkeypatch):
    body = ("print(json.dumps({'type': 'assistant', 'message': {'id': 'm1', 'usage': "
            "{'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100}}}))\n"
            "print(json.dumps({'type': 'result', 'result': 'done'}))\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    seen = []
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(
        SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path), on_tokens=seen.append))
    assert res.ok and seen == [115]


# ---- the pinned bottom row ----

class Tty(io.StringIO):
    def isatty(self):
        return True


def screen(monkeypatch, cols=80, rows=24):
    monkeypatch.setattr(cli, "enable_vt", lambda: True)
    monkeypatch.setattr(shutil, "get_terminal_size", lambda *a, **k: os.terminal_size((cols, rows)))
    monkeypatch.delenv("AUTOPILOT_PLAIN", raising=False)


def test_status_bar_pins_the_line_to_the_bottom_row_and_cleans_up(monkeypatch):
    screen(monkeypatch)
    out = Tty()
    bar = StatusBar(lambda width: "ON │ Code │ Task 1/3", out=out, every=0)  # every=0: no thread, drawn by hand
    assert bar.start() is True
    assert "\x1b[1;23r" in out.getvalue()  # rows 1..23 scroll; row 24 is kept for the line
    bar.draw()
    assert "\x1b7\x1b[24;1H\x1b[2KON │ Code │ Task 1/3\x1b8" in out.getvalue()  # cursor saved, row drawn, cursor back
    assert "\x1b]0;ON │ Code │ Task 1/3\x07" in out.getvalue()  # and the window title
    bar.stop()
    assert out.getvalue().endswith("\x1b[r\x1b[24;1H\x1b[2K")  # scrolling is whole again, the row is cleared


def test_status_bar_refits_when_the_window_is_resized(monkeypatch):
    screen(monkeypatch)
    out = Tty()
    bar = StatusBar(lambda width: "x" * 200, out=out, every=0)
    bar.start()
    screen(monkeypatch, cols=40, rows=10)
    bar.draw()
    tail = out.getvalue().split("\x1b[1;23r")[-1]
    assert "\x1b[1;9r" in tail and "\x1b[10;1H\x1b[2K" + "x" * 39 + "\x1b8" in tail  # new region, line cut to fit
    bar.stop()


def test_status_bar_is_silent_without_a_terminal_or_when_plain(monkeypatch):
    screen(monkeypatch)
    pipe = io.StringIO()  # a log file, a pipe, systemd: no escape codes ever
    bar = StatusBar(lambda width: "ON", out=pipe, every=0)
    assert bar.start() is False
    bar.draw()
    bar.stop()
    assert pipe.getvalue() == ""
    monkeypatch.setenv("AUTOPILOT_PLAIN", "1")
    tty = Tty()
    assert StatusBar(lambda width: "ON", out=tty, every=0).start() is False and tty.getvalue() == ""


def test_a_failing_line_never_breaks_the_bar(monkeypatch):
    screen(monkeypatch)
    out = Tty()
    bar = StatusBar(lambda width: 1 / 0, out=out, every=0)
    bar.start()
    before = out.getvalue()
    bar.draw()  # must not raise
    assert out.getvalue() == before
    bar.stop()


def test_control_characters_in_the_line_never_reach_the_terminal(monkeypatch):
    screen(monkeypatch)
    out = Tty()
    bar = StatusBar(lambda width: "ON │ P01\x1b[2J-T01\x07 Try\n1/3", out=out, every=0)  # e.g. an odd task id
    bar.start()
    before = len(out.getvalue())
    bar.draw()
    drawn = out.getvalue()[before:]
    assert "\x1b7\x1b[24;1H\x1b[2KON │ P01[2J-T01 Try1/3\x1b8\x1b]0;ON │ P01[2J-T01 Try1/3\x07" == drawn
    bar.stop()


# ---- the same line in `status` and in a watch that is not a terminal ----

def test_status_command_starts_with_the_line(tmp_path, capsys):
    root = make_project(tmp_path, phases_basic(), BASE)
    capsys.readouterr()  # drop what `init` printed
    assert cli_main(["status", "-C", str(root)]) in (0, None)
    assert capsys.readouterr().out.splitlines()[0].startswith("Idle │ Task 0/3 0% │ Ph 0/2 │ Blk 0")
