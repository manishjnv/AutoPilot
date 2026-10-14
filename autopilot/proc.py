"""Process helpers: UTF-8 everywhere, whole-tree kill on timeout, a portable run lock, least-privilege env."""
from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import tempfile
import threading
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


def pid_alive(pid) -> bool:
    """W37: is the process `pid` running? A missing or non-integer pid counts as alive (an old run.json has none)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if WINDOWS:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5 or k32.GetLastError() == 5  # access denied = it exists
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass
class Proc:
    rc: int
    stdout: str
    stderr: str
    timed_out: bool = False
    stopped: str = ""      # why the tree was killed early: on_line's reason (stream_proc) or OWNER_STOP
    ended: bool = False    # stream_proc: `done` fired and the tree had to be stopped after the grace time


def safe_env(passthrough=(), extra: dict | None = None) -> dict:
    keep = SAFE_ENV | {str(k).upper() for k in passthrough}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep or k.upper().startswith(SAFE_PREFIXES)}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return with_tool_dirs(env)


def python_tool_dirs() -> list[str]:
    """Where `pip install` puts command-line tools for this Python: the interpreter's Scripts/bin folder and the
    per-user one (used when the system folder isn't writable, e.g. C:\\Python3xx on Windows)."""
    import sysconfig
    out = []
    for scheme in (None, sysconfig.get_preferred_scheme("user")):
        try:
            d = sysconfig.get_path("scripts", scheme) if scheme else sysconfig.get_path("scripts")
        except KeyError:
            continue
        if d and os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def with_tool_dirs(env: dict) -> dict:
    """`env` with the Python tool folders appended to PATH when missing. Without this a check like `ruff check .`
    fails as "command not found" right after setup installed ruff (seen on the first real run)."""
    key = next((k for k in env if k.upper() == "PATH"), "PATH")
    parts = [p for p in str(env.get(key, "")).split(os.pathsep) if p]
    have = {os.path.normcase(p.rstrip("\\/")) for p in parts}
    parts += [d for d in python_tool_dirs() if os.path.normcase(d.rstrip("\\/")) not in have]
    return {**env, key: os.pathsep.join(parts)}


def agent_env(cfg) -> dict:
    """Environment for agent sessions and agent-written code (tests, builds)."""
    return safe_env(cfg.get("agent.env_passthrough", []) or [], cfg.get("agent.env", {}) or {})


_job_warned = False


def _make_job(p: subprocess.Popen):
    """W37c: Windows job object (kill on close) holding `p`; taskkill /T misses a grandchild whose parent is gone."""
    import ctypes
    from ctypes import wintypes
    u64, sz = ctypes.c_uint64, ctypes.c_size_t

    class Basic(ctypes.Structure):
        _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("c", sz), ("d", sz), ("e", wintypes.DWORD), ("f", sz), ("g", wintypes.DWORD),
                    ("h", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("io", u64 * 6), ("m1", sz), ("m2", sz), ("m3", sz), ("m4", sz)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = Extended()
    info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            and k32.AssignProcessToJobObject(job, ctypes.c_void_p(int(p._handle)))):
        err = ctypes.get_last_error()
        k32.CloseHandle(job)
        raise OSError(err, "job object setup failed")
    return job


def _attach_job(p: subprocess.Popen):
    """Put `p` in a job object on Windows. Any failure logs once and keeps the taskkill path."""
    global _job_warned
    p._ap_job = None
    if not WINDOWS:
        return
    try:
        p._ap_job = _make_job(p)
    except Exception as e:  # noqa: BLE001 - never stop a session over this
        if not _job_warned:
            _job_warned = True
            logging.getLogger(__name__).warning("job object unavailable, using taskkill /T only: %s", e)


def _job_call(name: str, job, *args):
    import ctypes
    fn = getattr(ctypes.WinDLL("kernel32", use_last_error=True), name)
    fn.argtypes = [ctypes.c_void_p] + [ctypes.c_uint] * len(args)
    return fn(job, *args)


def _close_job(p: subprocess.Popen):
    job = getattr(p, "_ap_job", None)
    p._ap_job = None
    if job:
        with contextlib.suppress(Exception):
            _job_call("CloseHandle", job)


def _kill_tree(p: subprocess.Popen):
    if WINDOWS:
        job = getattr(p, "_ap_job", None)
        if job:
            with contextlib.suppress(Exception):
                _job_call("TerminateJobObject", job, 1)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGKILL)


