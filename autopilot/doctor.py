"""`autopilot doctor`: check this machine and project before a run, and fix what can be fixed without a person.
Checks are read-only and never start an agent session; fixes run only through `autofix()`."""
from __future__ import annotations

import os
import re
import shutil
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, allowlist_on, sandbox_mode
from .proc import WINDOWS, run_proc

OK, WARN, FAIL = "ok", "WARN", "FAIL"
STATUS_WORD = {OK: "done", WARN: "not done", FAIL: "FAIL", "fix": "fixed"}  # Q17: the words `ap setup` uses


def row(level: str, item: str, detail: str = "", command: str = "") -> dict:
    return {"status": STATUS_WORD.get(level, level), "item": item, "detail": detail, "command": command}


def tuples_to_rows(rows) -> list[dict]:
    return [row(level, name, detail) for level, name, detail in rows]


def emit(rows: list[dict], as_json: bool = False, say=print) -> int:
    """Q17: one printer for all `ap doctor` modes, in the `ap setup` layout (status in a 10-column field). A FAIL or
    `not done` row puts its sentence and command on the next indented line. Returns 1 when a row is FAIL, else 0."""
    for r in rows:
        if as_json:
            import json
            say(json.dumps(r))
        elif r["status"] in ("FAIL", "not done") and (r["detail"] or r["command"]):
            say(f"{r['status']:<10}{r['item']}")
            say("          " + " ".join(x for x in (r["detail"], r["command"]) if x))
        else:
            say(f"{r['status']:<10}{r['item']:<14} {r['detail']}".rstrip())
    return int(any(r["status"] == "FAIL" for r in rows))
NOTIFY_ENVS = ("telegram_token_env", "slack_webhook_env", "webhook_env", "ntfy_topic_env")


def _run(cmd: list[str], cwd=None, timeout: float = 30, env=None) -> tuple[int, str]:
    try:
        p = run_proc(cmd, cwd=cwd, timeout=timeout, env=env)
    except OSError as exc:
        return 127, str(exc)
    return p.rc, (p.stdout + p.stderr).strip()


def _env(name: str) -> str:
    return os.environ.get(name) or (os.environ.get("AUTODEV_" + name[10:], "") if name.startswith("AUTOPILOT_") else "")


LOGIN_FIX = "run `claude auth login`, then start again. A paid Claude plan or an API key is necessary"
OTHER_AUTH = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
              "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")


def other_auth(cfg) -> str:
    """H2: what pays for sessions when there is no Claude login: an API key, a gateway, or usage.billing: api.
    Only the name is returned, never a value."""
    name = next((n for n in OTHER_AUTH if os.environ.get(n)), "")
    return name or ("usage.billing: api" if cfg is not None and cfg.get("usage.billing") == "api" else "")


def check_login(binary: str, version: tuple, cfg, timeout: float = 30, env=None) -> tuple[str, str, str]:
    """H2: FAIL only when a login is surely missing: a CLI that has `auth status`, and no other way to pay."""
    rc, out = _run([binary, "auth", "status"], timeout=timeout, env=env)  # documented from 2.1.268: exit 0 = logged in
    other = other_auth(cfg)
    if rc == 0:
        # only the sure case: a claude.ai login (not a key, not a gateway) on the free plan, and no other way to pay
        if all(re.search(rf'"{k}"\s*:\s*"{v}"', out, re.I) for k, v in (("subscriptionType", "free"),
                                                                        ("authMethod", r"claude\.ai"))) and not other:
            return FAIL, "claude login", "the free Claude plan cannot use Claude Code: get a paid plan, or set an API key"
        return OK, "claude login", "logged in"
    if version < (2, 1, 268):
        return WARN, "claude login", "cannot check: this CLI is older than 2.1.268. If sessions fail, run `claude` and /login"
    if other:
        return WARN, "claude login", f"not logged in; sessions use {other}"
    return FAIL, "claude login", f"not logged in: {LOGIN_FIX}"


# Q1: the one runner table. Every runner fact (binary, aliases, preset, install command per OS, login command,
# read-only status argv, token variables, plan) lives here; `pick_runner`, `check_runner_login`, `detect_runner`,
# `ap doctor`, `ap setup`, the N11 fallback, the template comment and REFERENCE read it (a test checks the copies).
# Rows: subscription runners only (owner rule 2026-10-11). Install commands and flags: docs checked 2026-10-12, not
# run live. A token variable counts first (presence only, never the value): no process to start. Never `login` here.
LOGIN_TIMEOUT = 20  # N10
DOCS_CHECKED = "2026-10-12"  # Q16: the day the install commands and flags of RUNNERS were last checked against the vendor docs


