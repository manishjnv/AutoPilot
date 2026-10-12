"""Q6: environment pre-check lines for `ap setup`: one line each, `found` / `fixed` / `skipped`, fixed without rights
where possible. Every check is a pure function over a `Snapshot`, so a test builds the machine it wants; `gather()`
reads the real machine. The sentences live in `install_errors.PRECHECK` (one catalogue, Q4)."""
from __future__ import annotations

import os
import platform as _platform
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..install_errors import PRECHECK, os_name
from ..proc import run_proc


@dataclass
class Snapshot:
    platform: str = sys.platform
    home: str = ""
    cwd: str = ""
    path: list = field(default_factory=list)      # PATH entries
    env: dict = field(default_factory=dict)        # names only matter; values are read for PATH and proxies
    uid: int = 1000
    sudo_user: str = ""
    machine: str = "x86_64"                        # platform.machine()
    win_32bit: bool = False
    home_writable: bool = True
    python_exe: str = ""
    uv_version: str = ""                           # `uv --version` first line
    pip_autopilot: bool = False                    # `pip show dev-autopilot` succeeds
    uv_autopilot: bool = False                     # `uv tool list` names dev-autopilot
    wsl: int = 0                                   # 0 = no WSL, 1 or 2
    runner_paths: dict = field(default_factory=dict)  # binary -> [every path on PATH]
    tokens: list = field(default_factory=list)     # token variable names that are set
    logged_in: list = field(default_factory=list)  # runner keys with a stored login
    git_user: tuple = ("", "")
    gh_user: tuple = ("", "")                      # name, no-reply email from `gh api user` when logged in
    long_paths: bool | None = None                 # Windows LongPathsEnabled; None = unknown or not Windows
    net_ok: bool | None = None                     # None = not probed
    tls_failed: bool = False                       # a probe failed on the certificate chain
    leftovers: list = field(default_factory=list)  # ~/.claude style folders with no binary
    # Q21: eight more lines. Defaults mean "fine or not probed", so a clean machine still prints no line.
    in_repo: bool = False                           # cwd holds a git repository
    git_dubious: bool = False                       # `git status` failed with the dubious-ownership text
    autocrlf: str = ""                              # `git config core.autocrlf` of the project
    api_keys: list = field(default_factory=list)   # names of ANTHROPIC_API_KEY, OPENAI_API_KEY, CODEX_API_KEY that are set
    clock_skew: float | None = None                 # seconds against an HTTP Date header; None = not probed
    free_gb: float | None = None                    # free space of the home and project drive (the smaller one)
    git_version: tuple | None = None                # (major, minor) of `git --version`
    console_utf8: bool | None = None                # Windows console encoding is UTF-8; None = not Windows or unknown
    port_busy: int = 0                              # the status page port in use (0 = free); `port_next` is the free one
    port_next: int = 0


Line = tuple[str, str, str]  # (id, status, text)


def _say(id_: str, status: str, detail: str = "", platform: str | None = None) -> Line:
    sentence, fix = PRECHECK[id_]
    fix = fix if isinstance(fix, str) else fix.get(os_name(platform), "")
    text = sentence + (f" {detail}" if detail else "") + (f" Command: {fix}" if fix and status != "fixed" else "")
    return id_, status, text


