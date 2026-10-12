"""Q4: errors in plain words. Every command the installer or `ap setup` runs is captured; the raw output goes to
`~/.autopilot/install.log` through `log_scrub`, never to the screen. The screen gets three lines on a failure: what
failed, one sentence, one command to run by hand (and the log path). One catalogue, one entry per known text."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .doctor import LOGGED_OUT, RUNNERS
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


PS1 = "irm https://raw.githubusercontent.com/manishjnv/AutoPilot/main/install.ps1 | iex"
SH = "https://raw.githubusercontent.com/manishjnv/AutoPilot/main/install.sh"
PROXY = {"linux": "export HTTPS_PROXY=http://proxy.example:3128   # your proxy address", "darwin":
         "export HTTPS_PROXY=http://proxy.example:3128   # your proxy address",
         "windows": "$env:HTTPS_PROXY = 'http://proxy.example:3128'   # your proxy address"}
LOCAL_BIN = {"linux": 'export PATH="$HOME/.local/bin:$PATH"', "darwin": 'export PATH="$HOME/.local/bin:$PATH"',
             "windows": '$env:PATH = "$env:USERPROFILE\\.local\\bin;$env:PATH"'}


def _runner_entries() -> list[Entry]:
    """One logged-out line and one no-plan line per runner row (the table is the one source, Q1)."""
    out = []
    for r in RUNNERS:
        names = "|".join(re.escape(n) for n in r.names)
        out.append(Entry(f"logged-out-{r.name}", rf"(?s)^(?=.*\b(?:{names})\b)(?=.*(?:{LOGGED_OUT.pattern}))",
                         f"{r.name} is not logged in: log in once, then start again (you need {r.plan}).", r.login))
    out.append(Entry("no-plan-claude", r'subscriptionType"?\s*:\s*"?free|the free Claude plan|requires a (?:Pro|Max) (?:plan|subscription)',
                     "The free Claude plan cannot use Claude Code: a paid plan (Pro or Max) is needed.",
                     "claude auth login   # with the account that has the plan"))
    # copilot: docs checked 2026-10-12, not run live; the exact wording comes from Q9
    out.append(Entry("no-plan-copilot", r"no (?:active )?Copilot (?:subscription|plan|license|seat)|Copilot (?:subscription|plan|license) (?:is )?(?:required|needed)"
                     r"|(?:do not|don't|does not) have access to (?:GitHub )?Copilot",
                     "This GitHub account has no Copilot plan: Autopilot needs a paid Copilot plan.",
                     "https://github.com/features/copilot/plans   # then: copilot login"))
    out.append(Entry("premium-requests-copilot", r"premium requests? (?:limit|quota)|(?:limit|quota) (?:of|for|on) premium requests?"
                     r"|premium requests? .{0,20}\b(?:exhausted|exceeded|used up)",
                     "The Copilot premium requests of this month are used up: wait for the reset, or name a second runner.",
                     "ap setup --runner claude   # or set agent.fallback in .agent/project.yaml"))
    return out


CATALOGUE: tuple[Entry, ...] = (
    Entry("schannel", r"CRYPT_E_NO_REVOCATION_CHECK|curl: \(35\)|schannel: next InitializeSecurityContext failed",
          "Windows could not check the certificate of the download server (a proxy or a security program blocks the revocation check).",
          {"windows": f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{PS1}"', "linux": f"curl --ssl-no-revoke -fsSL {SH} | bash",
           "darwin": f"curl -fsSL {SH} | bash"}),
    Entry("no-host", r"Could not resolve host|getaddrinfo|ENOTFOUND|EAI_AGAIN|Name or service not known|No such host is known|nodename nor servname",
          "No connection to the download server: check the network, and set HTTPS_PROXY when a proxy is in the way.", PROXY),
    Entry("timeout", r"timed? out|ETIMEDOUT|curl: \(28\)|Connection timed out",
          "The download server did not answer in time: the network or a proxy is slow or blocked.", PROXY),
    Entry("http-403", r"\b403\b[^\n]{0,20}Forbidden|(?:HTTP|status|error)[^\n]{0,20}\b403\b",
          "The download server refused the request (403): a proxy or a rate limit is in the way; wait a few minutes, then run it again.",
          "ap install"),
    Entry("http-404", r"\b404\b[^\n]{0,20}Not Found|(?:HTTP|status|error)[^\n]{0,20}\b404\b",
          "The download address does not exist (404): the version or tag name is wrong.",
          "ap install   # the newest release; or AUTOPILOT_REF=v0.4.0 for a fixed one"),
    Entry("no-space", r"No space left on device|ENOSPC|not enough space on the disk",
          "The disk is full: free some space, then run the step again.",
          {"linux": "df -h ~", "darwin": "df -h ~", "windows": "Get-PSDrive C"}),
    Entry("permission", r"EACCES|Permission denied|Access is denied",
          "No permission to write to the install folder: install for your user only, without sudo or administrator.",
          "uv tool install dev-autopilot"),
    Entry("node-old", r"EBADENGINE|Unsupported engine|requires Node(?:\.js)? (?:version )?v?\d+|engine \"node\" is incompatible",
          "Node.js is too old for this tool (version 22 or newer): use the native installer instead of npm.",
          "ap setup   # the native install command comes first"),
    Entry("store-python", r"Python was not found; run without arguments to install from the Microsoft Store|Microsoft Store",
          "Windows has only the Store shortcut for Python, not Python itself.", "uv python install 3.12", ("windows",)),
    Entry("execution-policy", r"running scripts is disabled on this system|UnauthorizedAccess|execution policy",
          "PowerShell may not run scripts on this PC: start it with the Bypass option.",
          "powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1", ("windows",)),
    Entry("not-on-path", r"command not found|is not recognized as (?:an internal|the name)",
          "The program is installed, but its folder is not on PATH in this terminal yet: add it, or open a new terminal.", LOCAL_BIN),
    *_runner_entries(),
    Entry("logged-out", LOGGED_OUT.pattern,
          "The runner is not logged in: log in once, then start again.", "ap setup   # it prints the login command"),
)


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