def runners_json() -> str:
    """Q16: the runner table as JSON for the release asset `runners.json` (signed with the release, X9). Rows are the
    `Runner` fields as plain lists, dicts and strings, plus `docs_checked` and the Autopilot version. A later `ap doctor`
    may read a newer file from the latest release; the built-in rows stay the offline fallback."""
    import json
    from dataclasses import asdict

    from . import __version__
    rows = [asdict(r) for r in RUNNERS]
    return json.dumps({"version": __version__, "docs_checked": DOCS_CHECKED, "runners": rows}, indent=1, sort_keys=True) + "\n"
VSCODE_SENTENCE = ("Copilot in VS Code is not a command-line tool. Autopilot needs the Copilot CLI, which uses the "
                   "same subscription.")


@dataclass(frozen=True)
class Runner:
    key: str                 # the `agent.preset` value, or `claude_cli`
    binary: str              # the program on PATH
    aliases: tuple           # older names of the same program
    install: dict            # os (`linux`, `darwin`, `windows`) -> the native install command (a link when there is none)
    login: str               # the one interactive login command; Autopilot prints it, never runs it (N10)
    status: tuple | None     # read-only status argv; `status[0]` may name another program (`gh`); None = token or claude
    tokens: tuple            # token variables that count as a login (presence only)
    plan: str                # what the user pays for
    footprints: tuple = ()   # folders that suggest the runner (Q3); a footprint never installs by itself
    npm: str = ""            # the npm route, after the native one (Node is a project dependency, not Autopilot's)
    probe: tuple = ()        # Q11: argv after the binary that sends `{prompt}` once and prints one answer (docs checked 2026-10-12)
    login_headless: str = ""  # Q13: the login form that prints an address and a code (device flow); flags from the roadmap text of 2026-10-12, NOT checked against vendor docs, not run live (NEEDS-YOU)
    uninstall: dict = field(default_factory=dict)  # Q12: install method -> the undo command; written from the install routes, NOT checked against vendor docs, not run live (NEEDS-YOU)

    @property
    def preset(self) -> str:
        return "" if self.key == "claude_cli" else self.key

    @property
    def name(self) -> str:
        """The plain name a user reads: `claude`, `copilot`, `codex`, `cursor`, `kiro`."""
        return "claude" if self.key == "claude_cli" else self.key

    @property
    def names(self) -> tuple:
        return (self.binary, *self.aliases)

    def install_cmd(self, platform: str | None = None) -> str:
        p = platform or sys.platform
        os_ = "windows" if p.startswith("win") else "darwin" if p == "darwin" else "linux"
        return self.install[os_]

    def which(self, path: str | None = None) -> str | None:
        """The program's path, under its current name or an alias; None when it is not on PATH."""
        for n in self.names:
            exe = shutil.which(n, path=path) if path is not None else shutil.which(n)
            if exe:
                return exe
        return None


