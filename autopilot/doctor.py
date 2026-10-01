"""`autopilot doctor`: check this machine and project before a run. Read-only; never starts an agent session."""
from __future__ import annotations

import os
import re
import shutil
import sys

from .config import Config
from .proc import run_proc

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


def checks(cfg: Config) -> list[tuple[str, str, str]]:
    """(level, name, detail) per check. FAIL = the run would break; WARN = it runs, but something is missing."""
    out = []
    if cfg.get("agent.backend", "claude_cli") == "claude_cli":
        out += check_claude()
    elif cfg.get("agent.backend") == "command":
        exe = (cfg.get("agent.command") or "").split()
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
