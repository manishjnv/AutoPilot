"""Q4: errors in plain words. Every command the installer or `ap setup` runs is captured; the raw output goes to
`~/.autopilot/install.log` through `log_scrub`, never to the screen. The screen gets three lines on a failure: what
failed, one sentence, one command to run by hand (and the log path). One catalogue, one entry per known text."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, replace
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
    # Q14: a line matches by code first, vendor id second, keywords third; `rx` (an English sentence) is the last resort
    code: str = ""           # exit code, Windows hex code, curl or Node error code (`0x80092012`, `curl: (35)`, `EACCES`)
    vendor: str = ""         # vendor error id or JSON field (`authentication_error`, `"subscriptionType": "free"`)
    kw: tuple = ()           # keyword sets: a set hits when every word of it is in the text (lower case)
    needs: str = ""          # a regex that must match as well (the runner name of a per-runner line)

    def tier(self, text: str) -> str:
        """Which match fired: `code`, `vendor`, `keyword`, `sentence`, or '' for none."""
        flags = re.IGNORECASE | re.MULTILINE
        if self.needs and not re.search(self.needs, text, flags):
            return ""
        for name, rx in (("code", self.code), ("vendor", self.vendor)):
            if rx and re.search(rx, text, flags):
                return name
        low = text.lower()
        if any(all(w in low for w in words) for words in self.kw):
            return "keyword"
        return "sentence" if re.search(self.rx, text, flags) else ""

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
                         f"{r.name} is not logged in: log in once, then start again (you need {r.plan}).", r.login,
                         needs=rf"\b(?:{names})\b"))
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


_BASE: tuple[Entry, ...] = (
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
    # Q11: the probe answers (`probe_slow` and `probe_no_ready` are the marks `commands.setup` adds for a silent runner)
    Entry("model-not-found", r"model.{0,40}(?:not found|not available|does not exist|unknown)|unknown model",
          "The model name is not available on this plan or in this region: use the alias haiku, sonnet or opus.",
          "ap doctor --runner   # then set agent.model_map in .agent/project.yaml to a name that works"),
    Entry("blocked-host", r"ECONNREFUSED|ECONNRESET|CERT_HAS_EXPIRED|UNABLE_TO_VERIFY_LEAF_SIGNATURE|\b407\b[^\n]{0,20}Proxy",
          "The AI service is blocked on this network: a firewall or proxy refuses the connection.", PROXY),
    Entry("probe-timeout", r"\bprobe_slow\b",
          "The runner did not answer within 60 seconds: check the network, the plan and the login.", "ap doctor --runner"),
    Entry("probe-no-answer", r"\bprobe_no_ready\b",
          "The runner answered, but not with the word ready: run it by hand to see why.", "ap doctor --runner"),    Entry("logged-out", LOGGED_OUT.pattern,
          "The runner is not logged in: log in once, then start again.", "ap setup   # it prints the login command"),
)


# Q14: the match of each line that is not an English sentence. id -> (code, vendor id or JSON field, keyword sets).
# A hex code (`0x80092012`) is the same in every Windows language, so a German or French message still matches.
# `exit code N` is added to the text by `explain` when the caller knows the exit code.
MATCH: dict[str, tuple[str, str, tuple]] = {
    "schannel": (r"0x8009201[23]|0x80090326|CRYPT_E_NO_REVOCATION_CHECK|CRYPT_E_REVOCATION_OFFLINE|curl: \(35\)|\bexit code 35\b", "",
                 (("revocation", "check"),)),
    "no-host": (r"curl: \(6\)|\bexit code 6\b|ENOTFOUND|EAI_AGAIN|0x80072EE7|WSAHOST_NOT_FOUND", "",
                (("resolve", "host"), ("name or service", "not known"), ("no such host",))),
    "timeout": (r"curl: \(28\)|\bexit code 28\b|ETIMEDOUT|ESOCKETTIMEDOUT|0x80072EE2|0x800705B4", "",
                (("timed out",), ("timeout",))),
    "http-403": (r"curl: \(22\)[^\n]*\b403\b|\bHTTP/[\d.]+ 403\b", r"\"status(?:Code)?\"\s*:\s*403|\b(?:forbidden|rate_limit_exceeded)\b",
                 (("403", "forbidden"),)),
    "http-404": (r"curl: \(22\)[^\n]*\b404\b|\bHTTP/[\d.]+ 404\b", r"\"status(?:Code)?\"\s*:\s*404|\bnot_found\b",
                 (("404", "not found"),)),
    "no-space": (r"ENOSPC|Errno 28|0x80070070|ERROR_DISK_FULL", "", (("no space", "device"), ("disk", "full"))),
    "permission": (r"EACCES|EPERM|Errno 13|0x80070005", "", (("permission", "denied"), ("access", "denied"))),
    "node-old": (r"EBADENGINE", "", (("unsupported", "engine"), ("requires", "node"))),
    "store-python": (r"\bexit code 9009\b", "", (("microsoft store",),)),
    "execution-policy": (r"PSSecurityException|UnauthorizedAccess|FullyQualifiedErrorId\s*:\s*UnauthorizedAccess", "",
                         (("running scripts", "disabled"), ("execution", "policy"))),
    "not-on-path": (r"CommandNotFoundException|ENOENT", "", (("command not found",), ("not recognized",))),
    "no-plan-claude": ("", r'subscriptionType"?\s*:\s*"?free|\bplan_required\b', (("free", "claude", "plan"),)),
    "no-plan-copilot": ("", r"copilot_access_denied|no_copilot_seat|copilot_not_enabled",
                        (("copilot", "no active"), ("copilot", "no subscription"), ("copilot", "access"), ("copilot", "license"),
                         ("copilot", "subscription", "required"), ("copilot", "plan", "required"))),
    "premium-requests-copilot": ("", r"premium_requests?_(?:limit|quota|exceeded|exhausted)",
                                 (("premium request", "limit"), ("premium request", "quota"), ("premium request", "exhausted"),
                                  ("premium request", "exceeded"), ("premium request", "used up"))),
    "model-not-found": (r"model_not_found|invalid_model|unknown_model", "", (("model", "not found"), ("model", "not available"), ("unknown", "model"))),
    "blocked-host": (r"ECONNREFUSED|ECONNRESET|CERT_HAS_EXPIRED|UNABLE_TO_VERIFY_LEAF_SIGNATURE|0x80072EFD", "", (("connection", "refused"), ("blocked by", "firewall"))),
    "probe-timeout": ("", r"\bprobe_slow\b", ()),
    "probe-no-answer": ("", r"\bprobe_no_ready\b", ()),
    "logged-out": (r"\bexit code 401\b|\bHTTP/[\d.]+ 401\b", r"authentication_error|unauthenticated|\"loggedIn\"\s*:\s*false|invalid_grant",
                   (("not logged in",), ("not signed in",), ("not authenticated",), ("no active session",), ("please log in",),
                    ("please sign in",), ("logged out",), ("no credentials",))),
}
_LOGGED_OUT_KW = MATCH["logged-out"]


def _with_match(e: Entry) -> Entry:
    if e.id.startswith("logged-out-"):
        code, vendor, kw = _LOGGED_OUT_KW
        return replace(e, code=code, vendor=vendor, kw=kw)
    code, vendor, kw = MATCH.get(e.id, ("", "", ()))
    return replace(e, code=code, vendor=vendor, kw=kw)


CATALOGUE: tuple[Entry, ...] = tuple(_with_match(e) for e in _BASE)


def match(text: str, platform: str | None = None, rc: int | None = None) -> tuple[Entry | None, str]:
    """(entry, tier) of the first catalogue line that fits; tier is code, vendor, keyword or sentence."""
    o = os_name(platform)
    raw = (text or "") + (f"\nexit code {rc}" if rc else "")
    for e in CATALOGUE:
        if e.os and o not in e.os:
            continue
        tier = e.tier(raw)
        if tier:
            return e, tier
    return None, ""


def explain(text: str, platform: str | None = None, rc: int | None = None) -> tuple[str, str, str]:
    """(entry id or '', sentence, fix command) for a raw output. Unknown text: ('', GENERIC, '')."""
    e, _ = match(text, platform, rc)
    return (e.id, e.sentence, e.fix_for(platform)) if e else ("", GENERIC, "")

def three_lines(step: str, text: str, log: Path, platform: str | None = None, cmd: str = "", rc: int | None = None) -> list[str]:
    """What the screen shows on a failure: what failed, the sentence, the command (and the log path)."""
    _, sentence, fix = explain(text, platform, rc)
    return [f"FAILED  {step}", f"        {sentence}",
            f"        Run by hand: {fix or cmd or '(see the log)'}  -- details: {log}"]


DROPPED = re.compile(r"curl: \((?:7|18|28|52|55|56)\)|ECONNRESET|ETIMEDOUT|ESOCKETTIMEDOUT|connection (?:was )?(?:reset|closed|dropped)|"
                     r"0x80072EFE|0x80072EE2|early EOF|unexpected disconnect", re.IGNORECASE)
RETRY_WAIT = 5      # Q12: seconds of backoff before the one retry on a dropped connection
HEARTBEAT = 10      # Q12: one dot every this many seconds while a silent installer runs


def _beat(say, every: float, done):
    """The heartbeat of a silent installer: one line, then one dot every `every` seconds until `done` is set. The dots go
    to the terminal itself (not through `say`, which is one line per call); a test reads the line through `say`."""
    say("downloading, up to 2 minutes")
    while not done.wait(every):
        sys.stdout.write(".")
        sys.stdout.flush()


def capture(step: str, cmd, *, shell: bool = False, env: dict | None = None, timeout: float = 900, run=run_proc,
            say=print, platform: str | None = None, home: Path | None = None, cwd=None, retry: bool = False,
            sleep=None, heartbeat: float = 0) -> int:
    """Run one install step. Output goes to the log only; on a failure the three lines go to the screen. Returns the
    exit code (127 when the program cannot start). Q12: `retry=True` runs it once more after RETRY_WAIT seconds when the
    first run died on a dropped connection (before the error line); `heartbeat` > 0 prints a line and a dot every that
    many seconds while the step is silent."""
    import threading
    import time
    sleep = sleep or time.sleep
    shown = cmd if isinstance(cmd, str) else " ".join(cmd)
    for attempt in (1, 2):
        done = threading.Event()
        if heartbeat:
            threading.Thread(target=_beat, args=(say, heartbeat, done), daemon=True).start()
        try:
            p = run(cmd, shell=shell, env=env, timeout=timeout, cwd=cwd)
            rc, text = p.rc, (p.stdout or "") + (p.stderr or "")
        except OSError as exc:
            rc, text = 127, str(exc)
        finally:
            done.set()
        if rc != 0 and retry and attempt == 1 and (DROPPED.search(text) or rc in (7, 18, 28, 52, 55, 56)):
            log_raw(step, shown, rc, text, env, home)
            say(f"The connection dropped. One more try in {RETRY_WAIT} seconds.")
            sleep(RETRY_WAIT)
            continue
        break
    log = log_raw(step, shown, rc, text, env, home)
    if rc != 0:
        for line in three_lines(step, text, log, platform, shown, rc):
            say(line)
    return rc


# Q6: the environment pre-check lines of `ap setup` (one sentence each; the fix is a command or '' when there is none)
PRECHECK: dict[str, tuple[str, dict | str]] = {
    "local-bin": ("Programs install into ~/.local/bin, which is not on PATH.", LOCAL_BIN),
    "proxy": ("A proxy is set; downloads and logins go through it.", ""),
    "corporate-ca": ("The certificate chain failed: a company proxy signs connections with its own CA. Point SSL_CERT_FILE and REQUESTS_CA_BUNDLE at that CA file.",
                     {"linux": "export SSL_CERT_FILE=/path/to/company-ca.pem REQUESTS_CA_BUNDLE=/path/to/company-ca.pem",
                      "darwin": "export SSL_CERT_FILE=/path/to/company-ca.pem REQUESTS_CA_BUNDLE=/path/to/company-ca.pem",
                      "windows": "$env:SSL_CERT_FILE = 'C:\\path\\company-ca.pem'; $env:REQUESTS_CA_BUNDLE = $env:SSL_CERT_FILE"}),
    "offline": ("No download server is reachable: connect to the network, then run `ap setup` again.", "ap setup"),
    "win32-bit": ("This is 32-bit Windows: uv and the AI CLIs ship 64-bit builds only.", ""),
    "arm": ("This is an ARM machine: the installers pick the ARM build; a tool without one needs the x64 build through emulation.", ""),
    "home-path": ("The home folder has a space or a non-ASCII character: some installers fail on it.", ""),
    "home-cloud": ("The home folder is on OneDrive or a network share: installs there are slow and may sync half-written files.", ""),
    "home-readonly": ("The home folder is not writable: nothing can install for this user.", {"linux": "ls -ld ~", "darwin": "ls -ld ~", "windows": "icacls $env:USERPROFILE"}),
    "root": ("You run as root or through sudo: the install lands in the wrong home. Run the installer as your own user.", ""),
    "python-shim": ("A conda or pyenv shim comes before the real Python: uv installs its own Python, so this is only a note.", ""),
    "uv-old": ("uv is older than one year: update it.", "uv self update"),
    "two-autopilots": ("Autopilot is installed twice, with pip and as a uv tool: remove the pip one.", {"linux": "python3 -m pip uninstall dev-autopilot", "darwin": "python3 -m pip uninstall dev-autopilot", "windows": "python -m pip uninstall dev-autopilot"}),
    "wsl1": ("This is WSL 1: the Linux installers need WSL 2.", "wsl --set-version Ubuntu 2   # in PowerShell"),
    "wsl-mnt": ("The project is under /mnt: a WSL run on a Windows drive is slow. Keep projects under the Linux home.", ""),
    "windows-binary-in-wsl": ("A Windows copy of a runner is visible from WSL; it is skipped. Install the Linux one inside WSL.", ""),
    "two-copies": ("Two copies of one CLI are on PATH: the first one runs; remove the other.", ""),
    "token-overrides-login": ("A token variable is set and wins over the stored login of that runner.", ""),
    "git-identity": ("git has no user.name or user.email: commits need both.",
                     'git config --global user.name "Your Name"; git config --global user.email "you@example.com"'),
    "long-paths": ("Windows long paths are off: deep node_modules folders fail.",
                   "New-ItemProperty -Path HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem -Name LongPathsEnabled -Value 1 -PropertyType DWord -Force   # as administrator"),
    "leftover": ("A folder of an AI CLI is left over, with no program: it is a note, nothing installs because of it.", ""),
    # Q21: eight more lines (found / fixed / skipped, one sentence each)
    "git-dubious": ("git does not trust this folder (dubious ownership): the folder is now on the safe list.", "git config --global --add safe.directory <folder>"),
    "autocrlf": ("git converts line endings on this Windows PC: it is off for this project, and .gitattributes keeps the endings steady.", "git config core.autocrlf false"),
    "api-key": ("An API key is set in the environment and may bill per use instead of your subscription: unset it in this terminal to avoid that.",
                {"linux": "unset ANTHROPIC_API_KEY OPENAI_API_KEY CODEX_API_KEY", "darwin": "unset ANTHROPIC_API_KEY OPENAI_API_KEY CODEX_API_KEY",
                 "windows": "Remove-Item Env:ANTHROPIC_API_KEY, Env:OPENAI_API_KEY, Env:CODEX_API_KEY -ErrorAction SilentlyContinue"}),
    "clock-skew": ("The clock of this PC is more than 3 minutes off: logins and certificates fail until it is right.",
                   {"linux": "sudo hwclock -s", "darwin": "sudo sntp -sS time.apple.com", "windows": "w32tm /resync"}),
    "low-disk": ("Less than 1 GB of disk is free: free some space before anything downloads.",
                 {"linux": "df -h ~", "darwin": "df -h ~", "windows": "Get-PSDrive C"}),
    "git-old": ("git is older than 2.30: worktrees need a newer one.",
                {"linux": "sudo apt install git   # or your package manager", "darwin": "brew install git", "windows": "winget install Git.Git"}),
    "console-encoding": ("This console is not UTF-8: some characters print wrong.",
                         {"linux": "", "darwin": "", "windows": "chcp 65001   # or set PYTHONIOENCODING=utf-8"}),
    "port-busy": ("The status page port is in use: the next free port is used instead.", ""),
}