_CLAUDE_SH = "curl -fsSL https://claude.ai/install.sh | bash"
RUNNERS = (
    Runner("claude_cli", "claude", (), {"linux": _CLAUDE_SH, "darwin": _CLAUDE_SH,
                                        "windows": "irm https://claude.ai/install.ps1 | iex"},
           "claude auth login", None, OTHER_AUTH, "a paid Claude plan (Pro or Max)", (".claude", ".claude.json"),
           npm="npm i -g @anthropic-ai/claude-code", probe=("-p", "{prompt}"), login_headless="claude auth login",
           uninstall={"native-posix": "rm -f ~/.local/bin/claude && rm -rf ~/.local/share/claude",
                      "native-windows": r"Remove-Item -Force $env:USERPROFILE\.local\bin\claude.exe; Remove-Item -Recurse -Force $env:USERPROFILE\.local\share\claude",
                      "npm": "npm uninstall -g @anthropic-ai/claude-code", "brew": "brew uninstall --cask claude-code", "winget": "winget uninstall Anthropic.ClaudeCode"}),
    # copilot: docs checked 2026-10-12, not run live. Status through `gh` (no prompt-free copilot status command).
    Runner("copilot", "copilot", (), {"linux": "curl -fsSL https://gh.io/copilot-install | bash",
                                      "darwin": "brew install --cask copilot-cli",
                                      "windows": "winget install GitHub.Copilot"},
           "copilot login", ("gh", "auth", "status"), ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
           "a paid GitHub Copilot plan", (".copilot",), npm="npm i -g @github/copilot",
           probe=("-p", "{prompt}", "--allow-all-tools", "--no-ask-user", "-s"), login_headless="copilot login --device-code",
           uninstall={"native-posix": "rm -f ~/.local/bin/copilot", "npm": "npm uninstall -g @github/copilot", "brew": "brew uninstall --cask copilot-cli", "winget": "winget uninstall GitHub.Copilot"}),
    Runner("codex", "codex", (), {"linux": "npm i -g @openai/codex", "darwin": "npm i -g @openai/codex",
                                  "windows": "npm i -g @openai/codex"},
           "codex login", ("login", "status"), ("CODEX_API_KEY",), "a ChatGPT plan", (".codex",),
           npm="npm i -g @openai/codex", probe=("exec", "--skip-git-repo-check", "{prompt}"), login_headless="codex login --device-auth",
           uninstall={"npm": "npm uninstall -g @openai/codex", "native-posix": "npm uninstall -g @openai/codex", "native-windows": "npm uninstall -g @openai/codex"}),
    # cursor renamed the binary from cursor-agent to agent (docs checked 2026-10-12)
    Runner("cursor", "agent", ("cursor-agent",), {"linux": "curl https://cursor.com/install -fsS | bash",
                                                  "darwin": "curl https://cursor.com/install -fsS | bash",
                                                  "windows": "irm 'https://cursor.com/install?win32=true' | iex"},
           "agent login", ("status",), ("CURSOR_API_KEY",), "a Cursor plan", (".cursor",),
           probe=("-p", "--trust", "{prompt}"), login_headless="agent login",
           uninstall={"native-posix": "rm -f ~/.local/bin/agent ~/.local/bin/cursor-agent", "native-windows": r"Remove-Item -Force $env:USERPROFILE\.local\bin\agent.exe"}),
    # kiro ships a download page on Windows, no script: the row prints the link
    Runner("kiro", "kiro-cli", (), {"linux": "curl -fsSL https://cli.kiro.dev/install | bash",
                                    "darwin": "curl -fsSL https://cli.kiro.dev/install | bash",
                                    "windows": "https://kiro.dev/downloads/ (download page, no script)"},
           "kiro-cli login", ("whoami",), ("KIRO_API_KEY",), "a Kiro plan or an AWS Builder ID", (".kiro",),
           probe=("chat", "--no-interactive", "{prompt}"), login_headless="kiro-cli login",
           uninstall={"native-posix": "rm -f ~/.local/bin/kiro-cli"}),
)
# exit codes of the status commands are not documented: a logged-out CLI may still exit 0
LOGGED_OUT = re.compile(r"not (logged|signed) in|not authenticated|unauthenticated|logged out|no (active )?"
                        r"(session|credentials)|please (log|sign) ?in", re.I)
# N10: owner rule 2026-10-11, subscription login only. Derived from the table: never a second copy.
LOGIN_CMD = {r.key: r.login for r in RUNNERS}
NO_SUBSCRIPTION = ("gemini", "aider", "opencode", "amp", "qwen", "goose")  # API key only: not supported


def runner(key: str) -> Runner | None:
    """The row of a preset name or `claude_cli` (`claude` is accepted too); None when there is none."""
    return next((r for r in RUNNERS if r.key == key or r.binary == key), None)


def runner_lines(platform: str | None = None) -> list[str]:
    """One line per runner with its install command for this OS, for the neutral runner-missing message (Q1)."""
    return [f"{r.name:<8} {r.install_cmd(platform)}" for r in RUNNERS]


def no_runner_text(platform: str | None = None) -> str:
    """The runner-missing message: neutral, one line per runner, then the VS Code sentence. Never 'Install Claude Code'."""
    return ("no agent CLI found. Install the one you pay for, or run `ap setup` (it asks once):\n"
            + "".join(f"      {line}\n" for line in runner_lines(platform)) + f"      {VSCODE_SENTENCE}")


def runner_chosen(root) -> bool:
    """N3: does the project's own project.yaml choose the agent CLI? Read raw: Config merges the claude_cli default.
    An unusual `agent:` value (not a mapping) counts as chosen, so the file is left alone."""
    import yaml

    from . import AGENT_DIR
    path = Path(root) / AGENT_DIR / "project.yaml"
    try:
        agent = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}) or {}
        agent = agent.get("agent") or {}
    except (yaml.YAMLError, AttributeError, OSError):
        return True  # a file preflight cannot read is never edited; validate reports it
    return not isinstance(agent, dict) or any(agent.get(k) for k in ("backend", "command", "preset"))


def check_endpoint(cfg, timeout=2) -> tuple[str, str, str]:
    """P12-T02 (W13): does the openai_compat endpoint answer? A GET to <base_url>/models; any HTTP answer counts.
    WARN only, because a local model is optional. Never raises."""
    from .backends.openai_compat import DEFAULT_BASE_URL
    base = str(cfg.get("agent.base_url") or DEFAULT_BASE_URL).rstrip("/")
    import urllib.error, urllib.parse, urllib.request  # W47: slow import, only this check needs it
    try:
        host = urllib.parse.urlsplit(base).hostname or ""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if host in ("127.0.0.1", "localhost", "::1")             else urllib.request.build_opener()  # a local runner never goes through an env proxy
        try:
            with opener.open(urllib.request.Request(base + "/models"), timeout=timeout):
                pass
        except urllib.error.HTTPError:
            pass  # the server answered (for example 404 on /models): it is up
        return OK, "endpoint", f"{base} answers"
    except Exception:  # noqa: BLE001 - a doctor row never raises
        return WARN, "endpoint", f"{base} does not answer (start Ollama or LM Studio)"


