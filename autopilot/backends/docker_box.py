"""W11: `sandbox.mode: docker` runs each Claude CLI session in a plain `docker run` container (stdlib only).

Only the worktree (at /work), its git folders and a temp login folder are mounted, never the home folder. Secret
variables pass by name (`-e NAME`), so their values never appear in argv or in `ps` output."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from ..proc import run_proc

SECRET_NAMES = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
KNOB_NAMES = ("ENABLE_CLAUDEAI_MCP_SERVERS",)
# Host-only: the container has its own config folder (/claude) and its own claude binary.
NEVER = ("CLAUDE_CONFIG_DIR", "AUTOPILOT_CLAUDE_BIN", "AUTODEV_CLAUDE_BIN")


def env_names(cfg, env: dict) -> list[str]:
    """Names (never values) of the variables the container gets: the secrets, every ANTHROPIC_*/CLAUDE_* variable
    and knob the backend sets (ClaudeCLIBackend.env()), and the keys of agent.env."""
    extra = cfg.get("agent.env")
    names = set(SECRET_NAMES) | {k for k in env if k.startswith(("ANTHROPIC_", "CLAUDE_")) or k in KNOB_NAMES}
    names |= {str(k) for k in extra} if isinstance(extra, dict) else set()
    return sorted(names - set(NEVER))


def _inside(path: str, root: str) -> bool:
    a, b = os.path.normpath(path), os.path.normpath(root)
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # other drive on Windows
        return False


def git_mounts(cwd: str, git_dirs=()) -> list[str]:
    """git_dirs[0] = common dir (read-only), git_dirs[1] = the worktree's own git dir (read-write), both at their host
    paths so the worktree's `.git` file resolves. A dir inside cwd is already under /work and is skipped."""
    out, seen = [], []
    for i, d in enumerate(git_dirs):
        if not d or d in seen or _inside(d, cwd):
            continue
        seen.append(d)
        out += ["-v", f"{d}:{d}" + (":ro" if i == 0 else "")]
    return out


def docker_argv(cfg, cmd, cwd, login_dir, git_dirs=(), uid=None, env=None, name="") -> list[str]:
    """The `docker run` argv for one session; cmd[0] (the host claude binary) becomes `claude` in the image.
    No -t: the prompt arrives on stdin. uid is a (uid, gid) tuple or None."""
    argv = ["docker", "run", "--rm", "-i"] + (["--name", name] if name else [])
    argv += ["--network", str(cfg.get("sandbox.network") or "bridge")]
    if uid:
        argv += ["--user", f"{uid[0]}:{uid[1]}", "-e", "HOME=/tmp"]
    argv += ["-v", f"{cwd}:/work", "-w", "/work", "-e", "CLAUDE_CONFIG_DIR=/claude", "-v", f"{login_dir}:/claude"]
    argv += git_mounts(str(cwd), git_dirs)
    for n in env_names(cfg, env or {}):
        argv += ["-e", n]
    return argv + [str(cfg.get("sandbox.image")), "claude", *cmd[1:]]


def git_dirs(cwd) -> tuple[str, ...]:
    """(common dir, git dir) as absolute host paths; () when git fails or cwd is no repository."""
    try:
        p = run_proc(["git", "rev-parse", "--git-common-dir", "--git-dir"], cwd=cwd, timeout=30)
    except OSError:
        return ()
    lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    if p.rc != 0 or len(lines) != 2:
        return ()
    return tuple(os.path.normpath(os.path.join(str(cwd), ln)) for ln in lines)  # git < 2.31 prints relative paths


def host_user():
    """(uid, gid) of this process, so files the agent writes stay the user's own; None on Windows."""
    return (os.getuid(), os.getgid()) if hasattr(os, "getuid") else None


@contextmanager
def login_dir(env=None):
    """A fresh 0700 temp folder outside the worktree with a copy of ~/.claude/.credentials.json (0600) when it exists;
    deleted on exit. The home folder itself is never mounted. W32: on Windows the source folder is CLAUDE_CONFIG_DIR
    of the session env when set."""
    path = tempfile.mkdtemp(prefix="autopilot-claude-")
    try:
        cfg_dir = (env or {}).get("CLAUDE_CONFIG_DIR") if sys.platform == "win32" else None
        src = Path(cfg_dir or Path.home() / ".claude") / ".credentials.json"
        if src.is_file():
            dst = os.path.join(path, ".credentials.json")
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def wrapped(cfg, cmd, cwd, env):
    """The docker argv of one session. On exit the container is removed (a killed docker client does not stop it,
    even with --rm) and the login folder is deleted."""
    name = f"autopilot-{uuid.uuid4().hex[:12]}"
    try:
        with login_dir(env) as login:
            yield docker_argv(cfg, cmd, os.path.abspath(cwd), login, git_dirs(cwd), host_user(), env, name)
    finally:
        try:
            run_proc(["docker", "rm", "-f", name], timeout=30)
        except OSError:
            pass