# W39: `ap stop --now`. An armed check (stop_when) is polled during run_proc / stream_proc; when it returns true the
# tree is interrupted (POSIX SIGINT, then OWNER_GRACE s for the report) and killed by pid / job object, never by name.
OWNER_STOP = "stopped by the owner"
OWNER_GRACE = 20
STOP_POLL = 1.0
_STOP_CHECK = None


@contextlib.contextmanager
def stop_when(check):
    """Arm `check()` (true = the owner asked to stop now) for the processes started inside the block."""
    global _STOP_CHECK
    old, _STOP_CHECK = _STOP_CHECK, check
    try:
        yield
    finally:
        _STOP_CHECK = old


def _owner_watch(p: subprocess.Popen, stopped: list, done: threading.Event):
    check = _STOP_CHECK
    while check and not done.wait(STOP_POLL) and p.poll() is None:
        try:
            hit = check()
        except Exception:  # noqa: BLE001 - a broken check never kills a session
            hit = False
        if not hit:
            continue
        stopped.append(OWNER_STOP)
        if not WINDOWS:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(p.pid, signal.SIGINT)
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(timeout=OWNER_GRACE)
        _kill_tree(p)
        return


def _start_watch(p: subprocess.Popen, stopped: list) -> threading.Event:
    done = threading.Event()
    if _STOP_CHECK is not None:
        threading.Thread(target=_owner_watch, args=(p, stopped, done), daemon=True).start()
    return done


def run_proc(cmd, *, cwd=None, env=None, input: str | None = None, timeout: float | None = None,
             shell: bool = False) -> Proc:
    """subprocess.run(capture_output=True, text=True) with UTF-8 decoding, stdin closed unless `input` is given, and
    the whole process tree killed on timeout or interrupt. Raises OSError if the program cannot be started."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    p = subprocess.Popen(cmd, shell=shell, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, **group)
    _attach_job(p)
    stopped: list[str] = []
    done = _start_watch(p, stopped)
    try:
        out, err = p.communicate(input, timeout=timeout)
        return Proc(p.returncode, out or "", err or "", stopped=stopped[0] if stopped else "")
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
    finally:
        done.set()
        _close_job(p)


def stream_proc(cmd, *, cwd=None, env=None, input: str | None = None, timeout: float | None = None,
                on_line=None, done=None, grace: float = 10) -> Proc:
    """run_proc for long agent sessions: stdout is read line by line as it arrives, and when `on_line(line)` returns a
    reason the whole tree is killed and the reason lands in `Proc.stopped`. W46: once `done(line)` is true (the final
    answer) the process gets `grace` seconds to exit, then its tree is killed and the run counts as finished (rc 0). stderr goes to a temp file (no pipe deadlock)."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    with tempfile.TemporaryFile() as errf:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                             stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=errf, **group)
        _attach_job(p)
        lines: list[str] = []
        stopped: list[str] = []
        ended: list[bool] = []

        def feed():
            with contextlib.suppress(OSError):  # the agent may exit before reading everything
                p.stdin.write(input)
                p.stdin.close()

        def read():
            for line in p.stdout:
                lines.append(line)
                why = on_line(line) if on_line and not stopped else ""
                if why:
                    stopped.append(why)
                    _kill_tree(p)
                elif done and not ended and done(line):
                    try:
                        p.wait(timeout=grace)
                    except subprocess.TimeoutExpired:
                        ended.append(True)
                        _kill_tree(p)

        threads = [threading.Thread(target=read, daemon=True)]
        if input is not None:
            threads.append(threading.Thread(target=feed, daemon=True))
        for t in threads:
            t.start()
        watching = _start_watch(p, stopped)  # not `done`: that name is the W46 final-answer callback
        timed_out = False
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(p)
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(timeout=15)
        except BaseException:  # Ctrl+C / SystemExit: never leave an orphaned agent behind
            _kill_tree(p)
            raise
        finally:
            watching.set()
            _close_job(p)
        threads[0].join(15)  # ponytail: a detached grandchild may still hold stdout; keep what was read
        errf.seek(0)
        err = errf.read().decode("utf-8", "replace")
    rc = 124 if timed_out else 0 if ended else (p.returncode if p.returncode is not None else -1)
    return Proc(rc, "".join(lines), err, timed_out=timed_out, stopped=stopped[0] if stopped else "", ended=bool(ended))


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