def check(s: Snapshot) -> list[Line]:
    """Every line that applies to this machine, in a fixed order. No side effect: `apply()` does the fixes."""
    out: list[Line] = []
    p = s.platform
    win = os_name(p) == "windows" or ("\\" in s.home and ":" in s.home[:3])  # a Windows home path, on any platform
    sep = "\\" if win else "/"
    local_bin = s.home.rstrip("\\/") + sep + ".local" + sep + "bin"

    def key(x: str) -> str:
        x = x.rstrip("\\/")
        return x.replace("\\", "/").lower() if win else x
    if s.home and key(local_bin) not in {key(x) for x in s.path if x}:
        out.append(_say("local-bin", "skipped", f"The folder is {local_bin}.", p))
    proxies = [k for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY") if s.env.get(k)]
    if proxies:
        out.append(_say("proxy", "found", f"Set: {', '.join(proxies)}.", p))
    if s.tls_failed and not (s.env.get("SSL_CERT_FILE") or s.env.get("REQUESTS_CA_BUNDLE")):
        out.append(_say("corporate-ca", "skipped", "", p))
    if s.net_ok is False:
        out.append(_say("offline", "skipped", "", p))
    if s.win_32bit:
        out.append(_say("win32-bit", "skipped", "", p))
    elif s.machine.lower() in ("arm64", "aarch64"):
        out.append(_say("arm", "found", f"Machine: {s.machine}.", p))
    if s.home and (" " in s.home or not s.home.isascii()):
        out.append(_say("home-path", "found", f"Home: {s.home}.", p))
    low = s.home.lower().replace("\\", "/")
    if s.home and ("onedrive" in low or s.home.startswith("\\\\") or low.startswith("//")):
        out.append(_say("home-cloud", "found", f"Home: {s.home}.", p))
    if s.home and not s.home_writable:
        out.append(_say("home-readonly", "skipped", f"Home: {s.home}.", p))
    if s.uid == 0 or s.sudo_user:
        out.append(_say("root", "found", f"User: {'root' if s.uid == 0 else s.sudo_user + ' through sudo'}.", p))
    py = s.python_exe.replace("\\", "/").lower()
    if any(k in py for k in ("/conda", "anaconda", "miniconda", "/.pyenv/shims/")):
        out.append(_say("python-shim", "found", f"Python: {s.python_exe}.", p))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s.uv_version)
    if m and (date.today() - date(int(m[1]), int(m[2]), int(m[3]))).days > 365:
        out.append(_say("uv-old", "skipped", f"uv: {s.uv_version}.", p))
    if s.pip_autopilot and s.uv_autopilot:
        out.append(_say("two-autopilots", "found", "", p))
    if s.wsl == 1:
        out.append(_say("wsl1", "found", "", p))
    if s.wsl and re.match(r"^/mnt/[a-z]/", s.cwd):
        out.append(_say("wsl-mnt", "found", f"Project: {s.cwd}.", p))
    for binary, paths in s.runner_paths.items():
        win = [x for x in paths if re.match(r"^/mnt/[a-z]/", x.replace("\\", "/"))]
        if s.wsl and win:
            out.append(_say("windows-binary-in-wsl", "skipped", f"{binary} at {win[0]}.", p))
        if len(set(paths)) > 1:
            out.append(_say("two-copies", "found", f"{binary}: {' and '.join(dict.fromkeys(paths))}.", p))
    for key in s.logged_in:
        from ..doctor import runner
        row = runner(key)
        hits = [t for t in (row.tokens if row else ()) if t in s.tokens]
        if hits:
            out.append(_say("token-overrides-login", "found", f"{hits[0]} is set; {row.name} also has a stored login.", p))
    if not (s.git_user[0] and s.git_user[1]):
        if s.gh_user[0] and s.gh_user[1]:
            out.append(_say("git-identity", "fixed", f"Set from your GitHub account: {s.gh_user[0]} <{s.gh_user[1]}>.", p))
        else:
            out.append(_say("git-identity", "skipped", "", p))
    if os_name(p) == "windows" and s.long_paths is False:
        out.append(_say("long-paths", "skipped", "", p))
    for left in s.leftovers:
        out.append(_say("leftover", "found", f"Folder: {left}.", p))
    # Q21
    if s.git_dubious:
        out.append(_say("git-dubious", "fixed", f"Folder: {s.cwd}.", p))
    if os_name(p) == "windows" and s.in_repo and s.autocrlf.lower() == "true":
        out.append(_say("autocrlf", "fixed", "", p))
    if s.api_keys:  # the names only; a value is never read into a line
        out.append(_say("api-key", "found", f"Set: {', '.join(s.api_keys)}.", p))
    if s.clock_skew is not None and abs(s.clock_skew) > 180:
        out.append(_say("clock-skew", "skipped", f"The clock is {int(abs(s.clock_skew) // 60)} minutes {'ahead' if s.clock_skew > 0 else 'behind'}.", p))
    if s.free_gb is not None and s.free_gb < 1:
        out.append(_say("low-disk", "skipped", f"Free: {s.free_gb:.1f} GB.", p))
    if s.git_version is not None and s.git_version < (2, 30):
        out.append(_say("git-old", "skipped", f"git: {s.git_version[0]}.{s.git_version[1]}.", p))
    if os_name(p) == "windows" and s.console_utf8 is False:
        out.append(_say("console-encoding", "skipped", "", p))
    if s.port_busy:
        out.append(_say("port-busy", "fixed", f"Port {s.port_busy} is in use; the status page takes port {s.port_next}.", p))
    return out


