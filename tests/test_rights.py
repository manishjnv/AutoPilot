"""N8: one consent at install, then zero questions. The rights the installer took install a missing system tool later."""
import shutil
from pathlib import Path
from types import SimpleNamespace

from autopilot import rights
from autopilot.rights import describe, have_rights, install_system_tool, remove_rights


def fake_run(calls, rc=0):
    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(rc=rc, stdout="", stderr="", timed_out=False)
    return run


def test_linux_install_goes_through_sudoers_without_a_question(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rights, "run_proc", fake_run(calls))
    monkeypatch.setattr(rights, "SUDOERS", str(tmp_path / "autopilot"))
    assert have_rights("linux") == ""  # no file: no rights
    assert install_system_tool("node", "sudo apt install nodejs npm", platform="linux") is False and calls == []
    (tmp_path / "autopilot").write_text("x\n")
    assert have_rights("linux") == "sudoers"
    monkeypatch.setattr(shutil, "which", lambda t, **kw: "/usr/bin/node")
    assert install_system_tool("node", "sudo apt install nodejs npm", platform="linux") is True
    assert calls == [["sudo", "-n", "/usr/bin/apt-get", "install", "-y", "nodejs", "npm"]]  # -n: never a prompt
    assert install_system_tool("x", "sudo rm -rf /", platform="linux") is False  # only apt-get install, named packages


def test_windows_install_queues_a_winget_id_and_runs_the_task(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rights, "run_proc", fake_run(calls))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(rights, "_refresh_path", lambda: None)
    monkeypatch.setattr(shutil, "which", lambda t, **kw: "C:/node.exe")
    assert install_system_tool("node", "winget install -e --id OpenJS.NodeJS.LTS", platform="win32", sleep=lambda s: None)
    assert (tmp_path / "Autopilot" / "setup-queue.txt").read_text() == "OpenJS.NodeJS.LTS\n"  # N8: ProgramData only
    assert calls[-1] == ["schtasks", "/Run", "/TN", "Autopilot-Setup"]
    assert install_system_tool("x", "winget install -e --id 'bad id; calc'", platform="win32") is False
    assert rights.queue_write("Git.Git", tmp_path / "local" / "autopilot" / "setup-queue.txt") is False  # elsewhere
    assert not (tmp_path / "local").exists()


def test_per_user_commands_need_no_rights(monkeypatch):
    calls = []
    monkeypatch.setattr(rights, "run_proc", fake_run(calls))
    monkeypatch.setattr(rights, "_refresh_path", lambda: None)
    monkeypatch.setattr(shutil, "which", lambda t, **kw: "/home/me/.local/bin/uv")
    assert install_system_tool("uv", "curl -LsSf https://astral.sh/uv/install.sh | sh", platform="linux") is True
    assert calls == ["curl -LsSf https://astral.sh/uv/install.sh | sh"]
    assert install_system_tool("uv", "", platform="linux") is False


def test_remove_rights_and_describe(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rights, "SUDOERS", str(tmp_path / "autopilot"))
    assert remove_rights("linux", run=fake_run(calls)) == [f"no {tmp_path / 'autopilot'}: nothing to remove"]
    (tmp_path / "autopilot").write_text("x\n")
    assert "undo: `ap uninstall --rights`" in describe("linux")
    assert remove_rights("linux", run=fake_run(calls))[0].startswith("removed ")
    assert calls[-1] == ["sudo", "-n", "rm", "-f", str(tmp_path / "autopilot")]
    assert remove_rights("linux", run=fake_run(calls, rc=1))[0].startswith("run: sudo rm -f")
    assert describe("darwin") == "none needed on macOS"
    assert remove_rights("darwin") == ["macOS: Autopilot took no rights (brew needs none)"]


def test_preflight_installs_a_missing_system_tool_through_the_rights(tmp_path, monkeypatch, capsys):
    from autopilot import cli
    from autopilot.cli import main as cli_main
    assert cli_main(["init", "-C", str(tmp_path), "--stack", "generic"]) == 0
    (tmp_path / "package-lock.json").write_text("{}\n")
    from autopilot.config import Config
    cfg = Config.load(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda t, **kw: None if t in ("node", "npm") else "/bin/x")
    done = []
    monkeypatch.setattr(rights, "install_system_tool", lambda tool, hint, **kw: done.append((tool, hint)) or False)
    assert cli.install_deps(cfg) is False
    assert done and done[0][0] in ("node", "npm") and "FAIL" in capsys.readouterr().out


