"""W38: a duplicate key in project.yaml is an error; `ap validate` prints the session environment."""
from pathlib import Path

import pytest
import yaml

from autopilot.cli import main as cli_main
from autopilot.config import Config, load_yaml

ROOT = Path(__file__).resolve().parent.parent

TWO_ENVS = """name: app
agent:
  env:
    CLAUDE_CONFIG_DIR: /home/example/.claude-work
  timeout_minutes: 30
  env:
    CLAUDE_CONFIG_DIR: /home/example/.claude-fake
"""


def project(tmp_path, text=None):
    assert cli_main(["init", "-C", str(tmp_path), "--stack", "python"]) == 0
    if text is not None:
        (tmp_path / ".agent" / "project.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_two_env_keys_under_agent_fail_with_both_lines(tmp_path):
    p = tmp_path / "project.yaml"
    p.write_text(TWO_ENVS, encoding="utf-8")
    with pytest.raises(yaml.YAMLError) as err:
        load_yaml(p)
    assert str(err.value) == "duplicate key 'env' in agent: lines 3 and 6"
    with pytest.raises(yaml.YAMLError, match="duplicate key 'env' in agent: lines 3 and 6"):
        Config.load(project(tmp_path / "app", TWO_ENVS))


def test_a_top_level_and_a_nested_duplicate_name_their_place(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("git:\n  mode: direct\nname: a\ngit:\n  push: false\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match="duplicate key 'git' in the top level: lines 1 and 4"):
        load_yaml(p)
    p.write_text("deploy:\n  prod:\n    cmd: a\n    cmd: b\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match="duplicate key 'cmd' in deploy.prod: lines 3 and 4"):
        load_yaml(p)


def test_a_clean_file_loads_and_equal_keys_in_different_mappings_are_fine(tmp_path):
    p = tmp_path / "ok.yaml"
    p.write_text("agent:\n  env: {A: '1'}\ndeploy:\n  staging: {cmd: a}\n  prod: {cmd: b}\n", encoding="utf-8")
    assert load_yaml(p) == {"agent": {"env": {"A": "1"}}, "deploy": {"staging": {"cmd": "a"}, "prod": {"cmd": "b"}}}
    assert Config.load(project(tmp_path / "app")).get("agent.backend") == "claude_cli"


def test_every_template_and_fixture_yaml_still_loads():
    files = [f for d in ("autopilot", "tests", "examples", "deploy", "plugin") for ext in ("*.yaml", "*.yml")
             for f in (ROOT / d).rglob(ext) if "__pycache__" not in f.parts]
    files += [f for ext in ("*.yaml", "*.yml") for f in (ROOT / ".agent").glob(ext)]
    assert any(f.name == "project.yaml" for f in files)
    for f in files:
        load_yaml(f)  # a duplicate key raises and names the file's lines


def test_validate_prints_the_session_env_and_the_config_folder(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "example-claude"))
    assert cli_main(["validate", "-C", str(root)]) in (0, 1)
    out = capsys.readouterr().out
    assert f"session env: CLAUDE_CONFIG_DIR={tmp_path / 'example-claude'}, 0 passthrough" in out
    assert f"config folder {tmp_path / 'example-claude'}" in out and "runner: claude at " in out
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    cli_main(["validate", "-C", str(root)])
    out = capsys.readouterr().out
    assert "CLAUDE_CONFIG_DIR=unset" in out and f"config folder {Path.home() / '.claude'}" in out


def test_validate_reports_a_duplicate_key_as_a_config_error(tmp_path, capsys):
    root = project(tmp_path, TWO_ENVS)
    assert cli_main(["validate", "-C", str(root)]) == 1
    assert "config  ERROR .agent/project.yaml: duplicate key 'env' in agent: lines 3 and 6" in capsys.readouterr().out


def test_the_run_start_log_names_the_config_folder(tmp_path, caplog, monkeypatch):
    import logging
    from test_autopilot import FakeBackend, make_project, phases_basic
    from test_orchestrator import orch_for
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "example-claude"))
    with caplog.at_level(logging.INFO, logger="autopilot"):
        orch_for(make_project(tmp_path, phases_basic()), FakeBackend()).run()
    assert f"config folder {tmp_path / 'example-claude'}" in [r.getMessage() for r in caplog.records]