def check_runner_login(cfg, env=None) -> tuple[str, str, str]:
    """N10: the configured runner (a `command` preset) is logged in with its own subscription; stdin closed, CI=1,
    LOGIN_TIMEOUT. FAIL names the one login command. No credential file is read, written or copied."""
    if cfg.get("agent.backend") == "openai_compat":  # P12-T02: a local model is never a login, WARN at most
        return check_endpoint(cfg)
    preset = str(cfg.get("agent.preset") or "")
    if cfg.get("agent.command") or not preset:
        return OK, "runner login", "custom command: not checked"
    if preset in NO_SUBSCRIPTION:
        return (WARN, "runner login",
                f"`{preset}` needs an API key, not supported (subscription runners: {', '.join(LOGIN_CMD)})")
    row = runner(preset)
    if row is None:
        return WARN, "runner login", f"no login check for preset `{preset}`"
    env = dict(os.environ if env is None else env)
    path = next((v for k, v in env.items() if k.upper() == "PATH"), None)
    exe = row.which(path)
    if not exe:
        return FAIL, "runner login", f"`{row.binary}` is not on PATH"
    if _logged_in(exe, row, env):
        return OK, "runner login", f"{row.binary} logged in"
    return FAIL, "runner login", f"{row.binary} is not logged in: run `{row.login}`, then start again"


def _logged_in(path: str, row: Runner, env: dict) -> bool:
    """N3: True when a token variable is set (only its presence is read), or the status command exits 0 within
    LOGIN_TIMEOUT without logged-out wording. A timeout or a program that does not start counts as logged out.
    A status argv that names another program (`gh auth status` for copilot) needs that program on PATH."""
    if any(env.get(k) for k in row.tokens):
        return True
    if row.key == "claude_cli":
        return check_login(path, (0, 0, 0), None, timeout=LOGIN_TIMEOUT)[0] == OK
    if not row.status:
        return False
    argv = [path, *row.status]
    if row.status[0] == "gh":  # copilot: the status lives in another program
        gh = shutil.which("gh", path=next((v for k, v in env.items() if k.upper() == "PATH"), None))
        if not gh:
            return False
        argv = [gh, *row.status[1:]]
    try:
        p = run_proc(argv, env={**env, "CI": "1"}, timeout=LOGIN_TIMEOUT)  # N10: no prompt, no browser
    except OSError:
        return False
    return p.rc == 0 and not p.timed_out and not LOGGED_OUT.search(p.stdout + p.stderr)


def _iter_runners(env=None):
    """(row, path, logged_in) for each table runner on PATH, in table order, one at a time (a status command runs
    only when the caller gets that far). Read-only: never starts a login."""
    env = dict(os.environ if env is None else env)
    path = next((v for k, v in env.items() if k.upper() == "PATH"), "")
    for row in RUNNERS:
        exe = row.which(path) if path else None
        if exe:
            yield row, exe, _logged_in(exe, row, env)


def installed_runners(env=None) -> list[tuple[Runner, str, bool]]:
    """Q3: every table runner on PATH as (row, path, logged_in), in table order."""
    return list(_iter_runners(env))


def detect_runner(env=None) -> str | None:
    """N3: the backend choice (`claude_cli`, or a preset name) of the first agent CLI on PATH that is installed and
    logged in, in RUNNERS order; None when there is none. Stops at the first hit: the later CLIs are never asked."""
    return next((row.key for row, _, ok in _iter_runners(env) if ok), None)


def config_folders(cfg) -> list[str]:
    """W28: the Claude config folders named in `agent.fallback` or `agent.env`, once each, in that order."""
    from .handoff import entry_folder
    fb = cfg.get("agent.fallback") if cfg is not None else None
    found = [(cfg.get("agent.env") or {}).get("CLAUDE_CONFIG_DIR")] if cfg is not None else []
    found += [entry_folder(e) for e in (fb if isinstance(fb, list) else [fb])]
    return list(dict.fromkeys(str(f) for f in found if f))


