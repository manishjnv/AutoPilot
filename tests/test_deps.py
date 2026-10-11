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