def apply(lines: list[Line], s: Snapshot, run=run_proc, dry_run: bool = False) -> list[Line]:
    """The rights-free fixes: `~/.local/bin` on PATH (a profile line, or the Windows user PATH) and the git identity from
    the GitHub account. A fix that fails turns its line into `skipped` with the command."""
    out = []
    for id_, status, text in lines:
        try:
            if id_ == "local-bin" and not dry_run:
                d = Path(s.home) / ".local" / "bin"
                if os_name(s.platform) == "windows":  # pragma: no cover - needs the registry
                    from ..doctor import _add_user_path_windows
                    _add_user_path_windows(d)
                    out.append(_say("local-bin", "fixed", f"{d} added to your user PATH (new terminals).", s.platform))
                else:
                    profile, line = Path(s.home) / ".profile", f'export PATH="$PATH:{d}"'
                    old = profile.read_text(encoding="utf-8") if profile.exists() else ""
                    if line not in old:
                        profile.write_text(old + ("" if not old or old.endswith("\n") else "\n") + line + "\n", encoding="utf-8")
                    out.append(_say("local-bin", "fixed", f"{d} added to PATH in {profile} (new login shells).", s.platform))
                continue
            if id_ == "git-identity" and status == "fixed" and not dry_run:
                run(["git", "config", "--global", "user.name", s.gh_user[0]], timeout=20)
                run(["git", "config", "--global", "user.email", s.gh_user[1]], timeout=20)
            if id_ == "git-dubious" and not dry_run:  # Q21.1: the one command git names itself
                if run(["git", "config", "--global", "--add", "safe.directory", s.cwd], timeout=20).rc != 0:
                    status = "skipped"
            if id_ == "autocrlf" and not dry_run:  # Q21.2: for this project only, never the global setting
                if run(["git", "-C", s.cwd, "config", "core.autocrlf", "false"], timeout=20).rc != 0:
                    status = "skipped"
                else:
                    ga = Path(s.cwd) / ".gitattributes"
                    if not ga.exists():
                        ga.write_text("* text=auto eol=lf\n", encoding="utf-8")
            if id_ == "port-busy" and dry_run:
                status = "skipped"
        except (OSError, ImportError):  # no registry on this system, or a read-only profile: the line stays `skipped`
            status = "skipped"
        out.append((id_, status, text))
    return out


def gather(env: dict | None = None, home: Path | None = None, which=None, run=run_proc, cwd: str | None = None,
           net_ok: bool | None = None, tls_failed: bool = False) -> Snapshot:
    """The real machine, read-only. Commands run: `uv --version`, `pip show`, `uv tool list`, `git config`, `gh api user`."""
    env = dict(os.environ if env is None else env)
    home = Path(home or env.get("HOME") or env.get("USERPROFILE") or Path.home())
    path = env.get("PATH", "")
    which = which or (lambda n: shutil.which(n, path=path))
    from ..doctor import RUNNERS as _ROWS
    secret = set(API_KEYS) | {t for r in _ROWS for t in r.tokens}  # Q21: a token or key value never enters the snapshot
    s = Snapshot(platform=sys.platform, home=str(home), cwd=cwd or os.getcwd(), path=path.split(os.pathsep),
                 env={k: ("set" if k in secret else v) for k, v in env.items()})
    s.uid = os.getuid() if hasattr(os, "getuid") else 1000
    s.sudo_user = env.get("SUDO_USER", "")
    s.machine = _platform.machine() or ""
    s.win_32bit = sys.platform.startswith("win") and _platform.architecture()[0] == "32bit"
    s.home_writable = os.access(home, os.W_OK)
    s.python_exe = sys.executable

    def out(cmd):
        try:
            p = run(cmd, timeout=30)
            return (p.stdout or "").strip() if p.rc == 0 else ""
        except OSError:
            return ""
    uv = which("uv")
    s.uv_version = out([uv, "--version"]).splitlines()[0] if uv and out([uv, "--version"]) else ""
    s.uv_autopilot = bool(uv) and "dev-autopilot" in out([uv, "tool", "list"])
    s.pip_autopilot = bool(out([sys.executable, "-m", "pip", "show", "dev-autopilot"]))
    try:
        ver = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        s.wsl = 2 if "WSL2" in ver else 1 if "microsoft" in ver.lower() else 0
    except OSError:
        s.wsl = 0
    from ..doctor import RUNNERS
    for row in RUNNERS:
        found = []
        for n in row.names:
            for d in path.split(os.pathsep):
                exe = shutil.which(n, path=d)
                if exe:
                    found.append(exe)
        if found:
            s.runner_paths[row.binary] = found
        home_marks = [str(home / f) for f in row.footprints if (home / f).exists()]
        if home_marks and not found:
            s.leftovers += home_marks
    s.tokens = sorted({t for row in RUNNERS for t in row.tokens if env.get(t)})
    git = which("git")
    if git:
        s.git_user = (out([git, "config", "--get", "user.name"]), out([git, "config", "--get", "user.email"]))
    gh = which("gh")
    if gh and not (s.git_user[0] and s.git_user[1]):
        name = out([gh, "api", "user", "--jq", ".name // .login"])
        ident = out([gh, "api", "user", "--jq", ".id"])
        login = out([gh, "api", "user", "--jq", ".login"])
        if name and ident and login:
            s.gh_user = (name, f"{ident}+{login}@users.noreply.github.com")
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
                s.long_paths = winreg.QueryValueEx(k, "LongPathsEnabled")[0] == 1
        except OSError:
            s.long_paths = None
    s.net_ok, s.tls_failed = net_ok, tls_failed
    _gather_q21(s, env, home, which, out, cwd or os.getcwd(), run)
    return s


