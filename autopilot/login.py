"""Q13: the login address is always on the screen as text, never only in a browser. A machine with no desktop (WSL, SSH,
a container, a snap-confined desktop, no browser) runs the headless form of the login (a device code); a desktop runs the
normal form and prints the same address anyway, so a blocked browser never stalls the person. No credential file is read,
written or copied: the vendor's own command does the login."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading

from .doctor import Runner
from .proc import WINDOWS, _kill_tree

LOGIN_WAIT = 900  # seconds; the vendors' device codes expire sooner (about 15 minutes), so this never waits longer
URL = re.compile(r"https?://[^\s<>\"')\]]+")
CODE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,5}\b")


def headless_why(env: dict | None = None, platform: str | None = None, exists=os.path.exists) -> str:
    """'' on a desktop; otherwise one short reason why the browser form cannot be trusted here."""
    env = os.environ if env is None else env
    plat = platform or sys.platform
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return "this is WSL"
    if env.get("SSH_CONNECTION") or env.get("SSH_TTY"):
        return "this is an SSH session"
    if exists("/.dockerenv") or exists("/run/.containerenv") or env.get("KUBERNETES_SERVICE_HOST"):
        return "this is a container"
    if env.get("SNAP") or env.get("SNAP_NAME"):
        return "this desktop is snap-confined"
    if plat.startswith("linux") and not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY") or env.get("BROWSER")):
        return "no desktop and no browser was found"
    return ""


def login_argv(row: Runner, exe: str, headless: bool) -> list[str]:
    """The login command of the row (the headless form when asked and when the row has one), with the program path."""
    text = row.login_headless if headless and row.login_headless else row.login
    argv = shlex.split(text, posix=not WINDOWS)
    return [exe, *argv[1:]]


def _run(argv: list[str], env: dict, headless: bool, on_line, wait: float) -> int:
    """Run the command, hand every output line (stdout and stderr together) to `on_line` as it arrives."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    if WINDOWS and str(argv[0]).lower().endswith((".cmd", ".bat")):  # a script needs cmd.exe (Python 3.10 does not add it)
        argv = ["cmd", "/c", *argv]
    p = subprocess.Popen(argv, env=env, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL if headless else None,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **group)

    def read():
        for line in p.stdout:
            on_line(line.rstrip("\r\n"))
    t = threading.Thread(target=read, daemon=True)
    t.start()
    try:
        p.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        t.join(5)
        return 124
    except BaseException:
        _kill_tree(p)
        raise
    t.join(5)
    return p.returncode


def login_runner(row: Runner, exe: str, *, env: dict | None = None, say=print, wait: float = LOGIN_WAIT,
                 platform: str | None = None, exists=os.path.exists) -> bool:
    """Run the login of one runner. Every address and code the vendor prints is repeated as plain text on its own line.
    True when the login command ends with exit code 0."""
    env = dict(os.environ if env is None else env)
    why = headless_why(env, platform, exists)
    argv = login_argv(row, exe, bool(why))
    if why:
        say(f"login     {why}: no browser is opened. Open the address below on any device, then type the code there.")
    else:
        say("login     the login opens in your browser; the address is printed here too, in case the browser is blocked.")
    say(f"login     running: {' '.join([row.binary, *argv[1:]])}")
    seen: set[str] = set()

    def on_line(line: str):
        for url in URL.findall(line):
            if url not in seen:
                seen.add(url)
                say(f"address   {url}")
        for code in CODE.findall(line):
            if code not in seen:
                seen.add(code)
                say(f"code      {code}")
    try:
        rc = _run(argv, env, bool(why), on_line, wait)
    except OSError:
        say(f"FAILED  login {row.name}: the program did not start. Run `{row.login}` by hand.")
        return False
    if rc == 124:
        say(f"login     no answer within {int(wait // 60)} minutes: the code has expired. Run `ap setup` to get a new one.")
        return False
    if rc != 0:
        say(f"login     the login did not finish. Run `{row.login_headless if why and row.login_headless else row.login}` by hand.")
        return False
    say(f"login     {row.name}: done")
    return True


def tty_ok() -> bool:
    return bool(sys.stdin and sys.stdin.isatty() and sys.stdout.isatty())
