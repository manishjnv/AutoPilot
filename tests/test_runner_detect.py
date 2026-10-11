"""N3, P03-T02: detect_runner finds the first installed and logged-in agent CLI on PATH."""
import json
import os
import sys
import time

import pytest

from autopilot import doctor
from autopilot.doctor import RUNNERS, detect_runner

FAKE = (
    "import json,sys,time\n"
    "mode, log = sys.argv[1], sys.argv[2]\n"
    "open(log, 'a', encoding='utf-8').write(json.dumps(sys.argv[3:]) + '\\n')\n"
    "if mode == 'hang': time.sleep(60)\n"
    "if mode == 'in': print('Logged in as fake-user@example.com'); sys.exit(0)\n"
    "if mode == 'out0': print('Not logged in'); sys.exit(0)\n"
    "print('Not logged in. Run login first.'); sys.exit(1)\n")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    """No real key from this machine may count: every key variable of RUNNERS is removed."""
    for _, _, _, keys in RUNNERS:
        for k in keys:
            monkeypatch.delenv(k, raising=False)


def fake_bin(tmp_path, **modes):
    """A tmp PATH folder with one fake CLI per name; mode is `in`, `out`, `out0` or `hang`. Each call is logged."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "fake.py").write_text(FAKE)
    for name, mode in modes.items():
        log = tmp_path / f"{name}.log"
        if sys.platform == "win32":
            (bindir / f"{name}.cmd").write_text(f'@"{sys.executable}" "%~dp0fake.py" {mode} "{log}" %*\n')
        else:
            exe = bindir / name
            exe.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" \"{bindir / 'fake.py'}\" {mode} \"{log}\" \"$@\"\n")
            exe.chmod(0o755)
    return str(bindir)


def calls(tmp_path, name):
    log = tmp_path / f"{name}.log"
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def env_with(path, **extra):
    return {**os.environ, "PATH": path, **extra}


def test_only_kiro_logged_in(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "in"})
    assert detect_runner(env_with(path)) == "kiro"
    assert calls(tmp_path, "kiro-cli") == [["whoami"]]


def test_claude_logged_out_falls_through_to_kiro(tmp_path):
    path = fake_bin(tmp_path, claude="out", **{"kiro-cli": "in"})
    assert detect_runner(env_with(path)) == "kiro"
    assert calls(tmp_path, "claude") == [["auth", "status"]]


def test_order_is_respected(tmp_path):
    path = fake_bin(tmp_path, claude="in", **{"kiro-cli": "in"})
    assert detect_runner(env_with(path)) == "claude_cli"
    assert calls(tmp_path, "kiro-cli") == []  # never asked: claude came first


def test_empty_path_is_none(tmp_path):
    assert detect_runner({"PATH": ""}) is None
    assert detect_runner({}) is None
    assert detect_runner(env_with(str(tmp_path))) is None  # a folder with no agent CLI


def test_hanging_login_check_is_stopped_by_the_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "LOGIN_TIMEOUT", 1)
    path = fake_bin(tmp_path, **{"kiro-cli": "hang", "cursor-agent": "in"})
    start = time.monotonic()
    assert detect_runner(env_with(path)) == "cursor"
    assert time.monotonic() - start < 30
    assert calls(tmp_path, "cursor-agent") == [["status"]]


def test_logged_out_wording_with_exit_0_is_not_logged_in(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "out0", "codex": "in"})
    assert detect_runner(env_with(path)) == "codex"
    assert calls(tmp_path, "codex") == [["login", "status"]]


def test_key_variable_counts_without_a_status_command(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "out", "gemini": "out", "aider": "out"})
    assert detect_runner(env_with(path)) is None  # gemini and aider have no status command and no key
    assert detect_runner(env_with(path, GEMINI_API_KEY="fake-example-key")) == "gemini"
    assert detect_runner(env_with(path, KIRO_API_KEY="fake-example-key")) == "kiro"
    assert detect_runner(env_with(path, OPENROUTER_API_KEY="")) is None  # an empty key does not count
    assert calls(tmp_path, "gemini") == [] and calls(tmp_path, "aider") == []


def test_claude_key_counts(tmp_path):
    path = fake_bin(tmp_path, claude="out", **{"kiro-cli": "in"})
    assert detect_runner(env_with(path, ANTHROPIC_API_KEY="fake-example-key")) == "claude_cli"
    assert calls(tmp_path, "claude") == []  # key first: no process


def test_never_starts_a_login(tmp_path):
    names = {b: "out" for b, _, _, _ in RUNNERS}
    path = fake_bin(tmp_path, **names)
    assert detect_runner(env_with(path)) is None
    for name in names:
        for argv in calls(tmp_path, name):
            assert argv[:1] != ["login"] or argv == ["login", "status"]
            assert "--with-api-key" not in argv
