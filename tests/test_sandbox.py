"""P5: network egress allowlist through Claude Code's own sandbox (--settings), opt-in via sandbox.enabled."""
import json

import yaml

from autopilot.backends import SessionRequest
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config


def cfg_with(tmp_path, data):
    (tmp_path / ".agent").mkdir(exist_ok=True)
    (tmp_path / ".agent" / "project.yaml").write_text(yaml.safe_dump(data))
    return Config.load(tmp_path)


def cmd(cfg, **kw):
    return ClaudeCLIBackend(cfg).build_cmd(SessionRequest(prompt="x", model="sonnet", cwd=".", **kw))


def denied(c):
    return c[c.index("--disallowedTools") + 1:] if "--disallowedTools" in c else []


def test_off_by_default(tmp_path):
    c = cmd(Config.load(tmp_path))
    assert "--settings" not in c and "WebFetch" not in denied(c)


def test_allowlist_reaches_the_cli_and_code_sessions_lose_web_tools(tmp_path):
    cfg = cfg_with(tmp_path, {"sandbox": {"enabled": True, "allowed_domains": ["pypi.org", "github.com"]}})
    c = cmd(cfg)
    sb = json.loads(c[c.index("--settings") + 1])["sandbox"]
    assert sb["enabled"] and sb["failIfUnavailable"] and sb["allowUnsandboxedCommands"] is False
    assert sb["network"]["allowedDomains"] == ["pypi.org", "github.com"]
    assert {"WebFetch", "WebSearch"} <= set(denied(c)) and "--strict-mcp-config" in c  # no project MCP servers
    assert "WebFetch" in denied(cmd(cfg, read_only=True))  # audit/decide/unstick read the repo: no web either
    research = cmd(cfg, web_only=True, read_only=True)  # the web, but not the repo
    assert "WebFetch" not in denied(research) and {"Read", "Grep", "Glob", "Bash"} <= set(denied(research))


def test_agents_may_not_widen_the_allowlist(tmp_path, monkeypatch):
    from autopilot.gate import protected_files
    monkeypatch.setattr("autopilot.config.NATIVE_WINDOWS", False)  # CI also runs on Windows
    assert ".claude/settings.json" not in protected_files(Config.load(tmp_path))
    cfg = cfg_with(tmp_path, {"sandbox": {"enabled": True}, "agent": {"extra_args": ["--settings=x.json"]}})
    assert {".claude/settings.json", ".claude/settings.local.json", ".mcp.json"} <= set(protected_files(cfg))
    assert any("would override the sandbox" in e for e in cfg._sandbox_errors())


def test_config_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("autopilot.config.NATIVE_WINDOWS", False)  # CI also runs on Windows
    cfg = cfg_with(tmp_path, {"sandbox": {"enabled": True}, "agent": {"backend": "command", "command": "x"}})
    assert any("claude_cli" in e for e in cfg.blocking_errors())
    cfg = cfg_with(tmp_path, {"sandbox": {"enabled": True, "allowed_domains": "pypi.org"}})
    assert any("must be a list" in e for e in cfg._sandbox_errors())
    monkeypatch.setattr("autopilot.config.NATIVE_WINDOWS", True)
    assert any("native Windows" in e for e in cfg._sandbox_errors())
    monkeypatch.setattr("autopilot.config.NATIVE_WINDOWS", False)
    assert cfg_with(tmp_path, {"sandbox": {"enabled": True, "allowed_domains": []}})._sandbox_errors() == []
