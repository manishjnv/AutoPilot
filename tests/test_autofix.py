"""The doctor fixes what needs no person (PATH, a broken claude CLI) before quickstart and run."""
import subprocess
import sys

import pytest

from autopilot import doctor
from autopilot.cli import main as cli_main
from autopilot.doctor import FAIL, OK, WARN, autofix
from test_backend import stub_claude


def test_autofix_runs_only_matching_fixes_and_respects_the_switch(monkeypatch):
    calls = []
    monkeypatch.setattr(doctor, "FIXES", {"claude CLI": lambda: calls.append("claude") or "reinstalled",
                                          "autopilot cmd": lambda: calls.append("path") or "added"})
    rows = [(FAIL, "claude CLI", "x"), (OK, "autopilot cmd", "on PATH"), (WARN, "notifications", "none")]
    assert autofix(rows) == []  # the test suite's AUTOPILOT_NO_AUTOFIX
    monkeypatch.delenv("AUTOPILOT_NO_AUTOFIX")
    assert autofix(rows) == ["claude CLI: reinstalled"] and calls == ["claude"]  # OK rows and unfixable WARNs skipped


def test_fix_claude_without_npm(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert "npm not found" in doctor.fix_claude()


@pytest.mark.skipif(sys.platform == "win32", reason="the POSIX branch writes ~/.profile")
def test_fix_path_on_posix_appends_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(doctor, "scripts_dir", lambda: tmp_path / "bin")
    (tmp_path / ".profile").write_text("umask 022")  # no trailing newline
    assert "added" in doctor.fix_path() and "added" in doctor.fix_path()
    text = (tmp_path / ".profile").read_text()
    assert text.count(f'export PATH="$PATH:{tmp_path / "bin"}"') == 1 and text.startswith("umask 022\n")
    assert str(tmp_path / "bin") in doctor.os.environ["PATH"]


def test_launcher_goes_only_into_a_known_user_folder_already_on_path(monkeypatch, tmp_path):
    home = tmp_path / "home"
    known = (home / "AppData" / "Local" / "Microsoft" / "WindowsApps") if doctor.WINDOWS else (home / ".local" / "bin")
    known.mkdir(parents=True)
    other = tmp_path / "random-on-path"
    other.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("PATH", str(other))
    assert doctor.write_launcher() == ""  # never an arbitrary PATH folder
    monkeypatch.setenv("PATH", str(other) + doctor.os.pathsep + str(known))
    path = doctor.write_launcher()
    assert path and doctor.Path(path).parent == known and "-m autopilot" in doctor.Path(path).read_text()
    assert not list(other.iterdir())


def test_path_check_names_the_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor, "scripts_dir", lambda: tmp_path)
    level, name, detail = doctor.check_path()
    assert (level, name) == (WARN, "autopilot cmd") and str(tmp_path) in detail and "python -m autopilot" in detail


def test_run_refuses_to_start_on_a_broken_claude(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, "print('Bun 1.4.3')\n"))
    proj = tmp_path / "app"
    proj.mkdir()
    assert cli_main(["init", "-C", str(proj)]) == 0
    assert cli_main(["run", "-C", str(proj)]) == 1
    assert "FAIL  claude CLI" in capsys.readouterr().out and not (proj / ".agent" / "state.db").exists()


def test_python_dash_m_autopilot_works():
    p = subprocess.run([sys.executable, "-m", "autopilot", "--version"], capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.strip()
