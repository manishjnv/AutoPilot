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


def test_install_scripts_take_the_rights_once():
    root = Path(__file__).resolve().parents[1]
    sh, ps = (root / "install.sh").read_text(encoding="utf-8"), (root / "install.ps1").read_text(encoding="utf-8")
    assert "visudo -cf" in sh and "/etc/sudoers.d/autopilot" in sh and "This script installs:" in sh
    assert "/RL HIGHEST" in ps and "Autopilot-Setup" in ps and "--silent --accept-package-agreements" in ps
    assert ps.count("-Verb RunAs") == 1  # one UAC prompt
    # N8: the task's script and queue live under ProgramData; the script is writable by Administrators (S-1-5-32-544) only
    assert "$env:ProgramData 'Autopilot'" in ps and "$env:ProgramData 'Autopilot\\setup-queue.txt'" in ps
    assert "icacls '$SetupScript' /inheritance:r /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F' '*S-1-5-32-545:RX'" in ps
    assert "$env:LOCALAPPDATA 'autopilot\\setup-queue" not in ps and "Set-Content -Path $SetupScript" not in ps
