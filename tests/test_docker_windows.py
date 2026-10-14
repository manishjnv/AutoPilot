"""W32: sandbox.mode: docker on native Windows (Docker Desktop). No test calls the real docker."""
from __future__ import annotations

import os

import pytest
import yaml

from autopilot import doctor
from autopilot.backends import docker_box
from autopilot.config import Config

WIN_CWD = "E:\\proj\\wt"


def cfg_with(tmp_path, sandbox):
    (tmp_path / ".agent").mkdir(exist_ok=True)
    data = {"agent": {"backend": "claude_cli"}, "sandbox": sandbox}
    (tmp_path / ".agent" / "project.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return Config.load(tmp_path)


@pytest.fixture(autouse=True)
def windows(monkeypatch):
    monkeypatch.setattr("autopilot.config.NATIVE_WINDOWS", True)
    monkeypatch.setattr("autopilot.doctor.sys.platform", "win32")


def test_docker_mode_is_not_refused_on_windows(tmp_path):
    assert cfg_with(tmp_path, {"mode": "docker", "image": "img"})._sandbox_errors() == []


def test_allowlist_is_still_refused_on_windows(tmp_path):
    assert "native Windows" in cfg_with(tmp_path, {"mode": "allowlist"})._sandbox_errors()[0]


def test_argv_has_project_and_login_mounts_with_drive_letters(tmp_path):
    cfg = cfg_with(tmp_path, {"mode": "docker", "image": "img"})
    login = "C:\\Users\\me\\AppData\\Local\\Temp\\autopilot-claude-x"
    argv = docker_box.docker_argv(cfg, ["claude", "-p"], WIN_CWD, login, (), None, {})
    assert f"{WIN_CWD}:/work" in argv and f"{login}:/claude" in argv
    assert argv[argv.index("img"):] == ["img", "claude", "-p"]


def test_login_dir_reads_claude_config_dir_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(docker_box.sys, "platform", "win32")
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / ".credentials.json").write_text("{}", encoding="utf-8")
    with docker_box.login_dir({"CLAUDE_CONFIG_DIR": str(conf)}) as d:
        assert os.path.isfile(os.path.join(d, ".credentials.json"))


def test_doctor_docker_row_reads_the_engine_version(tmp_path, monkeypatch):
    calls: list = []  # a fake `docker` that records its argv (a script named docker is not runnable on Windows)

    def run(cmd, **kw):
        calls.append(cmd)
        return (0, "29.8.2") if cmd[:2] == ["docker", "version"] else (0, "")
    monkeypatch.setattr("autopilot.doctor._run", run)
    rows = [r for r in doctor.checks(cfg_with(tmp_path, {"mode": "docker", "image": "img"})) if r[1] == "docker"]
    assert rows == [("ok", "docker", "29.8.2 (Docker Desktop)")]
    assert ["docker", "version", "--format", "{{.Server.Version}}"] in calls