def check_claude(cfg=None) -> list[tuple[str, str, str]]:
    from .backends.claude_cli import ClaudeCLIBackend
    binary = ClaudeCLIBackend.resolve_binary()
    rc, out = _run([binary, "--version"])
    first = out.splitlines()[0] if out else ""
    # a broken install can still print a version, just not Claude Code's (seen: "Bun 1.4.3")
    if not (rc == 0 and "claude code" in out.lower() and re.search(r"\d+\.\d+\.\d+", out)):
        return [(FAIL, "claude CLI", f"`{binary} --version` gave rc {rc}: {first[:120] or 'no output'}. Reinstall "
                 f"with `{INSTALL[claude_route(binary)][1]}`, or set AUTOPILOT_CLAUDE_BIN to the real binary")]
    version = tuple(int(x) for x in re.search(r"(\d+)\.(\d+)\.(\d+)", out).groups())
    rows = [(OK, "claude CLI", f"{first} ({binary})"), check_login(binary, version, cfg)]
    for folder in config_folders(cfg):  # W28: one login row for each other Claude config folder
        level, _, detail = check_login(binary, version, cfg, env={**os.environ, "CLAUDE_CONFIG_DIR": folder})
        rows.append((level, f"claude login ({folder})", detail))
    return rows


def scripts_dir() -> Path | None:
    """The folder pip put the `autopilot` command in: the interpreter's, or the per-user one (`pip install --user`,
    or a system Python whose folder isn't writable)."""
    for scheme in (None, sysconfig.get_preferred_scheme("user")):
        try:
            d = Path(sysconfig.get_path("scripts", scheme) if scheme else sysconfig.get_path("scripts"))
        except KeyError:
            continue
        if (d / "autopilot.exe").is_file() or (d / "autopilot").is_file():
            return d
    return None


def check_path() -> tuple[str, str, str]:
    if shutil.which("autopilot"):
        return OK, "autopilot cmd", "on PATH"
    d = scripts_dir()
    return WARN, "autopilot cmd", (f"installed in {d}, which is not on PATH" if d else "not installed as a command") \
        + "; `python -m autopilot` works meanwhile"


