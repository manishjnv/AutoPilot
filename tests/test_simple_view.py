"""Section J: a screen a beginner can read. J1 simple view, J2 the short `ap` command and a default project,
J3 color, J4 the status says "planning" while quickstart works."""
import io
import json
import os
import time
from pathlib import Path

import pytest

from autopilot import cli
from autopilot.cli import main as cli_main
from autopilot.orchestrator import Orchestrator
from autopilot.plain import SimpleView, colors_on, ending, paint, sentence, tint
from autopilot.report import status_panel, status_words
from test_autopilot import FakeBackend, make_project, phases_basic
from test_backend import stub_claude

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


def step(label, act, at="18:07:35"):
    return f"2026-10-03 {at} INFO   ▸ {label} · {act} · 0m17s"


# ---------------------------------------------------------------- J1: plain sentences
@pytest.mark.parametrize("act,text", [
    ("Write E:\\code\\x\\src\\csv2json\\cli.py", "Writes cli.py."),
    ("Edit /a/b/tests/test_cli.py", "Changes test_cli.py."),
    ("Read /a/.agent/BRAIN.md", "Reads BRAIN.md."),
    ('Bash cd "E:\\code\\x" && uv sync 2>&1', "Installs the tools."),
    ("Bash python -m pytest -q", "Runs the tests."),
    ("Bash ruff check .", "Checks the code style."),
    ("Bash ls -la && cat .agent/plan.yaml", "Reads the project files."),
    ("Bash frobnicate --all", "Runs a command."),  # never the raw command
    ("Grep def main", "Searches the project."),
    ("WebSearch csv rfc 4180", "Searches the web."),
    ("Quux something new", "Uses a tool."),
    ("StructuredOutput", "Writes its report."),
    ("Bash python - <<'EOF' p='tests/test_reader.py' s=open(p)", "Runs a short script."),
    ("Bash uv run pytest tests/test_writer.py -v", "Runs the tests."),
    ('"Now let me run all the checks to verify"', ""),  # the model's own talk is left out
])
def test_a_tool_call_becomes_one_short_sentence(act, text):
    assert sentence(act) == text


def test_simple_view_has_one_heading_and_a_goal_for_a_task():
    view = SimpleView({"P01-T01": (1, 13, "Project tooling and skeleton", "Make the package skeleton: (a) one, (b) two.  More text.")})
    label = "P01-T01 Project tooling and skeleton [haiku]"
    assert view.feed(step(label, "Write E:\\x\\pyproject.toml")) == [
        "", "Task 1 of 13: Project tooling and skeleton", "Goal: Make the package skeleton."]
    assert view.open_line() == "18:07  Writes pyproject.toml."  # the group in work, not final yet
    assert view.feed(step("writing PLAN.md", "Bash ls -la")) == ["18:07  Writes pyproject.toml.", "", "The plan"]
    assert view.feed(step("onboarding", "Write E:\\x\\.agent\\plan.yaml"))[:3] == [
        "18:07  Reads the project files.", "", "The task list"]
    assert view.feed(step("verify functional check P01 [sonnet]", "Bash ls"))[2] == "Test of the features"


def test_one_work_cycle_is_one_line():
    view = SimpleView({})
    label = "P01-T02 b [haiku]"
    out = view.feed(step(label, "Read /x/cli.py"))
    out += view.feed(step(label, "Read /x/files.py; Grep def main; Read /x/cli.py"))
    assert out == ["", "Task P01-T02: b"] and view.open_line() == "18:07  Reads 2 files: cli.py, files.py."
    assert view.feed(step(label, "Write /x/a.py")) == [] and view.open_line() == "18:07  Writes a.py."
    assert view.feed(step(label, "Edit /x/b.py; Edit /x/a.py")) == []
    assert view.open_line() == "18:07  Changes 2 files: a.py, b.py."
    assert view.feed(step(label, "Bash ruff check .; Bash mypy src; Bash pytest -q; Bash ruff check .")) == []
    cycle = "18:07  Changes 2 files: a.py, b.py. Checks the work: code style, types, tests."
    assert view.open_line() == cycle
    assert view.feed(step(label, "Bash pytest -q; echo done; grep x")) == []  # "; " inside a command is no new step
    assert view.feed(step(label, "Bash frobnicate")) == []  # says nothing new inside a cycle
    assert view.feed(step(label, "Edit /x/c.py", at="18:09:00")) == [cycle]  # a change after a check: the next cycle
    assert view.feed(step(label, "WebSearch x", at="18:09:30")) == ["18:09  Changes c.py."]
    assert view.close() == ["18:09  Searches the web."] and view.close() == [] and view.open_line() is None


