"""M4: ready-made invocations for other agent CLIs (Codex, Gemini, OpenCode) on the command backend."""
import os
import sys

import pytest
import yaml

from autopilot.backends import SessionRequest, get_backend
from autopilot.backends.command import PRESETS, command_template, model_flag
from autopilot.config import Config
from autopilot.doctor import checks


def cfg_with(tmp_path, agent):
    (tmp_path / ".agent").mkdir(exist_ok=True)
    (tmp_path / ".agent" / "project.yaml").write_text(yaml.safe_dump({"agent": {"backend": "command", **agent}}))
    return Config.load(tmp_path)


def fake_cli(tmp_path, monkeypatch, name):
    """A stand-in agent CLI on PATH: prints its argv and the stdin it got, then a done report."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "fake.py").write_text(
        "import json,sys\nprompt = sys.stdin.read()\nprint('ARGV', json.dumps(sys.argv[1:]))\n"
        "print('STDIN', json.dumps(prompt))\nprint('```json\\n' + json.dumps({'status': 'done'}) + '\\n```')\n")
    if sys.platform == "win32":
        (bindir / f"{name}.cmd").write_text(f'@"{sys.executable}" "%~dp0fake.py" %*\n')
    else:
        exe = bindir / name
        exe.write_text(f"#!{sys.executable}\n" + (bindir / "fake.py").read_text())
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))


def test_each_preset_runs_with_the_prompt_on_stdin(tmp_path, monkeypatch):
    fake_cli(tmp_path, monkeypatch, "codex")
    cfg = cfg_with(tmp_path, {"preset": "codex", "model_map": {"sonnet": "big-model"}})
    res = get_backend(cfg).run(SessionRequest(prompt="build the login page", model="sonnet", cwd=str(tmp_path),
                                              system_append="PROJECT CONTEXT"))
    assert res.ok and res.report == {"status": "done"}
    argv = next(line for line in res.text.splitlines() if line.startswith("ARGV"))
    assert '"exec"' in argv and '"-m", "big-model"' in argv and "standard input" in argv
    assert "build the login page" in res.text and "PROJECT CONTEXT" in res.text  # both arrive on stdin


def test_templates_and_model_flags(tmp_path):
    cfg = cfg_with(tmp_path, {"preset": "gemini", "model_map": {"opus": "pro"}})
    assert command_template(cfg).startswith("gemini --approval-mode=yolo")
    assert model_flag(cfg, "opus") == " -m pro" and model_flag(cfg, "sonnet") == ""  # unmapped alias: CLI default
    assert model_flag(cfg, "custom/model-1") == " -m custom/model-1"
    assert set(PRESETS) == {"codex", "gemini", "opencode"}
    own = cfg_with(tmp_path, {"preset": "codex", "command": "my-agent {model}"})
    assert command_template(own) == "my-agent {model}"  # an explicit command wins


def test_shell_characters_in_model_names_are_refused(tmp_path):
    cfg = cfg_with(tmp_path, {"preset": "codex", "model_map": {"sonnet": "x & calc.exe", "opus": "a;rm -rf ~"}})
    for bad in ("sonnet", "opus", "$(id)", "x\"y"):
        with pytest.raises(ValueError, match="unsafe model name"):
            model_flag(cfg, bad)
    assert any("model_map names" in e for e in cfg.validate())


def test_config_and_doctor(tmp_path, monkeypatch):
    assert any("agent.preset must be one of" in e for e in cfg_with(tmp_path, {"preset": "nope"}).validate())
    assert any("needs agent.command or agent.preset" in e for e in cfg_with(tmp_path, {}).validate())
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    rows = {n: lvl for lvl, n, _ in checks(cfg_with(tmp_path, {"preset": "opencode"}))}
    assert rows["agent command"] == "FAIL"
