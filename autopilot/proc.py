"""Process helpers: UTF-8 everywhere, whole-tree kill on timeout, a portable run lock, least-privilege env."""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from dataclasses import dataclass

WINDOWS = os.name == "nt"

# Passed to agent sessions and to the gate commands that run agent-written code. Everything else (notify tokens,
# deploy secrets, cloud keys) stays with the orchestrator unless listed in `agent.env_passthrough`.
SAFE_ENV = {
    "PATH", "PATHEXT", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "COMSPEC", "TEMP", "TMP", "TMPDIR", "USER", "USERNAME", "LOGNAME", "SHELL", "TERM", "LANG", "TZ",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS", "IS_SANDBOX", "VIRTUAL_ENV", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
    # toolchain locations (not secrets): builds and tests fail without them
    "JAVA_HOME", "GOPATH", "GOROOT", "GOCACHE", "GOMODCACHE", "CARGO_HOME", "RUSTUP_HOME", "NVM_DIR", "PNPM_HOME",
    "PYENV_ROOT", "CONDA_PREFIX", "DOTNET_ROOT", "ANDROID_HOME", "GRADLE_USER_HOME", "MAVEN_HOME", "DOCKER_HOST",
}
SAFE_PREFIXES = ("LC_", "XDG_", "ANTHROPIC_", "CLAUDE_")


@dataclass
class Proc:
    rc: int
    stdout: str
    stderr: str
    timed_out: bool = False


def safe_env(passthrough=(), extra: dict | None = None) -> dict:
    keep = SAFE_ENV | {str(k).upper() for k in passthrough}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep or k.upper().startswith(SAFE_PREFIXES)}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env


def agent_env(cfg) -> dict:
    """Environment for agent sessions and agent-written code (tests, builds)."""
    return safe_env(cfg.get("agent.env_passthrough", []) or [], cfg.get("agent.env", {}) or {})


def _kill_tree(p: subprocess.Popen):
    if WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGKILL)


def run_proc(cmd, *, cwd=None, env=None, input: str | None = None, timeout: float | None = None,
             shell: bool = False) -> Proc:
    """subprocess.run(capture_output=True, text=True) with UTF-8 decoding, stdin closed unless `input` is given, and
    the whole process tree killed on timeout or interrupt. Raises OSError if the program cannot be started."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    p = subprocess.Popen(cmd, shell=shell, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, **group)
    try:
        out, err = p.communicate(input, timeout=timeout)
        return Proc(p.returncode, out or "", err or "")
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        try:
            out, err = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:  # ponytail: a detached grandchild still holds the pipes; drop its output
            out, err = "", ""
        return Proc(124, out or "", err or "", timed_out=True)
    except BaseException:  # Ctrl+C / SystemExit: never leave an orphaned agent behind
        _kill_tree(p)
        raise


@contextlib.contextmanager
def exclusive_lock(path):
    """Non-blocking exclusive lock on `path`; raises BlockingIOError while another process holds it."""
    fh = open(path, "a+")
    try:
        if WINDOWS:
            import msvcrt
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as e:
                raise BlockingIOError(str(e)) from e
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
    finally:
        fh.close()
