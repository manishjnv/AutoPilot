"""Q4: every catalogue line turns a raw text into one sentence and one command; unknown text gets the generic line;
the raw text goes to the log and never to the screen."""
import os
from pathlib import Path

import pytest

from autopilot import install_errors as ie
from autopilot.doctor import RUNNERS
from autopilot.proc import Proc

# one raw text per catalogue id (the texts are what the tools print; the copilot ones are from the docs, not run live)
RAW = {
    "schannel": "curl: (35) schannel: next InitializeSecurityContext failed: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)",
    "no-host": "curl: (6) Could not resolve host: astral.sh",
    "timeout": "curl: (28) Connection timed out after 30001 milliseconds",
    "http-403": "curl: (22) The requested URL returned error: 403 Forbidden",
    "http-404": "error: HTTP 404 Not Found for https://github.com/manishjnv/AutoPilot/releases/download/v9.9.9/x.whl",
    "no-space": "OSError: [Errno 28] No space left on device",
    "permission": "npm ERR! Error: EACCES: permission denied, mkdir '/usr/lib/node_modules/@github'",
    "node-old": 'npm WARN EBADENGINE Unsupported engine { package: "@github/copilot@1.0.0", required: { node: ">=22" } }',
    "store-python": "Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut",
    "execution-policy": "install.ps1 cannot be loaded because running scripts is disabled on this system.",
    "not-on-path": "bash: ap: command not found",
    "logged-out-claude": "claude: Not logged in. Please run /login",
    "logged-out-copilot": "copilot: You are not logged in. Run `copilot login`",
    "logged-out-codex": "codex: not authenticated. Run codex login",
    "logged-out-cursor": "agent: Not signed in. Run `agent login`",
    "logged-out-kiro": "kiro-cli: not logged in",
    "no-plan-claude": '{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "free"}',
    "no-plan-copilot": "Error: your account does not have access to GitHub Copilot",
    "premium-requests-copilot": "You have reached your premium requests limit for this month.",
    "logged-out": "Error: no active session, please log in",
}


def test_every_catalogue_line_has_a_sample_and_every_sample_hits_its_line():
    ids = [e.id for e in ie.CATALOGUE]
    assert len(ids) == len(set(ids)) and set(ids) == set(RAW), set(ids) ^ set(RAW)
    assert ids.index("logged-out") == len(ids) - 1  # the generic login line comes after the per-runner ones


@pytest.mark.parametrize("entry_id", sorted(RAW))
def test_catalogue_line(entry_id):
    found, sentence, fix = ie.explain(RAW[entry_id], "win32" if entry_id in ("store-python", "execution-policy", "schannel") else "linux")
    assert found == entry_id, (found, sentence)
    assert sentence.endswith((".", ")")) and sentence.count(". ") <= 1 and len(sentence) < 160  # one sentence
    assert fix and "\n" not in fix  # one command


def test_unknown_text_gets_the_generic_line():
    assert ie.explain("Segmentation fault (core dumped)") == ("", ie.GENERIC, "")
    assert ie.explain("") == ("", ie.GENERIC, "")


def test_fix_commands_follow_the_os():
    assert "install.ps1" in ie.explain(RAW["schannel"], "win32")[2]
    assert ie.explain(RAW["schannel"], "linux")[2].startswith("curl --ssl-no-revoke")
    assert ie.explain(RAW["no-host"], "win32")[2].startswith("$env:HTTPS_PROXY")
    assert ie.explain(RAW["not-on-path"], "darwin")[2].startswith("export PATH=")
    assert ie.explain(RAW["store-python"], "linux")[0] == ""  # a Windows-only line never fires on Linux


def test_runner_lines_come_from_the_table():
    for r in RUNNERS:
        _, sentence, fix = ie.explain(f"{r.binary}: Not logged in", "linux")
        assert fix == r.login and r.plan in sentence, r.key


def test_capture_logs_the_raw_text_and_shows_three_plain_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path / "home"))
    said = []
    rc = ie.capture("install uv", ["bash", "-c", "x"], run=lambda *a, **k: Proc(35, "", RAW["schannel"] + "\nraw line 2\n"),
                    say=said.append, platform="win32")
    assert rc == 35 and len(said) == 3
    assert said[0] == "FAILED  install uv" and "Windows could not check the certificate" in said[1]
    assert "Run by hand: powershell" in said[2] and str(tmp_path / "home" / "install.log") in said[2]
    assert "CRYPT_E" not in "\n".join(said) and "raw line 2" not in "\n".join(said)
    log = (tmp_path / "home" / "install.log").read_text(encoding="utf-8")
    assert "CRYPT_E_NO_REVOCATION_CHECK" in log and "raw line 2" in log and "=== install uv: bash -c x -> exit 35" in log


def test_capture_success_is_silent_and_a_missing_program_is_127(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path / "home"))
    said = []
    assert ie.capture("ok step", ["true"], run=lambda *a, **k: Proc(0, "fine", ""), say=said.append) == 0 and said == []

    def boom(*a, **k):
        raise OSError("no such program")
    assert ie.capture("gone", ["nope"], run=boom, say=said.append) == 127 and said[0] == "FAILED  gone"
    assert ie.GENERIC in said[1]


def test_log_is_scrubbed_of_token_values(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path / "home"))
    env = {**os.environ, "GH_TOKEN": "ghp_fake000", "HTTPS_PROXY": "http://user:pw@proxy:3128"}
    ie.log_raw("step", "cmd", 1, "token ghp_fake000 via http://user:pw@proxy:3128", env=env)
    log = (tmp_path / "home" / "install.log").read_text(encoding="utf-8")
    assert "ghp_fake000" not in log and "pw@proxy" not in log and "***REDACTED[GH_TOKEN]***" in log


def test_exit_codes_are_stable():
    assert (ie.EXIT_OK, ie.EXIT_FAILED, ie.EXIT_USAGE, ie.EXIT_CHOICE) == (0, 1, 2, 3)
    assert ie.log_path(Path("/h")).as_posix().endswith(".autopilot/install.log") or os.environ.get("AUTOPILOT_HOME")
