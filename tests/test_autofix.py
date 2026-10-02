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


class Proc:
    rc, stdout, stderr = 0, "", ""


def test_fix_claude_without_npm_runs_the_native_installer_and_says_so_first(monkeypatch, tmp_path, capsys):
    """H3: no npm and no Claude Code: the installer from claude.ai runs, and no message asks for Node.js."""
    ran = []
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor, "run_proc", lambda cmd, **kw: ran.append(cmd) or Proc())
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", str(tmp_path / "missing-claude"))
    assert doctor.fix_claude() == "reinstalled (native)"
    assert "https://claude.ai/install." in ran[0][-1] and "npm" not in " ".join(ran[0])
    said = capsys.readouterr().out
    assert "https://claude.ai/install." in said and "downloads and installs" in said and "Node.js" not in said


def test_fix_claude_keeps_the_route_of_the_install(monkeypatch, tmp_path):
    """H3: an npm install is repaired with npm; a winget install gets the command and nothing runs."""
    ran = []
    monkeypatch.setattr(doctor, "run_proc", lambda cmd, **kw: ran.append(cmd) or Proc())
    npm_bin = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude"
    winget_bin = tmp_path / "WinGet" / "Links" / "claude.exe"
    for p in (npm_bin, winget_bin):
        p.parent.mkdir(parents=True)
        p.write_text("x")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/npm" if name == "npm" else None)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", str(npm_bin))
    assert doctor.fix_claude() == "reinstalled (npm)" and ran == [["/usr/bin/npm", "i", "-g", "@anthropic-ai/claude-code"]]
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)  # the npm program is gone: the native installer
    assert doctor.claude_route(str(npm_bin)) == "native"
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", str(winget_bin))
    assert "winget upgrade" in doctor.fix_claude() and len(ran) == 1


def test_claude_is_found_in_the_native_install_folder_when_path_is_old(monkeypatch, tmp_path):
    """H3: right after the native install, the terminal's PATH does not have ~/.local/bin yet."""
    from autopilot.backends.claude_cli import ClaudeCLIBackend
    for k in ("AUTOPILOT_CLAUDE_BIN", "AUTODEV_CLAUDE_BIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert ClaudeCLIBackend.resolve_binary() == "claude"
    native = tmp_path / ".local" / "bin" / ("claude.exe" if doctor.WINDOWS else "claude")
    native.parent.mkdir(parents=True)
    native.write_text("x")
    assert ClaudeCLIBackend.resolve_binary() == str(native)


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