# ---------- fixes: only what is safe without a person; logins, sudo and paid accounts stay with the owner ----------
_NATIVE = "irm https://claude.ai/install.ps1 | iex" if WINDOWS else "curl -fsSL https://claude.ai/install.sh | bash"
# H3: how Claude Code was installed -> (the repair command, the same command as the owner types it)
INSTALL = {
    "npm": (["npm", "i", "-g", "@anthropic-ai/claude-code"], "npm i -g @anthropic-ai/claude-code"),
    "winget": (None, "winget upgrade Anthropic.ClaudeCode"),  # winget installs do not update themselves
    "native": ((["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _NATIVE] if WINDOWS
                else ["bash", "-c", _NATIVE]), _NATIVE),
}


def claude_route(binary: str) -> str:
    """H3: npm, winget or native, from where the program is. A missing program is native: no Node.js is needed."""
    p = os.path.realpath(binary).replace("\\", "/").lower() if os.path.exists(binary) else ""
    if "/node_modules/" in p or p.endswith((".cmd", ".bat")):
        return "npm" if shutil.which("npm") else "native"
    return "winget" if "/winget/" in p else "native"


def fix_claude() -> str:
    """Reinstall Claude Code the way it was installed. The native route downloads the installer from claude.ai and
    runs it, so the command is shown before it starts. `autofix` does not call this under AUTOPILOT_NO_AUTOFIX=1."""
    from .backends.claude_cli import ClaudeCLIBackend
    route = claude_route(ClaudeCLIBackend.resolve_binary())
    cmd, shown = INSTALL[route]
    if not cmd:
        return f"cannot fix: Claude Code came from winget, which does not update it. Run `{shown}`"
    from .install_errors import capture  # Q4: raw output to the log, one sentence on screen
    print(f"fix   claude CLI: running `{shown}` (this downloads and installs Claude Code)", flush=True)
    lines: list[str] = []
    rc = capture("reinstall claude", [shutil.which(cmd[0]) or cmd[0]] + cmd[1:], say=lines.append, run=run_proc)
    return f"reinstalled ({route})" if rc == 0 else f"install failed: {lines[1].strip()} Run `{shown}` yourself"


def write_launcher() -> str:
    """A one-line `autopilot` launcher in a user folder that is already on PATH, so the command works at once in every
    terminal, including ones VS Code opened before a PATH change. Only well-known per-user folders, never an
    arbitrary PATH entry. Returns where it was written, or ''."""
    if WINDOWS:
        prefer = [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps",
                  Path.home() / ".local" / "bin", Path(os.environ.get("APPDATA", "")) / "npm"]  # uv, Claude Code, npm
        name, body = "autopilot.cmd", f'@"{sys.executable}" -m autopilot %*\r\n'
    else:
        prefer = [Path.home() / ".local" / "bin", Path.home() / "bin"]
        name, body = "autopilot", f'#!/bin/sh\nexec "{sys.executable}" -m autopilot "$@"\n'

    def norm(p) -> str:
        return os.path.normcase(str(p)).rstrip("\\/")
    on_path = {norm(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p}
    for d in prefer:
        if str(d) not in ("", ".") and norm(d) in on_path and d.is_dir() and os.access(d, os.W_OK):
            (d / name).write_text(body, encoding="utf-8")
            if not WINDOWS:
                (d / name).chmod(0o755)
            return str(d / name)
    return ""


def fix_path() -> str:
    launcher = write_launcher()
    now = f"; `autopilot` works now in every terminal via {launcher}" if launcher else ""
    d = scripts_dir()
    if not d:
        return (f"wrote a launcher{now}" if launcher else
                "cannot fix: the autopilot command is not installed (`python -m pip install -e <autopilot repo>`)")
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(d)
    if WINDOWS:
        _add_user_path_windows(d)
        later = ". Open terminals keep their old PATH (VS Code: restart it); until then use `python -m autopilot`"
        return f"added {d} to your user PATH{now or later}"
    profile, line = Path.home() / ".profile", f'export PATH="$PATH:{d}"'
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if line not in text:
        profile.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n", encoding="utf-8")
    return f"added {d} to PATH in {profile}{now or ' (new login shells)'}"


def _add_user_path_windows(d: Path):
    """HKCU\\Environment Path, appended in place (not setx, which truncates at 1024 characters)."""
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            cur, kind = winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            cur, kind = "", winreg.REG_EXPAND_SZ
        parts = [p for p in str(cur).split(";") if p]
        if str(d).rstrip("\\").lower() not in {p.rstrip("\\").lower() for p in parts}:
            winreg.SetValueEx(k, "Path", 0, kind, ";".join(parts + [str(d)]))
    # tell running programs (Explorer, new terminals) that the environment changed
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x2, 5000, None)


FIXES = {"claude CLI": fix_claude, "autopilot cmd": fix_path}


def autofix(rows: list[tuple[str, str, str]]) -> list[str]:
    """Apply the fix for each failed or warned check that has one; returns what was done. AUTOPILOT_NO_AUTOFIX=1
    turns this off (the test suite sets it: a test must never reinstall software or edit PATH)."""
    if os.environ.get("AUTOPILOT_NO_AUTOFIX"):
        return []
    return [f"{name}: {FIXES[name]()}" for level, name, _ in rows if level != OK and name in FIXES]


def _config_load_line(cfg: Config) -> str:
    """I1: what the last session loaded from the Claude config; read-only, '' when there is no state.db or no figure."""
    import json
    import sqlite3
    from .report import config_line
    db = cfg.agent_dir / "state.db"
    if not db.is_file():
        return ""
    try:
        con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT value FROM meta WHERE key='config_load'").fetchone()
        finally:
            con.close()
        return config_line(json.loads(row[0])) if row else ""
    except (sqlite3.Error, ValueError, TypeError):
        return ""


def check_user_guards(cfg: Config) -> tuple[str, str, str] | None:
    """I2: sessions skip ~/.claude/settings.json (`agent.user_config: false`), so its deny rules and tool hooks do
    not apply to them. Counts only, never a rule or a command."""
    import json
    if cfg.get("agent.user_config"):
        return None
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        s = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        deny = len((s.get("permissions") or {}).get("deny") or [])
        hooks = sum(len((s.get("hooks") or {}).get(k) or []) for k in ("PreToolUse", "PermissionRequest"))
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not (deny or hooks):
        return None
    return (WARN, "user guards", f"your ~/.claude/settings.json has {deny} deny rule(s) and {hooks} tool hook(s); "
            "Autopilot sessions do not load them. To keep them, set agent.user_config: true")


def _venv_in(root: Path, names=(".venv",)) -> bool:
    return any((root / n / "pyvenv.cfg").is_file() or (root / n / "bin").is_dir() or (root / n / "Scripts").is_dir()
               for n in names)


def _nonempty(p: Path) -> bool:
    try:
        return p.is_dir() and any(p.iterdir())
    except OSError:
        return False


def _go_cache() -> Path:
    mc = os.environ.get("GOMODCACHE")
    if mc:
        return Path(mc)
    return Path((os.environ.get("GOPATH") or "").split(os.pathsep)[0] or Path.home() / "go") / "pkg" / "mod"


def _cargo_registry() -> Path:
    return Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo") / "registry"


def missing_deps(root) -> list[dict]:
    """N2: pure check, no install. One item {lock, command, tool} per lock or manifest file whose dependency folder
    is missing. Presence checks: node_modules/ (npm, pnpm, yarn); .venv/ or venv/ (uv, poetry; a Poetry venv outside
    the project gives a false WARN); a venv in the project or an active one (requirements); a non-empty Go module
    cache or vendor/ (go.sum); target/ or the cargo registry (Cargo.lock)."""
    root = Path(root)
    out: list[dict] = []

    def add(lock, command, tool):
        out.append({"lock": lock, "command": command, "tool": tool})

    def has(n):
        return (root / n).is_file()
    if has("package-lock.json") and not (root / "node_modules").is_dir():
        add("package-lock.json", "npm ci", "npm")
    if has("pnpm-lock.yaml") and not (root / "node_modules").is_dir():
        add("pnpm-lock.yaml", "pnpm install --frozen-lockfile", "pnpm")
    if has("yarn.lock") and not (root / "node_modules").is_dir():
        try:
            berry = "__metadata:" in (root / "yarn.lock").read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            berry = False
        add("yarn.lock", "yarn install --immutable" if berry else "yarn install --frozen-lockfile", "yarn")
    if has("uv.lock") and not _venv_in(root, (".venv", "venv")):
        add("uv.lock", "uv sync", "uv")
    if has("poetry.lock") and not _venv_in(root, (".venv", "venv")):
        add("poetry.lock", "poetry install", "poetry")
    reqs = sorted(p.name for p in root.glob("requirements*.txt") if p.is_file())
    active = bool(os.environ.get("VIRTUAL_ENV")) or sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if reqs and not active and not _venv_in(root, (".venv", "venv", "env")):
        for r in reqs:
            add(r, f"pip install -r {r}", "python")
    if has("go.sum") and not (_nonempty(_go_cache()) or (root / "vendor").is_dir()):
        add("go.sum", "go mod download", "go")
    if has("Cargo.lock") and not ((root / "target").is_dir() or _nonempty(_cargo_registry())):
        add("Cargo.lock", "cargo fetch", "cargo")
    return out


_HINTS = {  # tool -> (windows, linux, macos)
    "python": ("winget install -e --id Python.Python.3.12", "sudo apt install python3 python3-venv python3-pip",
               "brew install python"),
    "node": ("winget install -e --id OpenJS.NodeJS.LTS", "sudo apt install nodejs npm", "brew install node"),
    "git": ("winget install -e --id Git.Git", "sudo apt install git", "brew install git"),
    "go": ("winget install -e --id GoLang.Go", "sudo apt install golang-go", "brew install go"),
    "uv": ("winget install -e --id astral-sh.uv", "curl -LsSf https://astral.sh/uv/install.sh | sh",
           "brew install uv"),
    "poetry": ("pipx install poetry", "pipx install poetry", "pipx install poetry"),
    "cargo": ("winget install -e --id Rustlang.Rustup", "curl --proto =https --tlsv1.2 -sSf https://sh.rustup.rs | sh",
              "curl --proto =https --tlsv1.2 -sSf https://sh.rustup.rs | sh"),
    "pnpm": ("npm install -g pnpm", "npm install -g pnpm", "npm install -g pnpm"),
    "yarn": ("npm install -g yarn", "npm install -g yarn", "npm install -g yarn"),
}
_HINTS["npm"] = _HINTS["node"]
_HINTS["rust"] = _HINTS["cargo"]


def system_tool_hint(tool: str, platform: str | None = None) -> str:
    """N2: the exact install command of a system tool for this OS (`platform` is sys.platform; default the current).
    Autopilot prints it and never runs it. '' for an unknown tool."""
    row = _HINTS.get(str(tool).lower().strip())
    if not row:
        return ""
    p = platform or sys.platform
    return row[0] if p.startswith("win") else row[2] if p == "darwin" else row[1]


def check_deps(cfg: Config) -> tuple[str, str, str] | None:
    """N2: WARN row naming the lock files whose dependencies are not installed, with the command."""
    miss = missing_deps(cfg.root)
    if not miss:
        return None
    parts = [f"{m['lock']}: {m['command']}" + ("" if shutil.which(m["tool"]) or (m["tool"] == "python"
             and (shutil.which("python") or shutil.which("python3"))) else f" (needs {m['tool']}: "
             f"{system_tool_hint(m['tool'])})") for m in miss]
    return (WARN, "dependencies", "not installed; run " + "; ".join(parts))


def package_line() -> str:
    """Which Autopilot is imported: version and package path (shared by `ap doctor` and the run log)."""
    from . import __file__ as init_file, __version__
    return f"Autopilot {__version__} from {Path(init_file).resolve().parent}"


INSTALL_SOURCE = {"editable": "editable checkout", "uv": "uv tool", "pip": "pip"}  # Q10: how Autopilot got here


def check_package(root) -> tuple[str, str, str]:
    """WARN when the project's own autopilot/ folder is imported instead of the installed package. The line also names
    the install source (editable checkout, uv tool, pip), so `ap upgrade` and a repair pick the right route (Q10)."""
    from .upgrade import detect_install
    line = package_line() + f", installed as: {INSTALL_SOURCE.get(detect_install(), 'pip')}"
    pkg = Path(line.split(" from ", 1)[1].split(", installed as:", 1)[0])
    if Path(root).resolve() in pkg.parents:
        return (WARN, "autopilot", line + ": the project's own autopilot/ folder is imported, not the installed Autopilot")
    return (OK, "autopilot", line)


def checks(cfg: Config) -> list[tuple[str, str, str]]:
    """(level, name, detail) per check. FAIL = the run would break; WARN = it runs, but something is missing."""
    out = [check_path(), check_package(cfg.root)]
    explicit = os.environ.get("AUTOPILOT_CLAUDE_BIN") or os.environ.get("AUTODEV_CLAUDE_BIN")  # a choice, like pick_runner
    if not runner_chosen(cfg.root) and not explicit:  # Q1: never `claude login` on a machine that never chose Claude
        found = installed_runners()
        out.append((WARN, "runner", "none chosen yet; `ap setup` picks one" + (": found " + ", ".join(
            f"{r.binary} ({'logged in' if ok else 'logged out'})" for r, _, ok in found) if found else "")))
    elif cfg.get("agent.backend", "claude_cli") == "claude_cli":
        out += check_claude(cfg)
        out += [g for g in [check_user_guards(cfg)] if g]
    elif cfg.get("agent.backend") == "openai_compat":  # P12-T02: the local endpoint, WARN when it does not answer
        out.append(check_endpoint(cfg))
    elif cfg.get("agent.backend") == "command":
        from .backends.command import command_template
        exe = command_template(cfg).split()
        found = bool(exe) and shutil.which(exe[0])
        out.append((OK if found else FAIL, "agent command", f"{exe[0] if exe else '(empty)'} "
                    + ("found" if found else "not found on PATH")))

    rc, txt = _run(["git", "--version"])
    out.append((OK if rc == 0 else FAIL, "git", txt.splitlines()[0] if rc == 0 and txt else "not found on PATH"))
    from .gitops import other_vcs, vcs_line  # W65: another version control gets one line, not an adapter
    if vcs := other_vcs(cfg.root):
        out.append((WARN, "version control", vcs_line(vcs)))
    from .rights import describe
    out.append((OK, "rights", describe()))  # N8: what the installer took and how to undo it
    if cfg.get("git.push"):
        rc, url = _run(["git", "remote", "get-url", "origin"], cwd=cfg.root)
        out.append((OK if rc == 0 else FAIL, "git remote", url if rc == 0 else "git.push is on but there is no origin"))

    needs_gh = [k for k, on in (("intake.enabled", cfg.get("intake.enabled")),
                                ("git.mode: pr", cfg.get("git.mode") == "pr")) if on]
    if needs_gh:
        rc, txt = _run(["gh", "auth", "status"])
        out.append((OK if rc == 0 else FAIL, "gh", ("logged in" if rc == 0 else "not installed or not logged in "
                    "(`gh auth login`)") + f"; needed by {', '.join(needs_gh)}"))

    if allowlist_on(cfg) and sys.platform.startswith("linux"):
        missing = [b for b in ("bwrap", "socat") if not shutil.which(b)]
        out.append((FAIL if missing else OK, "sandbox", f"missing {', '.join(missing)} (apt install bubblewrap socat)"
                    if missing else "bubblewrap and socat found"))
    if sandbox_mode(cfg) == "docker":  # W11: the docker mode needs the docker CLI on PATH
        rc, txt = _run(["docker", "version", "--format", "{{.Server.Version}}"]) if sys.platform == "win32" else (1, "")
        if rc == 0 and txt:  # W32: Docker Desktop on native Windows; the engine reports its version
            out.append((OK, "docker", f"{txt.splitlines()[0]} (Docker Desktop)"))
        else:
            rc, txt = _run(["docker", "--version"])
            ver = re.search(r"version ([\w.+-]+)", txt)
            out.append((OK, "docker", f"found {ver.group(1) if ver else txt.splitlines()[0]}") if rc == 0 and txt
                       else (FAIL, "docker", "not found (needed for sandbox.mode: docker)"))

    channels = [cfg.get(f"notify.{k}") for k in NOTIFY_ENVS if _env(str(cfg.get(f"notify.{k}") or ""))]
    out.append((OK if channels else WARN, "notifications", f"via {', '.join(channels)}" if channels else
                "none set: you will not hear about decisions (docs/NEEDS-YOU.md) or a finished run"))
    if cfg.get("chat.enabled"):
        need = [str(cfg.get(f"notify.{k}")) for k in ("telegram_token_env", "telegram_chat_env")]
        miss = [n for n in need if not _env(n)]
        out.append((FAIL if miss else OK, "telegram chat", f"chat.enabled but {', '.join(miss)} not set" if miss
                    else "bot token and chat id set"))

    out += [d for d in [check_deps(cfg)] if d]
    line = _config_load_line(cfg)
    if line:
        out.append((OK, "claude config", line + " (from the last session)"))
    for e in cfg.blocking_errors():
        out.append((FAIL, "config", e))
    for e in sorted(set(cfg.validate()) - set(cfg.blocking_errors())):
        out.append((WARN, "config", e))
    return out
