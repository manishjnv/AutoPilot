"""N8: one consent at install start, then zero questions (owner rule 2026-10-11, one developer, one PC).

The installer takes the rights once: on Windows one UAC prompt creates the scheduled task `Autopilot-Setup` (run level
highest) that runs `%ProgramData%/Autopilot/setup.ps1` (writable by Administrators only) to install the winget ids
queued in that folder; on Linux and WSL one `sudo` writes `/etc/sudoers.d/autopilot`
(apt-get, dpkg, snap, brew without a password). A later run that needs a missing system tool goes through those
rights, logs it, names it on screen, and never asks. `ap uninstall --rights` removes both.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .proc import run_proc

log = logging.getLogger("autopilot")
TASK = "Autopilot-Setup"
SUDOERS = "/etc/sudoers.d/autopilot"
SUDO_LINE = "{user} ALL=(root) NOPASSWD: /usr/bin/apt-get, /usr/bin/dpkg, /usr/bin/snap, /usr/local/bin/brew"
WINGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{1,99}$")  # the queue holds ids only, never a command
APT_PKG = re.compile(r"^[a-z0-9][a-z0-9.+-]{1,99}$")


def win_dir() -> Path:
    """Windows: the folder the scheduled task trusts. The installer's elevated step creates it under ProgramData and
    gives only Administrators write access to `setup.ps1`; the queue file next to it is per-id text, pattern checked."""
    return Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData") / "Autopilot"


def queue_path() -> Path:
    return win_dir() / "setup-queue.txt"


def queue_write(winget_id: str, path: Path | None = None) -> bool:
    """Append one checked winget id to the queue. Refuses an id that is not a plain id and a queue outside `win_dir()`:
    the task reads only that folder, so a queue elsewhere would never run and must not be written."""
    q = path or queue_path()
    if not WINGET_ID.match(winget_id) or q.parent != win_dir():
        return False
    q.parent.mkdir(parents=True, exist_ok=True)
    with open(q, "a", encoding="utf-8") as fh:
        fh.write(winget_id + "\n")
    return True


def have_rights(platform: str | None = None) -> str:
    """'task' (Windows scheduled task), 'sudoers' (Linux file), 'brew' (macOS: nothing needed) or ''."""
    p = platform or sys.platform
    if p.startswith("win"):
        try:
            return "task" if run_proc(["schtasks", "/Query", "/TN", TASK], timeout=20).rc == 0 else ""
        except OSError:
            return ""
    if p == "darwin":
        return "brew"
    try:
        return "sudoers" if Path(SUDOERS).is_file() else ""
    except OSError:  # /etc/sudoers.d is not readable on every machine (CI runners): then no rights are known
        return ""


def _refresh_path():
    """Windows: a tool an installer just added is on the registry PATH, not yet in this process."""
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        parts = []
        for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            with winreg.OpenKey(hive, key) as k:
                parts += winreg.QueryValueEx(k, "Path")[0].split(";")
        os.environ["PATH"] = os.pathsep.join(dict.fromkeys(os.environ.get("PATH", "").split(os.pathsep) + parts))
    except OSError:
        pass


def install_system_tool(tool: str, hint: str, platform: str | None = None, wait: float = 180, sleep=time.sleep) -> bool:
    """Install a missing system tool through the stored rights, with no question. `hint` is the OS install command
    from `doctor.system_tool_hint`. True when the tool is on PATH afterwards. A per-user command (curl | sh, pipx, npm
    -g) runs as it is: it needs no rights."""
    p = platform or sys.platform
    if not hint:
        return False
    log.info("installs %s through the stored rights: %s", tool, hint)
    print(f"install {tool}: {hint}")
    if hint.startswith("winget "):
        m = re.search(r"--id\s+(\S+)", hint)
        if not m or not WINGET_ID.match(m.group(1)) or have_rights(p) != "task":
            return False
        q = queue_path()
        q.parent.mkdir(parents=True, exist_ok=True)
        with open(q, "a", encoding="utf-8") as fh:
            fh.write(m.group(1) + "\n")
        if run_proc(["schtasks", "/Run", "/TN", TASK], timeout=30).rc != 0:
            return False
        end = time.monotonic() + wait
        while time.monotonic() < end:  # the task runs on its own; wait until the tool appears
            _refresh_path()
            if shutil.which(tool):
                return True
            sleep(5)
        return bool(shutil.which(tool))
    if hint.startswith("sudo "):
        if have_rights(p) != "sudoers":
            return False
        words = hint.split()
        pkgs = [w for w in words[3:] if APT_PKG.match(w)]  # "sudo apt install a b" -> a b
        if words[1:3] not in (["apt", "install"], ["apt-get", "install"], ["dnf", "install"]) or not pkgs:
            return False
        cmd = ["sudo", "-n", "/usr/bin/apt-get", "install", "-y", *pkgs]
        rc = run_proc(cmd, timeout=900).rc
        return rc == 0 and bool(shutil.which(tool))
    rc = run_proc(hint, shell=True, timeout=900).rc  # per-user: brew, pipx, npm -g, curl | sh
    _refresh_path()
    return rc == 0 and bool(shutil.which(tool))


def remove_rights(platform: str | None = None, run=run_proc) -> list[str]:
    """`ap uninstall --rights`: remove the task and the sudoers file. Returns the lines to show; a step that needs
    elevation itself prints the one command to run by hand."""
    p = platform or sys.platform
    out = []
    if p.startswith("win"):
        rc = run(["schtasks", "/Delete", "/TN", TASK, "/F"], timeout=30).rc
        d = win_dir()  # the task's script is writable by Administrators only, so the folder goes with the task
        try:
            if rc == 0 and d.exists():
                shutil.rmtree(d)
        except OSError:
            rc = 1
        out.append(f"removed scheduled task {TASK} and {d}" if rc == 0 else "run this in an administrator PowerShell: "
                   f"schtasks /Delete /TN {TASK} /F; Remove-Item -Recurse -Force '{d}'")
    elif p != "darwin":
        if have_rights(p) == "sudoers":
            rc = run(["sudo", "-n", "rm", "-f", SUDOERS], timeout=30).rc
            out.append(f"removed {SUDOERS}" if rc == 0 else f"run: sudo rm -f {SUDOERS}")
        else:
            out.append(f"no {SUDOERS}: nothing to remove")
    else:
        out.append("macOS: Autopilot took no rights (brew needs none)")
    return out


def describe(platform: str | None = None) -> str:
    """One doctor line: what was installed and how to undo it."""
    p = platform or sys.platform
    r = have_rights(p)
    if r == "task":
        return f"scheduled task {TASK} installs winget packages with no prompt; undo: `ap uninstall --rights`"
    if r == "sudoers":
        return f"{SUDOERS} lets apt-get, dpkg, snap and brew run with no password; undo: `ap uninstall --rights`"
    if r == "brew":
        return "none needed on macOS"
    return "none: a missing system tool stops the run with its install command (run the installer again to take them)"
