"""N2: missing project dependencies and system tool hints (pure checks, nothing is installed)."""
import sys

import pytest

from autopilot.doctor import WARN, check_deps, missing_deps, system_tool_hint
from test_doctor import project


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.setenv("GOMODCACHE", str(tmp_path / "gomod-cache-example"))
    monkeypatch.setenv("CARGO_HOME", str(tmp_path / "cargo-home-example"))


def one(root):
    items = missing_deps(root)
    assert len(items) == 1
    return items[0]


def test_node_lock_without_node_modules(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    d = one(tmp_path)
    assert (d["lock"], d["command"], d["tool"]) == ("package-lock.json", "npm ci", "npm")
    (tmp_path / "node_modules").mkdir()
    assert missing_deps(tmp_path) == []


def test_pnpm_and_both_yarn_flavours(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert one(tmp_path)["command"] == "pnpm install --frozen-lockfile"
    (tmp_path / "pnpm-lock.yaml").unlink()
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n", encoding="utf-8")
    assert one(tmp_path)["command"] == "yarn install --frozen-lockfile"
    (tmp_path / "yarn.lock").write_text("__metadata:\n  version: 6\n", encoding="utf-8")
    d = one(tmp_path)
    assert (d["command"], d["tool"]) == ("yarn install --immutable", "yarn")


@pytest.mark.parametrize("lock,command,tool", [("uv.lock", "uv sync", "uv"), ("poetry.lock", "poetry install", "poetry"),
                                               ("go.sum", "go mod download", "go"), ("Cargo.lock", "cargo fetch", "cargo")])
def test_other_locks(tmp_path, lock, command, tool):
    (tmp_path / lock).write_text("", encoding="utf-8")
    d = one(tmp_path)
    assert (d["lock"], d["command"], d["tool"]) == (lock, command, tool)


def test_requirements_file(tmp_path):
    (tmp_path / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")
    d = one(tmp_path)
    assert (d["command"], d["tool"]) == ("pip install -r requirements.txt", "python")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("", encoding="utf-8")
    assert missing_deps(tmp_path) == []


def test_present_environments_report_nothing(tmp_path):
    for lock in ("uv.lock", "go.sum", "Cargo.lock"):
        (tmp_path / lock).write_text("", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "target").mkdir()
    assert missing_deps(tmp_path) == []


def test_empty_folder(tmp_path):
    assert missing_deps(tmp_path) == []


@pytest.mark.parametrize("tool", ["python", "node", "git", "npm", "pnpm", "yarn", "uv", "poetry", "go", "cargo"])
def test_system_tool_hint_on_both_platforms(tool):
    win, lin = system_tool_hint(tool, "win32"), system_tool_hint(tool, "linux")
    assert win and lin
    assert system_tool_hint(tool, "darwin")
    if tool in ("python", "node", "git"):
        assert win.startswith("winget ") and lin.startswith("sudo apt ")


def test_unknown_tool_has_no_hint():
    assert system_tool_hint("nonexistent-tool-example", "linux") == ""


def test_doctor_row_names_the_dependency_and_command(tmp_path):
    cfg = project(tmp_path)
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    level, name, detail = check_deps(cfg)
    assert (level, name) == (WARN, "dependencies")
    assert "package-lock.json" in detail and "npm ci" in detail
    from autopilot.doctor import checks
    assert any(r[1] == "dependencies" and r[0] == WARN for r in checks(cfg))
    (tmp_path / "node_modules").mkdir()
    assert check_deps(cfg) is None


# ---- N2: preflight installs project dependencies (a fake npm on PATH records each call)
def node_project(tmp_path, monkeypatch, setup=None):
    from autopilot.cli import main as cli_main
    from autopilot.config import Config
    assert cli_main(["init", "-C", str(tmp_path), "--stack", "generic"]) == 0
    p = tmp_path / ".agent" / "project.yaml"
    text = p.read_text(encoding="utf-8").replace("\nagent:\n", "\nagent:\n  backend: command\n", 1)  # W38: one agent block
    if setup:
        text = text.replace("  setup: []", f"  setup: [\"{setup}\"]", 1)
    p.write_text(text, encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    bin_dir = tmp_path / "bin-example"
    bin_dir.mkdir()
    calls = tmp_path / "npm-calls.log"
    (bin_dir / "npm").write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nmkdir -p node_modules\n', encoding="utf-8")
    (bin_dir / "npm").chmod(0o755)
    (bin_dir / "npm.cmd").write_text(f'@echo %* >> "{calls}"\r\n@mkdir node_modules\r\n', encoding="utf-8")
    monkeypatch.setenv("PATH", str(bin_dir) + __import__("os").pathsep + __import__("os").environ["PATH"])
    return Config.load(tmp_path), p, calls


def test_preflight_installs_and_remembers_the_standard_command(tmp_path, monkeypatch):
    from autopilot.cli import preflight
    cfg, p, calls = node_project(tmp_path, monkeypatch)
    before = p.read_text(encoding="utf-8")
    assert preflight(cfg) is True
    assert calls.read_text(encoding="utf-8").split() == ["ci"]
    assert (tmp_path / "node_modules").is_dir()
    text = p.read_text(encoding="utf-8")
    assert '["npm ci"]' in text
    assert "# Commands the orchestrator runs itself" in text and text.count("#") == before.count("#")
    from autopilot.config import Config
    assert Config.load(tmp_path).commands("setup") == ["npm ci"]
    assert preflight(Config.load(tmp_path)) is True  # second run: nothing to install
    assert len(calls.read_text(encoding="utf-8").splitlines()) == 1


def test_pip_install_goes_through_a_venv(tmp_path, monkeypatch):
    import os
    from autopilot.cli import venv_commands
    cmd = "pip install -r requirements.txt"
    got = venv_commands(tmp_path, cmd)
    assert len(got) == 2 and got[0].endswith("-m venv .venv") and "pip install -r" in got[1]
    assert got[1].startswith(".venv") and cmd not in got
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("", encoding="utf-8")
    got = venv_commands(tmp_path, cmd)
    assert len(got) == 1 and got[0].startswith(".venv") and "venv .venv" not in got[0]
    (tmp_path / ".venv" / "pyvenv.cfg").unlink()
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "active"))
    got = venv_commands(tmp_path, cmd)
    assert len(got) == 1 and "-m pip install -r requirements.txt" in got[0] and not got[0].startswith(".venv")
    assert venv_commands(tmp_path, "npm ci") == ["npm ci"]


def test_preflight_remembers_the_venv_commands(tmp_path, monkeypatch):
    from autopilot.cli import preflight
    cfg, p, calls = node_project(tmp_path, monkeypatch)
    (tmp_path / "package-lock.json").unlink()
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    import types
    ran = []
    monkeypatch.setattr("autopilot.gate.run_commands",
                        lambda cmds, *a: ran.extend(cmds) or [types.SimpleNamespace(rc=0, output="")])
    assert preflight(cfg) is True
    from autopilot.config import Config
    setup = Config.load(tmp_path).commands("setup")
    assert ran == setup
    assert "-m venv .venv" in setup[0] and len(setup) == 2 and not any(c.startswith("pip ") for c in setup)


def test_preflight_runs_commands_setup_when_set(tmp_path, monkeypatch):
    from autopilot.cli import preflight
    cfg, p, calls = node_project(tmp_path, monkeypatch, setup="npm install --no-audit")
    assert preflight(cfg) is True
    assert calls.read_text(encoding="utf-8").split() == ["install", "--no-audit"]
    assert '["npm install --no-audit"]' in p.read_text(encoding="utf-8")


def test_preflight_without_the_system_tool_prints_the_install_command(tmp_path, monkeypatch, capsys):
    from autopilot.cli import preflight
    cfg, p, calls = node_project(tmp_path, monkeypatch)
    empty = tmp_path / "empty-bin-example"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert preflight(cfg) is False
    out = capsys.readouterr().out
    assert f"FAIL  npm is not installed. Install it with: {system_tool_hint('npm')}" in out
    assert not calls.exists() and not (tmp_path / "node_modules").exists()
