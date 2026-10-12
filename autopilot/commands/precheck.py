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
    s = Snapshot(platform=sys.platform, home=str(home), cwd=cwd or os.getcwd(), path=path.split(os.pathsep), env=env)
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
    return s