def test_a_line_too_wide_for_the_window_loses_its_file_names():
    view = SimpleView({}, width=30)
    view.feed(step("P01-T02 b", "Read /x/a_long_file_name.py; Read /x/another_long_name.py"))
    assert view.open_line() == "18:07  Reads 2 files."
    view.width = 200
    assert view.open_line() == "18:07  Reads 2 files: a_long_file_name.py, another_long_name.py."


def test_simple_view_says_pass_fail_and_phase_end_in_plain_words():
    view = SimpleView({})
    assert view.feed("2026-10-03 18:09:00 INFO task P01-T01 attempt 1 failed: PROBLEM: skip marker") == [
        "18:09  The checks failed. Autopilot tries again."]
    assert view.feed("2026-10-03 18:10:00 INFO task P01-T01 done (haiku, $0.45)") == [
        "18:10  The task is complete. All checks passed. Attempts: 2."]
    assert view.feed("2026-10-03 18:11:00 INFO closing phase P01 (done)") == ["18:11  Phase P01 is complete."]
    assert view.feed("2026-10-03 18:11:00 INFO quality: P01-T01 · haiku · low · attempts 1") == []
    assert view.feed("not a log line at all") == []
    assert view.feed("2026-10-03 18:22:00 INFO [Autopilot · x] run_done: stopped by .agent/STOP file") == [
        "18:22  The build stopped. You asked for the stop."]


def test_the_result_line_of_a_task_has_files_time_and_attempts():
    view = SimpleView({})
    label = "P01-T03 c [haiku]"
    view.feed(step(label, "Write /x/a.py; Edit /x/b.py", at="23:58:00"))
    assert view.feed("2026-10-03 23:59:00 INFO task P01-T03 attempt 1 failed: tests") == [
        "23:58  Changes 2 files: a.py, b.py.", "23:59  The checks failed. Autopilot tries again."]
    view.feed(step(label, "Edit /x/a.py", at="23:59:30"))
    assert view.feed("2026-10-04 00:02:00 INFO task P01-T03 done (sonnet, $0.45)") == [
        "23:59  Changes a.py.",
        "00:02  The task is complete. All checks passed. Files changed: 2. Time: 4m. Attempts: 2."]


def test_the_last_line_says_how_the_build_ended():
    assert ending("plan complete") == "The build is complete."
    assert ending("stopped by .agent/STOP file") == "The build stopped. You asked for the stop."
    assert ending("budget reached") == "The build stopped. Reason: budget reached."


