"""M4, P03-T01: ready-made invocations for other agent CLIs (Codex, Gemini, OpenCode, Kiro, Cursor, Aider)."""
import json
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
    """A stand-in agent CLI on PATH: prints its argv, the stdin and the --message-file it got, then a done report."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "fake.py").write_text(
        "import json,sys\nprompt = sys.stdin.read()\nprint('ARGV', json.dumps(sys.argv[1:]))\n"
        "print('STDIN', json.dumps(prompt))\n"
        "if '--message-file' in sys.argv:\n"
        "    print('FILE', json.dumps(open(sys.argv[sys.argv.index('--message-file') + 1], encoding='utf-8').read()))\n"
        "print('```json\\n' + json.dumps({'status': 'done'}) + '\\n```')\n")
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
    assert set(PRESETS) == {"codex", "gemini", "opencode", "kiro", "cursor", "aider"}
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


# P03-T01: kiro reads stdin (no positional argument), cursor gets _ASK + stdin, aider reads a temp message file
NEW = {"kiro": ("kiro-cli", ['"chat"', '"--no-interactive"', '"--trust-all-tools"']),
       "cursor": ("cursor-agent", ['"-p"', '"--force"', '"--trust"', "standard input"]),
       "aider": ("aider", ['"--message-file"', '"--yes-always"', '"--no-auto-commits"', '"--no-dirty-commits"'])}


@pytest.mark.parametrize("preset", sorted(NEW))
def test_new_presets_run_through_the_command_backend(tmp_path, monkeypatch, preset):
    exe, flags = NEW[preset]
    fake_cli(tmp_path, monkeypatch, exe)
    cfg = cfg_with(tmp_path, {"preset": preset, "model_map": {"sonnet": "big-model"}})
    assert command_template(cfg).split()[0] == exe
    res = get_backend(cfg).run(SessionRequest(prompt="build the login page", model="sonnet", cwd=str(tmp_path),
                                              system_append="PROJECT CONTEXT"))
    assert res.ok and res.report == {"status": "done"}
    argv = next(line for line in res.text.splitlines() if line.startswith("ARGV"))
    assert all(f in argv for f in flags) and '"--model", "big-model"' in argv and '"-m"' not in argv
    stdin = next(line for line in res.text.splitlines() if line.startswith("STDIN"))
    assert "build the login page" in stdin and "PROJECT CONTEXT" in stdin  # the prompt is still piped
    if preset == "kiro":
        assert "standard input" not in argv  # a positional argument stops kiro-cli from reading stdin
    if preset == "aider":
        file_line = next(line for line in res.text.splitlines() if line.startswith("FILE"))
        assert "build the login page" in file_line and "PROJECT CONTEXT" in file_line
        path = json.loads(argv[5:])[1]
        assert not os.path.exists(path) and not path.startswith(str(tmp_path))  # removed, outside the worktree


@pytest.mark.parametrize("preset", sorted(NEW))
def test_new_presets_model_flag(tmp_path, preset):
    cfg = cfg_with(tmp_path, {"preset": preset, "model_map": {"opus": "pro", "haiku": "x & calc.exe"}})
    assert model_flag(cfg, "opus") == " --model pro" and model_flag(cfg, "sonnet") == ""
    assert "{model_flag}" in command_template(cfg)
    for bad in ("haiku", "$(id)", "a;rm -rf ~", "x\"y"):
        with pytest.raises(ValueError, match="unsafe model name"):
            model_flag(cfg, bad)


def test_old_presets_unchanged():
    ask = '"Your full instructions are on standard input. Follow them and end with the requested JSON report."'
    assert PRESETS["codex"] == "codex exec --sandbox workspace-write --skip-git-repo-check{model_flag} " + ask
    assert PRESETS["gemini"] == "gemini --approval-mode=yolo{model_flag} -p " + ask
    assert PRESETS["opencode"] == "opencode run --auto{model_flag} " + ask


def _init_python(tmp_path, force=False):
    import argparse
    from autopilot.cli import cmd_init
    cmd_init(argparse.Namespace(path=str(tmp_path), stack="python", name=None, force=force, quiet=True))
    return (tmp_path / ".agent" / "project.yaml").read_text(encoding="utf-8")


def _template_keys():
    from autopilot.cli import TEMPLATES
    return set(yaml.safe_load((TEMPLATES / "agent" / "project.yaml").read_text(encoding="utf-8")))


def test_init_stack_keeps_blocks_after_commands(tmp_path):
    text = _init_python(tmp_path)
    data = yaml.safe_load(text)
    assert _template_keys() <= set(data)
    assert {"agent", "gate", "models", "scheduling"} <= set(data)
    assert data["commands"]["test"] == ["python -m pytest -q"]
    assert "scheduling:" in text


def test_init_force_twice_keeps_one_commands_block(tmp_path):
    first = yaml.safe_load(_init_python(tmp_path))
    text = _init_python(tmp_path, force=True)
    assert text.count("\ncommands:") + text.startswith("commands:") == 1
    assert set(yaml.safe_load(text)) == set(first)


def test_command_error_names_every_preset(tmp_path):
    # P08-T02: the error lists every preset from PRESETS, not a fixed short list
    err = next(e for e in cfg_with(tmp_path, {}).validate() if "needs agent.command or agent.preset" in e)
    for name in PRESETS:
        assert name in err
    for name in ("kiro", "cursor", "aider"):
        assert name in err
