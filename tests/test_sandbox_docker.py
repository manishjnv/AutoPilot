"""W11: sandbox.mode, the one mode rule and its config checks."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

from autopilot.backends import SessionRequest, docker_box
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.backends.docker_box import docker_argv, login_dir
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


# P11-T02: the docker run wrapper of the Claude CLI backend. No test calls the real docker.
CMD = ["/usr/local/bin/claude", "-p", "--output-format", "stream-json", "--model", "sonnet"]


def argv_for(tmp_path, monkeypatch, git=(), **kv):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "example-fake-key")
    cfg = Fake(**{"sandbox.mode": "docker", "sandbox.image": "my-autopilot", **kv})
    cwd, login = str(tmp_path / "wt"), str(tmp_path / "login")
    return docker_argv(cfg, CMD, cwd, login, git, (1000, 1000), dict(os.environ)), cwd


def test_docker_argv_mounts_the_worktree_at_work(tmp_path, monkeypatch):
    argv, cwd = argv_for(tmp_path, monkeypatch)
    assert argv[:4] == ["docker", "run", "--rm", "-i"] and "--rm" in argv
    assert f"{cwd}:/work" in argv and argv[argv.index("-w") + 1] == "/work"
    assert argv[argv.index("--network") + 1] == "bridge"
    assert argv[argv.index("--user") + 1] == "1000:1000" and "HOME=/tmp" in argv
    assert argv[-len(CMD) - 1:] == ["my-autopilot", "claude", *CMD[1:]]
    assert CMD[0] not in argv


def test_docker_argv_never_mounts_home_or_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "dummy-oauth-example")
    argv, _ = argv_for(tmp_path, monkeypatch)
    home = str(Path.home())
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert not any(m.split(":/")[0] in (home, home.rstrip("/\\")) for m in mounts)
    assert all("example-fake-key" not in a and "dummy-oauth-example" not in a for a in argv)
    pairs = list(zip(argv, argv[1:]))
    assert ("-e", "ANTHROPIC_API_KEY") in pairs and ("-e", "CLAUDE_CODE_OAUTH_TOKEN") in pairs
    assert ("-e", "CLAUDE_CONFIG_DIR=/claude") in pairs


def test_docker_argv_mounts_git_dirs_common_read_only(tmp_path, monkeypatch):
    common, own = str(tmp_path / "repo" / ".git"), str(tmp_path / "repo" / ".git" / "worktrees" / "wt")
    argv, _ = argv_for(tmp_path, monkeypatch, git=(common, own), **{"sandbox.network": "none"})
    assert f"{common}:{common}:ro" in argv and f"{own}:{own}" in argv
    assert argv[argv.index("--network") + 1] == "none"


def test_docker_argv_skips_git_dirs_inside_the_worktree(tmp_path, monkeypatch):
    inner = str(tmp_path / "wt" / ".git")
    argv, cwd = argv_for(tmp_path, monkeypatch, git=(inner, inner))
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "-v"] == [f"{cwd}:/work", f"{tmp_path / 'login'}:/claude"]


def test_env_names_cover_backend_knobs_never_host_paths():
    env = {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku", "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "PATH": "/bin",
           "AUTOPILOT_CLAUDE_BIN": "/x/claude", "CLAUDE_CONFIG_DIR": "/h/.claude"}
    names = docker_box.env_names(Fake(**{"agent.env": {"MY_TOOL_TOKEN": "fake"}}), env)
    assert {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_SUBAGENT_MODEL",
            "ENABLE_CLAUDEAI_MCP_SERVERS", "MY_TOOL_TOKEN"} <= set(names)
    assert not {"PATH", "AUTOPILOT_CLAUDE_BIN", "CLAUDE_CONFIG_DIR"} & set(names)


def test_build_cmd_unchanged_when_mode_off_or_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", "/fake/claude")
    req = SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path))
    plain = ClaudeCLIBackend(cfg_with(tmp_path, {})).build_cmd(req)
    assert ClaudeCLIBackend(cfg_with(tmp_path, {"sandbox": {"mode": "off"}})).build_cmd(req) == plain
    assert plain[0] == "/fake/claude" and "--settings" not in plain and "docker" not in plain
    allow = ClaudeCLIBackend(cfg_with(tmp_path, {"sandbox": {"enabled": True}})).build_cmd(req)
    assert "--settings" in allow and "--strict-mcp-config" in allow
    docker = ClaudeCLIBackend(cfg_with(tmp_path, {"sandbox": {"mode": "docker", "image": "i"}})).build_cmd(req)
    assert docker == plain  # the wrap happens in run(), around the unchanged argv


def test_login_dir_copies_credentials_and_is_removed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text('{"token": "fake-example"}', encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    with login_dir() as d:
        assert Path(d, ".credentials.json").read_text(encoding="utf-8") == '{"token": "fake-example"}'
        assert not Path(d).is_relative_to(tmp_path) and Path(d) != home
        if sys.platform != "win32":
            assert Path(d, ".credentials.json").stat().st_mode & 0o777 == 0o600
    assert not Path(d).exists()


def test_login_dir_without_credentials_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with login_dir() as d:
        assert os.listdir(d) == []
    assert not Path(d).exists()


def test_git_dirs_none_outside_a_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert docker_box.git_dirs(str(tmp_path)) == ()


def test_wrapped_removes_the_container_and_login_folder(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(docker_box, "run_proc", lambda cmd, **kw: calls.append(cmd) or (_ for _ in ()).throw(OSError()))
    with docker_box.wrapped(Fake(**{"sandbox.image": "i"}), CMD, str(tmp_path), {}) as argv:
        login = argv[argv.index("CLAUDE_CONFIG_DIR=/claude") + 2].rsplit(":/claude", 1)[0]
        assert Path(login).is_dir()
    name = argv[argv.index("--name") + 1]
    assert name.startswith("autopilot-") and calls[-1] == ["docker", "rm", "-f", name]
    assert not Path(login).exists()


def test_run_in_docker_mode_calls_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "example-fake-key")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", "/fake/claude")
    calls = tmp_path / "calls.jsonl"
    result = json.dumps({"type": "result", "result": "ok", "session_id": "s1", "total_cost_usd": 0.01})
    if sys.platform != "win32":  # a fake `docker` script on PATH records its argv and answers like claude
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        script = bin_dir / "docker"
        script.write_text(f"#!{sys.executable}\nimport json, sys\nopen({str(calls)!r}, 'a').write(json.dumps("
                          f"sys.argv[1:]) + chr(10))\nsys.stdin.read()\nprint({result!r})\n")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    else:  # Windows CreateProcess finds no script named `docker`: record the two calls in process instead
        from autopilot.backends import claude_cli
        from autopilot.proc import Proc, run_proc

        def fake(cmd, **kw):
            if cmd[0] != "docker":  # git rev-parse runs for real
                return run_proc(cmd, **kw)
            with open(calls, "a", encoding="utf-8") as f:
                f.write(json.dumps(cmd[1:]) + "\n")
            return Proc(rc=0, stdout=result + "\n", stderr="")
        monkeypatch.setattr(claude_cli, "stream_proc", lambda cmd, on_line=None, **kw: fake(cmd))
        monkeypatch.setattr(docker_box, "run_proc", fake)
    cfg = cfg_with(tmp_path, {"agent": {"backend": "claude_cli"}, "sandbox": {"mode": "docker", "image": "my-img"}})
    res = ClaudeCLIBackend(cfg).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert calls.exists(), res.error
    runs = [json.loads(ln) for ln in calls.read_text(encoding="utf-8").splitlines()]
    first = runs[0]
    assert first[:4] == ["run", "--rm", "-i", "--name"] and first[4].startswith("autopilot-")
    assert first[first.index("my-img"):][:3] == ["my-img", "claude", "-p"]
    assert "/fake/claude" not in first and not any("example-fake-key" in a for a in first)
    assert runs[-1] == ["rm", "-f", first[4]]
    assert res.ok and res.text == "ok"


def fake_docker(tmp_path, monkeypatch, text="Docker version 27.1.1, build abc"):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if os.name == "nt":  # Windows runs only .exe files through Popen, and a copied python.exe cannot load its DLLs
        monkeypatch.setattr("autopilot.doctor._run", lambda cmd, **k: (0, text) if cmd[:1] == ["docker"] else (0, ""))
    else:
        script = bindir / "docker"
        script.write_text("#!/bin/sh\necho " + repr(text) + "\n", encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    return bindir


def docker_rows(tmp_path, data):
    from autopilot import doctor
    rows = doctor.checks(cfg_with(tmp_path, data))
    return [r for r in rows if r[1] == "docker"]


def test_doctor_docker_row_ok_when_docker_is_on_path(tmp_path, monkeypatch):
    fake_docker(tmp_path, monkeypatch)
    rows = docker_rows(tmp_path, {"sandbox": {"mode": "docker", "image": "my-autopilot"}})
    assert rows == [("ok", "docker", "found 27.1.1")]


def test_doctor_docker_row_fails_without_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    rows = docker_rows(tmp_path, {"sandbox": {"mode": "docker", "image": "my-autopilot"}})
    assert rows == [("FAIL", "docker", "not found (needed for sandbox.mode: docker)")]


def test_doctor_has_no_docker_row_when_mode_is_off(tmp_path, monkeypatch):
    fake_docker(tmp_path, monkeypatch)
    assert docker_rows(tmp_path, {"sandbox": {"mode": "off"}}) == []
    assert docker_rows(tmp_path, {"sandbox": {"mode": "allowlist"}}) == []


def test_doctor_sandbox_row_follows_allowlist_on(tmp_path, monkeypatch):
    from autopilot import doctor
    monkeypatch.setattr("autopilot.doctor.sys.platform", "linux")
    monkeypatch.setattr("autopilot.doctor.shutil.which", lambda b, **k: None)
    for data in ({"sandbox": {"mode": "allowlist"}}, {"sandbox": {"enabled": True}}):
        rows = [r for r in doctor.checks(cfg_with(tmp_path, data)) if r[1] == "sandbox"]
        assert rows and rows[0][0] == "FAIL"


def test_gate_protects_settings_when_allowlist_mode_is_on(tmp_path):
    from autopilot.gate import protected_files
    c = cfg_with(tmp_path, {"sandbox": {"mode": "allowlist"}})
    assert ".mcp.json" in protected_files(c)
    off = cfg_with(tmp_path, {"sandbox": {"mode": "docker", "image": "i"}})
    assert ".mcp.json" not in protected_files(off)