API_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY")
STATUS_PORT = 8765


def port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def clock_skew(url: str = "https://api.github.com", fetch=None) -> float | None:
    """Seconds this clock is ahead of the server's HTTP `Date` header (negative = behind); None when it cannot be read.
    `fetch(url)` returns the Date header text; a test passes a fake, so no test reaches the network."""
    from email.utils import parsedate_to_datetime
    try:
        if fetch is None:
            import urllib.request
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310 - a fixed https address
                text = r.headers.get("Date", "")
        else:
            text = fetch(url)
        server = parsedate_to_datetime(text)
    except (OSError, ValueError, TypeError):
        return None
    import datetime
    return (datetime.datetime.now(datetime.timezone.utc) - server).total_seconds()


def _gather_q21(s: Snapshot, env: dict, home: Path, which, out, cwd: str, run=run_proc) -> None:
    """Q21: the facts of the eight new lines. Read-only; the only network call is one HEAD request for the Date header,
    and only when AUTOPILOT_NO_NETWORK_CHECKS is unset (the test suite sets it through conftest)."""
    s.api_keys = [k for k in API_KEYS if env.get(k)]  # presence only: the value is never stored
    git = which("git")
    if git:
        m = re.search(r"(\d+)\.(\d+)", out([git, "--version"]))
        s.git_version = (int(m[1]), int(m[2])) if m else None
        try:
            p = run([git, "-C", cwd, "status", "--porcelain"], timeout=20)
            text = (p.stdout or "") + (p.stderr or "")
            s.in_repo = p.rc == 0 or "dubious ownership" in text
            s.git_dubious = p.rc != 0 and "dubious ownership" in text
        except OSError:
            pass
        if s.in_repo and not s.git_dubious:
            s.autocrlf = out([git, "-C", cwd, "config", "--get", "core.autocrlf"])
    try:
        free = min(shutil.disk_usage(home).free, shutil.disk_usage(cwd).free)
        s.free_gb = free / 1e9
    except OSError:
        pass
    if sys.platform.startswith("win"):
        import ctypes
        try:
            s.console_utf8 = ctypes.windll.kernel32.GetConsoleOutputCP() == 65001
        except (AttributeError, OSError):
            s.console_utf8 = None
        if env.get("PYTHONIOENCODING", "").lower().replace("-", "") == "utf8":
            s.console_utf8 = True
    if not env.get("AUTOPILOT_NO_NETWORK_CHECKS"):
        s.clock_skew = clock_skew()
    if not port_free(STATUS_PORT):
        s.port_busy = STATUS_PORT
        s.port_next = next((p for p in range(STATUS_PORT + 1, STATUS_PORT + 11) if port_free(p)), 0)
        if not s.port_next:
            s.port_busy = 0
