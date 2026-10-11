"""`autopilot doctor`: check this machine and project before a run, and fix what can be fixed without a person.
Checks are read-only and never start an agent session; fixes run only through `autofix()`."""
from __future__ import annotations

import os
import re
import shutil
import sys
import sysconfig
from pathlib import Path

from .config import Config
from .proc import WINDOWS, run_proc

OK, WARN, FAIL = "ok", "WARN", "FAIL"
NOTIFY_ENVS = ("telegram_token_env", "slack_webhook_env", "webhook_env", "ntfy_topic_env")


def _run(cmd: list[str], cwd=None, timeout: float = 30) -> tuple[int, str]:
    try:
        p = run_proc(cmd, cwd=cwd, timeout=timeout)
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


def check_login(binary: str, version: tuple, cfg, timeout: float = 30) -> tuple[str, str, str]:
    """H2: FAIL only when a login is surely missing: a CLI that has `auth status`, and no other way to pay."""
    rc, out = _run([binary, "auth", "status"], timeout=timeout)  # documented from 2.1.268: exit 0 = logged in
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


# N3: agent CLIs in the order preflight tries them -> (binary, backend choice, read-only status argv or None,
# documented key variables). A key variable counts first: no process to start. Never a `login` argument here.
LOGIN_TIMEOUT = 20  # N10
RUNNERS = (
    ("claude", "claude_cli", None, OTHER_AUTH),
    ("kiro-cli", "kiro", ("whoami",), ("KIRO_API_KEY",)),
    ("cursor-agent", "cursor", ("status",), ("CURSOR_API_KEY",)),
    ("codex", "codex", ("login", "status"), ("CODEX_API_KEY",)),
    ("gemini", "gemini", None, ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    ("aider", "aider", None, ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
                              "DEEPSEEK_API_KEY")),
)
# exit codes of the status commands are not documented: a logged-out CLI may still exit 0
LOGGED_OUT = re.compile(r"not (logged|signed) in|not authenticated|unauthenticated|logged out|no (active )?"
                        r"(session|credentials)|please (log|sign) ?in", re.I)
# N10: owner rule 2026-10-11, subscription login only. The one interactive login command per runner (never run by
# Autopilot: it prints the line and stops), and the runners whose only login is an API key (not supported).
LOGIN_CMD = {"claude_cli": "claude auth login", "codex": "codex login", "cursor": "cursor-agent login",
             "kiro": "kiro-cli login", "copilot": "gh auth login"}
NO_SUBSCRIPTION = ("gemini", "aider", "opencode", "amp", "qwen", "goose")


def check_runner_login(cfg, env=None) -> tuple[str, str, str]:
    """N10: the configured runner (a `command` preset) is logged in with its own subscription; stdin closed, CI=1,
    LOGIN_TIMEOUT. FAIL names the one login command. No credential file is read, written or copied."""
    preset = str(cfg.get("agent.preset") or "")
    if cfg.get("agent.command") or not preset:
        return OK, "runner login", "custom command: not checked"
    if preset in NO_SUBSCRIPTION:
        return (WARN, "runner login",
                f"`{preset}` needs an API key, not supported (subscription runners: {', '.join(LOGIN_CMD)})")
    row = next((r for r in RUNNERS if r[1] == preset), None)
    if row is None:
        return WARN, "runner login", f"no login check for preset `{preset}`"
    binary, _, status, keys = row
    env = dict(os.environ if env is None else env)
    exe = shutil.which(binary, path=next((v for k, v in env.items() if k.upper() == "PATH"), None))
    if not exe:
        return FAIL, "runner login", f"`{binary}` is not on PATH"
    if _logged_in(exe, binary, status, keys, env):
        return OK, "runner login", f"{binary} logged in"
    return FAIL, "runner login", f"{binary} is not logged in: run `{LOGIN_CMD.get(preset, binary + ' login')}`, then start again"


