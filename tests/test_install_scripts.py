"""Q5: thin install scripts. Every program they meet here is a fake on a temporary PATH; no download, no install."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH, PS1, CMD = ROOT / "install.sh", ROOT / "install.ps1", ROOT / "install.cmd"
posix = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs a POSIX bash")


def fakes(tmp_path, **scripts):
    """A tmp PATH folder with one fake program per name (a sh script body); the real bash and coreutils stay reachable."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    for name, body in scripts.items():
        (d / name).write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        (d / name).chmod(0o755)
    for tool in ("bash", "sh", "tail", "cat", "rm", "mkdir", "date", "grep", "dirname", "head", "tr", "sed"):
        real = shutil.which(tool)
        if real and not (d / tool).exists():
            os.symlink(real, d / tool)
    return str(d)


def run_sh(tmp_path, path, *args, **env):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    e = {"HOME": str(home), "PATH": path, "AUTOPILOT_HOME": str(home / ".autopilot"), **env}
    return subprocess.run(["/bin/bash", str(SH), *args], capture_output=True, text=True, env=e)


def test_scripts_stay_thin_and_keep_the_bump_lines():
    assert len(SH.read_text(encoding="utf-8").splitlines()) < 150
    assert len(PS1.read_text(encoding="utf-8").splitlines()) < 220
    assert len(CMD.read_text(encoding="utf-8").splitlines()) <= 12
    assert "\nDEFAULT_REF=v" in SH.read_text(encoding="utf-8") and "\n$DefaultRef = 'v" in PS1.read_text(encoding="utf-8")
    for text in (SH.read_text(encoding="utf-8"), PS1.read_text(encoding="utf-8")):
        assert "ap setup" in text and "This script installs: uv, Python 3.12 (when missing), Autopilot." in text
        assert "claude.ai/install" not in text  # Q5: no runner install in the scripts; `ap setup` names the runner


@posix
def test_fake_schannel_curl_failing_with_35_gets_one_retry_note(tmp_path):
    """The friend's PC: a Schannel curl fails the revocation check (35); the script retries once with --ssl-no-revoke."""
    curl = ('case "$*" in *-V*) echo "curl 8.9.1 (Windows) libcurl/8.9.1 Schannel"; exit 0;; esac\n'
            'case "$*" in *--ssl-no-revoke*) exit 0;; esac\n'
            'echo "curl: (35) schannel: next InitializeSecurityContext failed: CRYPT_E_NO_REVOCATION_CHECK" >&2; exit 35')
    p = run_sh(tmp_path, fakes(tmp_path, curl=curl), "--dry-run", AUTOPILOT_PROBE="1")
    assert p.returncode == 0, p.stderr
    notes = [l for l in p.stdout.splitlines() if l.startswith("note: curl could not check certificate revocation")]
    assert len(notes) == 1 and "--ssl-no-revoke" in notes[0]  # once, then kept for the run
    assert "found: astral.sh, pypi.org, github.com reachable" in p.stdout
    assert "CRYPT_E" not in p.stdout  # raw curl text never reaches the screen


@posix
def test_unreachable_hosts_are_reported_together_in_plain_words(tmp_path):
    curl = ('case "$*" in *-V*) echo "curl 8 OpenSSL"; exit 0;; esac\n'
            'case "$*" in *pypi.org*) exit 0;; esac\n'
            'echo "curl: (6) Could not resolve host" >&2; exit 6')
    p = run_sh(tmp_path, fakes(tmp_path, curl=curl), AUTOPILOT_PROBE="1")
    assert p.returncode == 1
    assert "FAILED  step 1: pre-check" in p.stderr and "No connection to the download server" in p.stderr
    assert "astral.sh github.com" in (p.stderr + p.stdout).replace("https://", "") or "astral.sh" in p.stderr
    assert "Could not resolve host" not in p.stdout and "install.log" in p.stderr
    assert "Could not resolve host" in (tmp_path / "home" / ".autopilot" / "install.log").read_text(encoding="utf-8")


@posix
def test_git_bash_hands_over_to_powershell_with_the_same_options(tmp_path):
    ps = 'echo "PS1 $*"; exit 0'
    path = fakes(tmp_path, **{"powershell.exe": ps})
    p = run_sh(tmp_path, path, "--dry-run", "--skip-login", "--yes", "--runner", "copilot", OSTYPE="msys")
    assert p.returncode == 0, p.stderr
    assert "install.ps1 takes over" in p.stdout
    line = next(l for l in p.stdout.splitlines() if l.startswith("PS1 "))
    assert "-NoProfile -ExecutionPolicy Bypass -File" in line and line.endswith("install.ps1 -DryRun -SkipLogin -Yes -Runner copilot")
    assert "==> Step 2" not in p.stdout  # nothing else ran in bash


@posix
def test_options_pass_through_to_ap_setup_and_bad_ones_are_usage(tmp_path):
    ap = 'echo "AP $*"; exit 0'
    p = run_sh(tmp_path, fakes(tmp_path, ap=ap), "--dry-run", "--runner=codex", "--yes", "--skip-login")
    assert p.returncode == 0, p.stderr
    assert "AP setup --dry-run --skip-login --yes --runner codex" in p.stdout
    assert run_sh(tmp_path, fakes(tmp_path), "--runner", "nope").returncode == 2
    assert run_sh(tmp_path, fakes(tmp_path), "--bogus").returncode == 2


@posix
def test_setup_exit_3_is_passed_through_with_one_hint(tmp_path):
    ap = 'case "$*" in --version) echo "ap 0.4.0";; *) echo "ap setup --runner copilot"; exit 3;; esac'
    curl = 'exit 0'
    path = fakes(tmp_path, ap=ap, autopilot=ap, curl=curl, uv='echo uv 0.9', python3='exit 0')
    p = run_sh(tmp_path, path)
    assert p.returncode == 3 and "Run the line above to name your runner" in p.stdout


@posix
def test_a_failed_step_prints_three_lines_and_logs_the_raw_text(tmp_path):
    curl = 'case "$*" in *-V*) echo "curl 8 OpenSSL"; exit 0;; *-sSI*) exit 0;; esac; echo "boom raw text EACCES" >&2; exit 1'
    p = run_sh(tmp_path, fakes(tmp_path, curl=curl, python3="exit 0"))
    assert p.returncode == 1
    assert "FAILED  step 2: uv" in p.stderr and "No permission to write" in p.stderr and "Run by hand: curl" in p.stderr
    assert "boom raw text" not in p.stdout + p.stderr
    assert "boom raw text" in (tmp_path / "home" / ".autopilot" / "install.log").read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("pwsh"), reason="needs PowerShell 7")
def test_install_ps1_parses():
    check = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$null, [ref]$e); "
             "if ($e.Count) { $e; exit 1 }" % str(PS1).replace("'", "''"))
    assert subprocess.run(["pwsh", "-NoProfile", "-Command", check], capture_output=True, text=True).returncode == 0


def test_cmd_wrapper_only_starts_powershell():
    text = CMD.read_text(encoding="utf-8")
    assert text.count("powershell -NoProfile -ExecutionPolicy Bypass") == 2 and "%*" in text
    assert "install.ps1" in text and "exit /b %ERRORLEVEL%" in text
