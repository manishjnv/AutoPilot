"""Q13: the login address and code are on the screen as text, in the browser form and in the headless form. Every login
here is a fake script; nothing opens a browser or reaches a vendor."""
import sys
from pathlib import Path

import pytest

from autopilot import login as lg
from autopilot.doctor import RUNNERS, runner

URL = "https://github.com/login/device"

# a fake login: prints the address and a code, then ends 0; with `fail` as the first argument it ends 1; `hang` waits
FAKE = ("import sys, time\n"
        "mode = sys.argv[-1]\n"
        f"print('Open {URL} and enter the code ABCD-1234')\n"
        "sys.stdout.flush()\n"
        "if mode == 'hang': time.sleep(60)\n"
        "sys.exit(1 if mode == 'fail' else 0)\n")


def fake_row(tmp_path: Path, mode: str, headless: str = "") -> tuple:
    script = tmp_path / "fakelogin.py"
    script.write_text(FAKE, encoding="utf-8")
    exe = tmp_path / ("copilot.cmd" if sys.platform == "win32" else "copilot")
    if sys.platform == "win32":
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        exe.chmod(0o755)
    base = runner("copilot")
    from dataclasses import replace
    return replace(base, login=f"copilot login {mode}", login_headless=headless or f"copilot login --device-code {mode}"), str(exe)


DESKTOP = {"DISPLAY": ":0", "HOME": "/h"}


def test_desktop_mode_runs_the_normal_login_and_still_prints_the_address(tmp_path):
    row, exe = fake_row(tmp_path, "ok")
    said = []
    assert lg.login_runner(row, exe, env=DESKTOP, say=said.append, platform="linux", exists=lambda p: False)
    text = "\n".join(said)
    assert "opens in your browser" in text and f"address   {URL}" in text and "code      ABCD-1234" in text
    assert "--device-code" not in text  # the normal form ran
    assert "login     copilot: done" in text


def test_wsl_chooses_the_headless_command_and_prints_the_address_as_text(tmp_path):
    row, exe = fake_row(tmp_path, "ok")
    said = []
    assert lg.login_runner(row, exe, env={"WSL_DISTRO_NAME": "Ubuntu"}, say=said.append, platform="linux", exists=lambda p: False)
    text = "\n".join(said)
    assert "this is WSL: no browser is opened" in text and "copilot login --device-code ok" in text
    assert f"address   {URL}" in text and "code      ABCD-1234" in text


@pytest.mark.parametrize("env,exists,why", [
    ({"WSL_DISTRO_NAME": "Ubuntu"}, lambda p: False, "WSL"),
    ({"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22"}, lambda p: False, "SSH"),
    ({"DISPLAY": ":0"}, lambda p: p == "/.dockerenv", "container"),
    ({"DISPLAY": ":0", "SNAP": "/snap/x"}, lambda p: False, "snap"),
    ({}, lambda p: False, "no desktop"),
])
def test_every_headless_trigger_is_found(env, exists, why):
    assert why in lg.headless_why(env, "linux", exists)


def test_a_desktop_and_a_windows_machine_are_not_headless():
    assert lg.headless_why({"DISPLAY": ":0"}, "linux", lambda p: False) == ""
    assert lg.headless_why({"BROWSER": "firefox"}, "linux", lambda p: False) == ""
    assert lg.headless_why({}, "win32", lambda p: False) == ""
    assert lg.headless_why({}, "darwin", lambda p: False) == ""


def test_a_failed_login_says_the_command_to_run_by_hand(tmp_path):
    row, exe = fake_row(tmp_path, "fail")
    said = []
    assert not lg.login_runner(row, exe, env=DESKTOP, say=said.append, platform="linux", exists=lambda p: False)
    assert "did not finish" in "\n".join(said) and "copilot login fail" in "\n".join(said)


def test_a_login_that_waits_is_stopped_at_the_wait_limit(tmp_path):
    row, exe = fake_row(tmp_path, "hang")
    said = []
    assert not lg.login_runner(row, exe, env=DESKTOP, say=said.append, wait=1, platform="linux", exists=lambda p: False)
    assert f"address   {URL}" in "\n".join(said) and "the code has expired" in "\n".join(said)


def test_every_row_has_a_headless_form_that_starts_with_its_own_binary():
    for r in RUNNERS:
        assert r.login_headless.split()[0] == r.login.split()[0] == r.binary, r.key


def test_setup_calls_the_login_hook_for_every_runner_and_rechecks(tmp_path, monkeypatch):
    from test_setup import Machine
    m = Machine(tmp_path, monkeypatch, codex="out")
    asked = []
    assert m.setup(login=lambda row: asked.append(row.key) or False) == 0
    assert asked == ["codex"] and "login     codex: not logged in. Run `codex login`" in m.text
