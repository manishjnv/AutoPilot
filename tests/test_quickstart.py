"""M5: `autopilot quickstart` (init → claude check → onboard → doctor) and the VPS installer script."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from autopilot.cli import main as cli_main
from test_backend import stub_claude

CLAUDE_OK = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
             "elif sys.argv[1:2] == ['auth']: pass\n"
             "else: print(json.dumps({'type': 'result', 'result': 'onboarded', 'session_id': 's1'}))\n")


def test_broken_claude_stops_before_onboarding(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, "print('Bun 1.4.3')\n"))
    proj = tmp_path / "app"
    proj.mkdir()
    assert cli_main(["quickstart", "-C", str(proj)]) == 1
    out = capsys.readouterr().out
    assert "claude CLI" in out and "onboarding session" not in out and (proj / ".agent" / "project.yaml").exists()


def test_missing_plan_doc(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    assert cli_main(["quickstart", "-C", str(proj), "--plan-doc", str(tmp_path / "nope.md")]) == 1
    assert "plan document not found" in capsys.readouterr().out


def test_happy_path_ends_with_doctor(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")  # python preset: real verify commands
    (tmp_path / "PLAN.md").write_text("# Plan\nA todo app.\n")
    rc = cli_main(["quickstart", "-C", str(proj), "--plan-doc", str(tmp_path / "PLAN.md")])
    out = capsys.readouterr().out
    assert "onboarding session" in out and "--- doctor" in out
    assert rc == 0 and "ready for `autopilot run`" in out and "What you can do next" in out


def test_no_plan_and_no_idea_asks_for_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    assert cli_main(["quickstart", "-C", str(proj)]) == 1  # pytest's stdin is not a terminal: nobody to ask
    assert "--idea" in capsys.readouterr().out


def test_an_idea_becomes_plan_md_then_onboarding(tmp_path, monkeypatch, capsys):
    body = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
            "elif sys.argv[1:2] == ['auth']: pass\n"
            "else:\n"
            "    import pathlib\n"
            "    if not pathlib.Path('PLAN.md').exists():\n"
            "        pathlib.Path('PLAN.md').write_text('# Plan: todo CLI\\n' + 'Part 1 and Part 2 ' * 60)\n"
            "    print(json.dumps({'type': 'result', 'result': 'ok', 'session_id': 's1'}))\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    rc = cli_main(["quickstart", "-C", str(proj), "--idea", "a todo list CLI with due dates"])
    out = capsys.readouterr().out
    assert "writing PLAN.md from your idea" in out and (proj / "PLAN.md").exists()
    assert "onboarding session" in out and rc == 0


def test_an_existing_plan_md_is_used(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    (proj / "PLAN.md").write_text("# Plan\nA todo app.\n")
    assert cli_main(["quickstart", "-C", str(proj)]) == 0
    out = capsys.readouterr().out
    assert "using PLAN.md" in out and "writing PLAN.md" not in out


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs a POSIX bash")
def test_install_script_parses_and_checks_its_arguments():
    script = Path(__file__).resolve().parents[1] / "deploy" / "install.sh"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    p = subprocess.run(["bash", str(script), "Bad Name", "x"], capture_output=True, text=True)
    assert p.returncode == 2 and "usage" in p.stderr
