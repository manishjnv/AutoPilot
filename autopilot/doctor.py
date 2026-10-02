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


def _run(cmd: list[str], cwd=None) -> tuple[int, str]:
    try:
        p = run_proc(cmd, cwd=cwd, timeout=30)
    except OSError as exc:
        return 127, str(exc)
    return p.rc, (p.stdout + p.stderr).strip()


def _env(name: str) -> str:
    return os.environ.get(name) or (os.environ.get("AUTODEV_" + name[10:], "") if name.startswith("AUTOPILOT_") else "")


def check_claude() -> list[tuple[str, str, str]]:
    from .backends.claude_cli import ClaudeCLIBackend
    binary = ClaudeCLIBackend.resolve_binary()
    rc, out = _run([binary, "--version"])
    first = out.splitlines()[0] if out else ""
    # a broken install can still print a version, just not Claude Code's (seen: "Bun 1.4.3")
    if not (rc == 0 and "claude code" in out.lower() and re.search(r"\d+\.\d+\.\d+", out)):
        return [(FAIL, "claude CLI", f"`{binary} --version` gave rc {rc}: {first[:120] or 'no output'}. Reinstall "
                 "with `npm i -g @anthropic-ai/claude-code`, or set AUTOPILOT_CLAUDE_BIN to the real binary")]
    rc, _ = _run([binary, "auth", "status"])  # documented from 2.1.268: exit 0 = logged in
    return [(OK, "claude CLI", f"{first} ({binary})"),
            (OK, "claude login", "logged in") if rc == 0 else
            (WARN, "claude login", "not logged in, or a CLI older than 2.1.268: run `claude` and /login once")]


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
def fix_claude() -> str:
    npm = shutil.which("npm")
    if not npm:
        return "cannot fix: npm not found. Install Node.js (nodejs.org), then `npm i -g @anthropic-ai/claude-code`"
    try:
        p = run_proc([npm, "i", "-g", "@anthropic-ai/claude-code"], timeout=900)
    except OSError as exc:
        return f"cannot fix: {exc}"
    return "reinstalled with npm" if p.rc == 0 else f"npm install failed (rc {p.rc}): {(p.stderr or p.stdout)[-300:]}"


def write_launcher() -> str:
    """A one-line `autopilot` launcher in a user folder that is already on PATH, so the command works at once in every
    terminal, including ones VS Code opened before a PATH change. Only well-known per-user folders, never an
    arbitrary PATH entry. Returns where it was written, or ''."""
    if WINDOWS:
        prefer = [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps",
                  Path(os.environ.get("APPDATA", "")) / "npm"]
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


def checks(cfg: Config) -> list[tuple[str, str, str]]:
    """(level, name, detail) per check. FAIL = the run would break; WARN = it runs, but something is missing."""
    out = [check_path()]
    if cfg.get("agent.backend", "claude_cli") == "claude_cli":
        out += check_claude()
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

    for e in cfg.blocking_errors():
        out.append((FAIL, "config", e))
    for e in sorted(set(cfg.validate()) - set(cfg.blocking_errors())):
        out.append((WARN, "config", e))
    return out
