"""W37b: sessions may not kill processes by name (deny rules, system rule, gate check of the session log)."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from autopilot.backends import SessionRequest
from autopilot.backends.claude_cli import KILL_DENY, ClaudeCLIBackend
from autopilot.config import Config
from autopilot.gate import kill_commands, task_gate
from autopilot.gitops import Git

ROOT = Path(__file__).resolve().parents[1]


def tool_use(name, command):
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_fake1", "name": name, "input": {"command": command}}]}})


def text_line(text):
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": text}]}})


def test_build_cmd_always_denies_kill_by_name(tmp_path):
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent/project.yaml").write_text('agent:\n  disallowed_tools:\n    - "Bash(git push:*)"\n',
                                                  encoding="utf-8")
    cmd = ClaudeCLIBackend(Config.load(tmp_path)).build_cmd(SessionRequest(prompt="x", model="sonnet",
                                                                           cwd=str(tmp_path)))
    denied = cmd[cmd.index("--disallowedTools") + 1:]
    assert "Bash(git push:*)" in denied
    for rule in ("Bash(taskkill:*)", "Bash(pkill:*)", "Bash(killall:*)", "Bash(Stop-Process:*)"):
        assert rule in denied
    assert len(set(KILL_DENY)) == 4


def test_template_lists_the_four_rules_once(tmp_path):
    text = (ROOT / "autopilot/templates/agent/project.yaml").read_text(encoding="utf-8")
    for rule in KILL_DENY:
        assert text.count(f'"{rule}"') == 1
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent/project.yaml").write_text(text, encoding="utf-8")
    cmd = ClaudeCLIBackend(Config.load(tmp_path)).build_cmd(SessionRequest(prompt="x", model="sonnet",
                                                                           cwd=str(tmp_path)))
    assert "Bash(git push:*)" in cmd
    assert all(cmd.count(rule) == 1 for rule in KILL_DENY)  # not added twice when the list has them


def test_system_prompt_says_stop_by_pid():
    text = (ROOT / "autopilot/prompts/system.md").read_text(encoding="utf-8")
    assert "Stop only the processes you started, by pid." in text
    assert "Never stop processes by name (taskkill /IM, pkill, killall, Stop-Process -Name)." in text


def test_kill_commands_reads_tool_calls_only():
    log = "\n".join(["$ claude -p", "STDOUT:", text_line("I will not run taskkill /IM python.exe"),
                     tool_use("Bash", "kill 12345"), tool_use("Bash", "taskkill /IM python.exe /F"),
                     tool_use("PowerShell", "Stop-Process -Name python"), tool_use("Bash", "cd x && pkill -f pytest"),
                     tool_use("Grep", "killall python"), tool_use("Bash", "echo killall")])
    assert kill_commands(log) == ["taskkill /IM python.exe /F", "Stop-Process -Name python",
                                  "cd x && pkill -f pytest"]
    wrapped = "\n".join(tool_use("Bash", c) for c in (
        "sudo pkill -f pytest", "cmd /c taskkill /IM python.exe /F", 'powershell -c "Stop-Process -Name python"',
        "env A=1 killall python", "taskkill /PID 123 /T /F", "Stop-Process -Id 123", "grep taskkill notes.md"))
    assert kill_commands(wrapped) == ["sudo pkill -f pytest", "cmd /c taskkill /IM python.exe /F",
                                      'powershell -c "Stop-Process -Name python"', "env A=1 killall python"]
    many = "\n".join(tool_use("Bash", f"killall p{i}") for i in range(8))
    assert len(kill_commands(many)) == 5


@pytest.fixture
def repo(tmp_path):
    for a in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.com"]):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def gate_with_log(repo, lines):
    log = repo.parent / "session.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cfg = Config.load(repo)
    cfg.data["commands"] = {"test": [f'"{sys.executable}" -c "pass"']}
    task = SimpleNamespace(allow_no_changes=False, allow_test_changes=False, files_in_scope=["src/**"], verify=[])
    return task_gate(cfg, Git(repo), task, log_path=str(log))


def test_gate_fails_a_kill_by_name_and_names_it(repo):
    g = gate_with_log(repo, [tool_use("Bash", "taskkill /IM python.exe /F")])
    assert not g.ok
    assert any("process-wide kill: taskkill /IM python.exe /F" in p and "by pid" in p for p in g.problems)


@pytest.mark.parametrize("lines", [[text_line("never run taskkill /IM python.exe")], [tool_use("Bash", "kill 12345")]])
def test_gate_passes_text_mentions_and_kill_by_pid(repo, lines):
    g = gate_with_log(repo, lines)
    assert g.ok, g.problems
