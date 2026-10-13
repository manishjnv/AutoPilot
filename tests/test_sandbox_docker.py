"""W11: sandbox.mode, the one mode rule and its config checks."""
from __future__ import annotations

import pytest
import yaml

from autopilot.config import Config, allowlist_on, sandbox_mode


class Fake:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, key, default=None):
        return self.kv.get(key, default)


def cfg_with(tmp_path, data):
    (tmp_path / ".agent").mkdir(exist_ok=True)
    (tmp_path / ".agent" / "project.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return Config.load(tmp_path)


def sandbox_errs(c):
    return [e for e in c._sandbox_errors()]


@pytest.fixture(autouse=True)
def linux(monkeypatch):
    monkeypatch.setattr("autopilot.config.NATIVE_WINDOWS", False)  # CI also runs on Windows


def test_sandbox_mode_values():
    assert sandbox_mode(Fake()) == "off"
    assert sandbox_mode(Fake(**{"sandbox.enabled": True})) == "allowlist"
    assert sandbox_mode(Fake(**{"sandbox.enabled": False})) == "off"
    assert sandbox_mode(Fake(**{"sandbox.mode": "docker"})) == "docker"
    assert sandbox_mode(Fake(**{"sandbox.mode": "off", "sandbox.enabled": True})) == "off"
    assert sandbox_mode(Fake(**{"sandbox.mode": "allowlist"})) == "allowlist"


def test_allowlist_on_four_cases():
    assert allowlist_on(Fake()) is False
    assert allowlist_on(Fake(**{"sandbox.enabled": True})) is True
    assert allowlist_on(Fake(**{"sandbox.mode": "allowlist"})) is True
    assert allowlist_on(Fake(**{"sandbox.mode": "docker"})) is False
    assert allowlist_on(Fake(**{"sandbox.mode": "docker", "sandbox.enabled": True})) is True


def test_bad_mode_names_the_three_values(tmp_path):
    errs = sandbox_errs(cfg_with(tmp_path, {"sandbox": {"mode": "vm"}}))
    assert len(errs) == 1 and "off, allowlist or docker" in errs[0]


def test_docker_needs_an_image(tmp_path):
    base = {"agent": {"backend": "claude_cli"}, "sandbox": {"mode": "docker"}}
    assert "sandbox.image" in sandbox_errs(cfg_with(tmp_path, base))[0]
    base["sandbox"]["image"] = "my-autopilot"
    assert sandbox_errs(cfg_with(tmp_path, base)) == []


def test_docker_needs_the_claude_cli_backend(tmp_path):
    c = cfg_with(tmp_path, {"agent": {"backend": "command", "command": "x"},
                            "sandbox": {"mode": "docker", "image": "my-autopilot"}})
    assert "agent.backend: claude_cli" in sandbox_errs(c)[0]


def test_docker_refused_on_native_windows(tmp_path, monkeypatch):
    monkeypatch.setattr("autopilot.config.NATIVE_WINDOWS", True)
    c = cfg_with(tmp_path, {"agent": {"backend": "claude_cli"}, "sandbox": {"mode": "docker", "image": "i"}})
    assert "WSL2" in sandbox_errs(c)[0]


def test_enabled_only_validates_as_before(tmp_path):
    c = cfg_with(tmp_path, {"agent": {"backend": "claude_cli"}, "sandbox": {"enabled": True}})
    assert sandbox_mode(c) == "allowlist" and sandbox_errs(c) == []
    c = cfg_with(tmp_path, {"agent": {"backend": "claude_cli"}, "sandbox": {"enabled": True, "allowed_domains": "x"}})
    assert "allowed_domains" in sandbox_errs(c)[0]
