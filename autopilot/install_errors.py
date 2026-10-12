"""Q4: errors in plain words. Every command the installer or `ap setup` runs is captured; the raw output goes to
`~/.autopilot/install.log` through `log_scrub`, never to the screen. The screen gets three lines on a failure: what
failed, one sentence, one command to run by hand (and the log path). One catalogue, one entry per known text."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .log_scrub import scrub_secrets
from .proc import run_proc

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_CHOICE = 0, 1, 2, 3  # stable: 0 ok, 1 a step failed, 2 bad usage, 3 a choice is needed
GENERIC = "The step did not finish. The full output is in the log."
# token variables whose values are scrubbed from the log (presence is all Autopilot ever reads of them)
SECRET_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "COPILOT_GITHUB_TOKEN",
               "GH_TOKEN", "GITHUB_TOKEN", "CODEX_API_KEY", "CURSOR_API_KEY", "KIRO_API_KEY", "OPENAI_API_KEY",
               "GEMINI_API_KEY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")


def os_name(platform: str | None = None) -> str:
    p = platform or sys.platform
    return "windows" if p.startswith("win") else "darwin" if p == "darwin" else "linux"


def log_path(home: Path | None = None) -> Path:
    base = Path(os.environ.get("AUTOPILOT_HOME") or (home or Path.home()) / ".autopilot")
    return base / "install.log"


def secrets(env: dict | None = None) -> dict[str, str]:
    """name -> value of every token variable that is set, for `scrub_secrets`. Never printed or logged."""
    env = os.environ if env is None else env
    out = {k: str(env[k]) for k in SECRET_VARS if env.get(k)}
    if env.get("HTTPS_PROXY") or env.get("https_proxy"):  # a proxy URL may carry a password
        for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            if env.get(k) and "@" in env[k]:
                out[k] = env[k]
    return out


def log_raw(step: str, cmd: str, rc: int, text: str, env: dict | None = None, home: Path | None = None) -> Path:
    """Append one block to the install log; the text is scrubbed first. Returns the log path."""
    p = log_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(f"\n=== {step}: {cmd} -> exit {rc}\n{scrub_secrets(text, secrets(env)).rstrip()}\n")
    return p


@dataclass(frozen=True)
class Entry:
    id: str
    rx: str                  # matched against the raw output, case-insensitive
    sentence: str            # one plain sentence a user reads
    fix: dict | str          # the command to run by hand: one string, or one per os (`linux`, `darwin`, `windows`)
    os: tuple = ()           # empty = every system

    def fix_for(self, platform: str | None = None) -> str:
        return self.fix if isinstance(self.fix, str) else self.fix.get(os_name(platform), "")


CATALOGUE: tuple[Entry, ...] = ()  # filled below (Q4); the runner rows add their own lines


def explain(text: str, platform: str | None = None) -> tuple[str, str, str]:
    """(entry id or '', sentence, fix command) for a raw output. Unknown text: ('', GENERIC, '')."""
    o = os_name(platform)
    for e in CATALOGUE:
        if (not e.os or o in e.os) and re.search(e.rx, text or "", re.I | re.M):
            return e.id, e.sentence, e.fix_for(platform)
    return "", GENERIC, ""


def three_lines(step: str, text: str, log: Path, platform: str | None = None, cmd: str = "") -> list[str]:
    """What the screen shows on a failure: what failed, the sentence, the command (and the log path)."""
    _, sentence, fix = explain(text, platform)
    return [f"FAILED  {step}", f"        {sentence}",
            f"        Run by hand: {fix or cmd or '(see the log)'}  -- details: {log}"]


def capture(step: str, cmd, *, shell: bool = False, env: dict | None = None, timeout: float = 900, run=run_proc,
            say=print, platform: str | None = None, home: Path | None = None, cwd=None) -> int:
    """Run one install step. Output goes to the log only; on a failure the three lines go to the screen. Returns the
    exit code (127 when the program cannot start)."""
    shown = cmd if isinstance(cmd, str) else " ".join(cmd)
    try:
        p = run(cmd, shell=shell, env=env, timeout=timeout, cwd=cwd)
        rc, text = p.rc, (p.stdout or "") + (p.stderr or "")
    except OSError as exc:
        rc, text = 127, str(exc)
    log = log_raw(step, shown, rc, text, env, home)
    if rc != 0:
        for line in three_lines(step, text, log, platform, shown):
            say(line)
    return rc