def test_doctor_has_a_rights_row(tmp_path):
    from autopilot.cli import main as cli_main
    from autopilot.config import Config
    from autopilot.doctor import checks
    assert cli_main(["init", "-C", str(tmp_path), "--stack", "generic"]) == 0
    rows = {name: detail for _, name, detail in checks(Config.load(tmp_path))}
    assert "rights" in rows and ("undo:" in rows["rights"] or "none" in rows["rights"])


def test_install_scripts_take_no_rights_by_default():
    """N5.4: the normal path has no sudo and no UAC; the Windows rights step runs only with -Rights."""
    root = Path(__file__).resolve().parents[1]
    sh, ps = (root / "install.sh").read_text(encoding="utf-8"), (root / "install.ps1").read_text(encoding="utf-8")
    assert "sudo tee" not in sh and "visudo" not in sh and "This script installs:" in sh and "ap install --rights" in sh
    assert "/RL HIGHEST" in ps and "Autopilot-Setup" in ps and "--silent --accept-package-agreements" in ps
    assert ps.count("-Verb RunAs") == 1 and "if ($Rights) {" in ps and "--scope user" in ps  # UAC only with -Rights
    # N8: the task's script and queue live under ProgramData; the script is writable by Administrators (S-1-5-32-544) only
    assert "$env:ProgramData 'Autopilot'" in ps and "$env:ProgramData 'Autopilot\\setup-queue.txt'" in ps
    assert "Remove-Item -Recurse -Force '$SetupDir'" in ps and "icacls '$SetupDir' /setowner *S-1-5-32-544" in ps
    assert "/grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX'" in ps
    assert "FromBase64String('$SetupB64')" in ps and "SetupDraft" not in ps  # the body rides inside the elevated command
    assert "icacls '$SetupQueue' /grant '*S-1-5-32-545:M'" in ps and "Clear-Content $q" in ps
    assert "[regex]::Escape($SetupScript)" in ps  # an old task that points elsewhere is recreated
    assert "$env:LOCALAPPDATA" not in ps


def test_setup_rights_linux_installs_the_sudoers_file_with_one_sudo(tmp_path, monkeypatch):
    """N5.4: `ap install --rights` on Linux: sudo install (mode 0440) then visudo; no shell string."""
    calls = []
    monkeypatch.setattr(rights, "SUDOERS", str(tmp_path / "etc" / "autopilot"))
    out = rights.setup_rights("linux", run=fake_run(calls), user="me", tmp=tmp_path)
    assert calls[0][:4] == ["sudo", "install", "-m", "0440"] and calls[1][:3] == ["sudo", "visudo", "-cf"]
    assert not (tmp_path / "autopilot-sudoers").exists() and out  # the draft is removed


def test_setup_rights_windows_prints_the_one_command(monkeypatch):
    monkeypatch.setattr(rights, "have_rights", lambda platform=None: "")
    out = rights.setup_rights("win32", run=fake_run([]))
    assert len(out) == 1 and "install.ps1 -Rights" in out[0]


def test_sudoers_draft_is_private_and_not_a_fixed_name(tmp_path, monkeypatch):
    """H6: the draft is a mkstemp file (0600) inside a private mkdtemp folder, gone after the install."""
    import os
    import sys

    import pytest
    if sys.platform.startswith("win"):
        pytest.skip("POSIX file modes")
    seen = []

    def run(cmd, **kw):
        if cmd[:2] == ["sudo", "install"]:
            draft = Path(cmd[-2])
            seen.append((draft, draft.stat().st_mode & 0o777, draft.parent.stat().st_mode & 0o777))
        return SimpleNamespace(rc=0, stdout="", stderr="", timed_out=False)
    monkeypatch.setattr(rights, "SUDOERS", str(tmp_path / "autopilot"))
    rights.setup_rights("linux", run=run, user="me", tmp=tmp_path)
    draft, mode, dmode = seen[0]
    assert draft.name != "autopilot-sudoers" and mode == 0o600 and dmode == 0o700
    assert not draft.parent.exists() and os.listdir(tmp_path) == []