def test_status_in_words(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.run()
    assert status_words(orch.cfg, orch.plan, orch.state, {}) == "No build is active. 3 of 3 tasks complete. No problems."
    live = {"status": "running", "state": "Code", "task": "P02-T01", "attempt": 2, "max_attempts": 3}
    assert status_words(orch.cfg, orch.plan, orch.state, live).startswith(
        "Writes the code. Task 3 of 3, attempt 2. 3 of 3 tasks complete. No problems.")
    assert status_words(orch.cfg, orch.plan, orch.state, {"status": "running", "state": "Plan"}).startswith(
        "Makes the plan. ")
    assert status_words(orch.cfg, orch.plan, orch.state, {"status": "finished"}).startswith("Build complete. ")
    orch.state.set_task("P02-T01", status="pending")  # a build that stopped early must not say "complete"
    assert status_words(orch.cfg, orch.plan, orch.state, {"status": "finished"}).startswith("The build stopped. 2 of 3 ")


def watch(tmp_path, capsys, *flags):
    root = make_project(tmp_path, phases_basic())
    log = root / ".agent" / "logs" / "autopilot.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(step("P01-T01 a [haiku]", "Write E:\\x\\src\\x.py") + "\n", encoding="utf-8")
    (root / ".agent" / "run.json").write_text(json.dumps({"status": "finished", "outcome": "plan complete"}))
    capsys.readouterr()
    assert cli_main(["watch", "-C", str(root), *flags]) == 0
    return capsys.readouterr().out


def test_watch_simple_view_shows_sentences_and_detail_shows_the_log(tmp_path, capsys):
    out = watch(tmp_path, capsys, "--simple")
    assert "Task 1 of 3: a" in out and "Writes x.py." in out and "INFO" not in out and "[haiku]" not in out
    end = out[out.index("The build is complete."):]  # J8: the end message, then the status in short
    assert "Build: " in end and "Progress: Tasks 0/3 (0%)" in end and "Usage: " in end
    assert "\x1b" not in out  # not a terminal: no color codes


def test_watch_detail_keeps_the_technical_lines(tmp_path, capsys):
    out = watch(tmp_path, capsys, "--detail")
    assert "INFO" in out and "[haiku]" in out and "Write E:\\x\\src\\x.py" in out


# ---------------------------------------------------------------- J3: color
class Tty(io.StringIO):
    def isatty(self):
        return True


def test_color_only_on_a_terminal_and_never_when_the_user_says_no(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("AUTOPILOT_PLAIN", raising=False)
    monkeypatch.setattr(cli, "enable_vt", lambda: True)
    assert colors_on(Tty()) is True and colors_on(io.StringIO()) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert colors_on(Tty()) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("AUTOPILOT_PLAIN", "1")
    assert colors_on(Tty()) is False


def test_paint_and_colored_view():
    assert paint("ok", "green", True) == "\x1b[32mok\x1b[0m" and paint("ok", "green", False) == "ok"
    view = SimpleView({}, color=True)
    assert view.feed("2026-10-03 18:10:00 INFO task P01-T01 done (haiku, $0.45)")[0].count("\x1b[32m") == 1
    assert "\x1b[31m" in view.feed("2026-10-03 18:09:00 INFO task P01-T01 attempt 1 failed: x")[0]
    assert "\x1b[1" in view.feed(step("onboarding", "Read /x/PLAN.md"))[1]  # the heading stands out
    view = SimpleView({"P01-T01": (1, 3, "a", "Make a.")}, color=True)
    line = view.feed(step("P01-T01 a [haiku]", "Write /x/cli.py; Write /x/b.py; Bash ls"))
    assert line[1] == "\x1b[1;36mTask 1 of 3: \x1b[0m\x1b[1ma\x1b[0m"  # the count and the title differ
    assert line[2] == "\x1b[2mGoal: Make a.\x1b[0m"
    assert view.open_line() == "\x1b[2m18:07\x1b[0m  Changes 2 files: \x1b[36mcli.py\x1b[0m, \x1b[36mb.py\x1b[0m."  # time dim, files cyan


def test_each_fact_in_the_status_line_has_its_color():
    text = "Writes the code. Task 3 of 13, attempt 2. 2 of 13 tasks complete. 1 task is blocked. Time: 12m."
    assert tint(text, False) == text
    assert tint(text, True) == ("Writes the code. Task \x1b[1;36m3 of 13\x1b[0m, \x1b[33mattempt 2\x1b[0m. "
                                "\x1b[1;36m2 of 13\x1b[0m tasks complete. \x1b[31m1 task is blocked.\x1b[0m "
                                "\x1b[2mTime: 12m.\x1b[0m")
    assert tint("Build complete. 3 of 3 tasks complete. No problems.", True).count("\x1b[32m") == 2
    assert tint("Progress: 1/3 done · 0 blocked · 2 questions", True) == (
        "\x1b[1mProgress\x1b[0m: \x1b[1;36m1/3\x1b[0m done · 0 blocked · \x1b[33m2 questions\x1b[0m")
    assert tint("Build: Ph 1/2 · Try 2 │ Health: Git OK · Checks OK", True).count("\x1b[32mOK") == 2


def test_status_panel_has_short_words_and_uses_the_window_width(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.run()
    rows = status_panel(orch.cfg, orch.plan, orch.state, {})
    assert rows[0] == "Build: No build active" and rows[1] == "Progress: Tasks 3/3 (100%) · Phases 2/2 · 0 blocked · 0 questions"
    assert rows[2].startswith("Usage: ") and rows[2].endswith(f"${orch.state.cost():.2f}")
    assert len(rows) == 3  # no build: no health row
    live = {"status": "running", "state": "Code", "task": "P02-T01", "attempt": 2, "git": "OK", "build": "OK"}
    rows = status_panel(orch.cfg, orch.plan, orch.state, {**live, "context_tokens": 68000})
    assert rows[0] == "Build: Ph 2/2 · Task 3/3 · Writes the code · Try 2 · Context ███░░░░░ 34%"
    orch.state.set_meta("window_seen", {"five_hour": {"pct": 0.09, "reset": time.time() + 3600}, "seven_day": {"pct": 0.72}})
    assert status_panel(orch.cfg, orch.plan, orch.state, live)[2].startswith("Usage: 5h █░░░░░░░ 9% · Week ██████░░ 72% · ")
    rows = status_panel(orch.cfg, orch.plan, orch.state, live)
    assert rows[0] == "Build: Ph 2/2 · Task 3/3 · Writes the code · Try 2"
    assert rows[3].startswith("Health: Git OK · Checks OK")
    assert status_panel(orch.cfg, orch.plan, orch.state, {"status": "finished"})[0] == "Build: Complete"
    wide = status_panel(orch.cfg, orch.plan, orch.state, live, width=200)  # a wide window: categories side by side
    assert len(wide) < 4 and wide[0].startswith(rows[0] + " │ Progress: Tasks 3/3 (100%)")
    assert len(status_panel(orch.cfg, orch.plan, orch.state, live, width=40)) == 4


def test_status_bar_with_four_rows(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_PLAIN", raising=False)
    monkeypatch.setattr(cli, "enable_vt", lambda: True)
    monkeypatch.setattr(cli.shutil, "get_terminal_size", lambda *a: os.terminal_size((80, 24)))
    out = Tty()
    bar = cli.StatusBar(lambda width: "a\nb\nc\nd", out=out, every=0, height=4, title=lambda: "the title")
    assert bar.start() is True and "\x1b[1;20r" in out.getvalue()  # rows 1..20 scroll; rows 21..24 are the panel
    bar.draw()
    assert "\x1b7\x1b[21;1H\x1b[2Ka\x1b[22;1H\x1b[2Kb\x1b[23;1H\x1b[2Kc\x1b[24;1H\x1b[2Kd\x1b8" in out.getvalue()
    assert "\x1b]0;the title\x07" in out.getvalue()
    bar.stop()
    assert out.getvalue().endswith("\x1b[r\x1b[24;1H\x1b[2K\x1b[23;1H\x1b[2K\x1b[22;1H\x1b[2K\x1b[21;1H\x1b[2K")


# ---------------------------------------------------------------- J2: `ap`, and a project without -C
def test_ap_is_a_second_name_for_the_same_program():
    text = Path("pyproject.toml").read_text(encoding="utf-8")  # no tomllib: Python 3.10 does not have it
    assert 'ap = "autopilot.cli:main"' in text and 'autopilot = "autopilot.cli:main"' in text


def test_start_is_run_in_the_background(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "start_detached", lambda root, argv: seen.append(argv) or 0)
    root = make_project(tmp_path, phases_basic())
    assert cli_main(["start", "-C", str(root)]) == 0
    assert seen == [["run", "--clear-stop", "-C", str(root)]]


def test_the_watch_window_gets_color_when_claude_code_started_the_run(tmp_path, monkeypatch):
    import subprocess
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: started.append(kw))
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/xterm" if name == "xterm" else None)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("CLAUDECODE", "1")
    cli.open_watch_window(tmp_path)
    monkeypatch.delenv("CLAUDECODE")
    cli.open_watch_window(tmp_path)  # the user's own NO_COLOR stays
    assert "NO_COLOR" not in started[0]["env"] and started[1]["env"]["NO_COLOR"] == "1"


def test_a_command_with_no_folder_uses_the_last_project(tmp_path, monkeypatch, capsys):
    root = make_project(tmp_path, phases_basic())
    assert cli_main(["status", "-C", str(root)]) == 0  # this project is now the last one used
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    capsys.readouterr()
    assert cli_main(["status"]) == 0
    out = capsys.readouterr().out
    assert f"project: {root}" in out and "Task 0/3" in out


def test_the_current_folder_wins_when_it_is_a_project(tmp_path, monkeypatch, capsys):
    one = make_project(tmp_path, phases_basic())
    other = tmp_path / "two"
    other.mkdir()
    two = make_project(other, phases_basic()[:1])
    assert cli_main(["status", "-C", str(one)]) == 0
    monkeypatch.chdir(two)
    capsys.readouterr()
    assert cli_main(["status"]) == 0
    out = capsys.readouterr().out
    assert "project:" not in out and "Task 0/2" in out


def test_no_project_anywhere_gives_a_clear_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli_main(["status"]) == 1
    assert "no Autopilot project" in capsys.readouterr().out


def test_two_active_builds_are_listed_and_never_guessed(tmp_path, monkeypatch, capsys):
    one = make_project(tmp_path, phases_basic())
    other = tmp_path / "two"
    other.mkdir()
    two = make_project(other, phases_basic())
    for r in (one, two):
        assert cli_main(["status", "-C", str(r)]) == 0
    monkeypatch.setattr(cli, "run_active", lambda root: True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    capsys.readouterr()
    assert cli_main(["status"]) == 1  # pytest has no terminal: nobody to ask
    out = capsys.readouterr().out
    assert str(one) in out and str(two) in out and "-C" in out


# ---------------------------------------------------------------- J4: "planning" while quickstart works
def test_quickstart_says_planning_and_does_not_print_steps_it_does_itself(tmp_path, monkeypatch, capsys):
    body = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
            "elif sys.argv[1:2] == ['auth']: pass\n"
            "else:\n"
            "    import pathlib, shutil\n"
            "    seen = pathlib.Path('seen.json')\n"
            "    if not seen.exists(): shutil.copy('.agent/run.json', seen)\n"
            "    if not pathlib.Path('PLAN.md').exists():\n"
            "        pathlib.Path('PLAN.md').write_text('# Plan: todo CLI\\n' + 'Part 1 and Part 2 ' * 60)\n"
            "    print(json.dumps({'type': 'result', 'result': 'ok', 'session_id': 's1'}))\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    assert cli_main(["quickstart", "-C", str(proj), "--idea", "a todo list CLI with due dates"]) == 0
    out = capsys.readouterr().out
    during = json.loads((proj / "seen.json").read_text(encoding="utf-8"))  # what a watcher saw during the plan session
    assert during["status"] == "running" and during["state"] == "Plan" and "plan" in during["current"].lower()
    after = json.loads((proj / ".agent" / "run.json").read_text(encoding="utf-8"))
    assert after["status"] == "finished"  # no run was asked for: the status must not say ON for ever
    assert "autopilot onboard --plan-doc" not in out  # quickstart does that step itself