def _logged_in(path: str, binary: str, status: tuple | None, keys: tuple, env: dict) -> bool:
    """N3: True when a key variable is set (only its presence is read), or the status command exits 0 within
    LOGIN_TIMEOUT without logged-out wording. A timeout or a program that does not start counts as logged out."""
    if any(env.get(k) for k in keys):
        return True
    if binary == "claude":
        return check_login(path, (0, 0, 0), None, timeout=LOGIN_TIMEOUT)[0] == OK
    if not status:
        return False
    try:
        p = run_proc([path, *status], env={**env, "CI": "1"}, timeout=LOGIN_TIMEOUT)  # N10: no prompt, no browser
    except OSError:
        return False
    return p.rc == 0 and not p.timed_out and not LOGGED_OUT.search(p.stdout + p.stderr)


def detect_runner(env=None) -> str | None:
    """N3: the backend choice (`claude_cli`, or a preset name) of the first agent CLI on PATH that is installed and
    logged in, in RUNNERS order; None when there is none. Read-only: never starts a login."""
    env = dict(os.environ if env is None else env)
    path = next((v for k, v in env.items() if k.upper() == "PATH"), "")
    if not path:
        return None
    for binary, backend, status, keys in RUNNERS:
        exe = shutil.which(binary, path=path)
        if exe and _logged_in(exe, binary, status, keys, env):
            return backend
    return None


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
    return [(OK, "claude CLI", f"{first} ({binary})"), check_login(binary, version, cfg)]


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
    print(f"fix   claude CLI: running `{shown}` (this downloads and installs Claude Code)", flush=True)
    try:
        p = run_proc([shutil.which(cmd[0]) or cmd[0]] + cmd[1:], timeout=900)
    except OSError as exc:
        return f"cannot fix: {exc}. Run `{shown}` yourself"
    return (f"reinstalled ({route})" if p.rc == 0 else
            f"install failed (rc {p.rc}): {(p.stderr or p.stdout)[-300:]}. Run `{shown}` yourself")


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


def check_package(root) -> tuple[str, str, str]:
    """WARN when the project's own autopilot/ folder is imported instead of the installed package."""
    line = package_line()
    pkg = Path(line.split(" from ", 1)[1])
    if Path(root).resolve() in pkg.parents:
        return (WARN, "autopilot", line + ": the project's own autopilot/ folder is imported, not the installed Autopilot")
    return (OK, "autopilot", line)


def checks(cfg: Config) -> list[tuple[str, str, str]]:
    """(level, name, detail) per check. FAIL = the run would break; WARN = it runs, but something is missing."""
    out = [check_path(), check_package(cfg.root)]
    if cfg.get("agent.backend", "claude_cli") == "claude_cli":
        out += check_claude(cfg)
        out += [g for g in [check_user_guards(cfg)] if g]
    elif cfg.get("agent.backend") == "command":
        from .backends.command import command_template
        exe = command_template(cfg).split()
        found = bool(exe) and shutil.which(exe[0])
        out.append((OK if found else FAIL, "agent command", f"{exe[0] if exe else '(empty)'} "
                    + ("found" if found else "not found on PATH")))

    rc, txt = _run(["git", "--version"])
    out.append((OK if rc == 0 else FAIL, "git", txt.splitlines()[0] if rc == 0 and txt else "not found on PATH"))
    if cfg.get("git.push"):
        rc, url = _run(["git", "remote", "get-url", "origin"], cwd=cfg.root)
        out.append((OK if rc == 0 else FAIL, "git remote", url if rc == 0 else "git.push is on but there is no origin"))

    needs_gh = [k for k, on in (("intake.enabled", cfg.get("intake.enabled")),
                                ("git.mode: pr", cfg.get("git.mode") == "pr")) if on]
    if needs_gh:
        rc, txt = _run(["gh", "auth", "status"])
        out.append((OK if rc == 0 else FAIL, "gh", ("logged in" if rc == 0 else "not installed or not logged in "
                    "(`gh auth login`)") + f"; needed by {', '.join(needs_gh)}"))

    if cfg.get("sandbox.enabled") and sys.platform.startswith("linux"):
        missing = [b for b in ("bwrap", "socat") if not shutil.which(b)]
        out.append((FAIL if missing else OK, "sandbox", f"missing {', '.join(missing)} (apt install bubblewrap socat)"
                    if missing else "bubblewrap and socat found"))

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
