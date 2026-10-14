"""W51: `ap report --issue [--show]` builds a scrubbed issue from the last run. Opt-in; never prompts."""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
import os
import tempfile
from pathlib import Path

REPO = "manishjnv/AutoPilot"
COPY = f"gh is not logged in; copy the file into a new issue at https://github.com/{REPO}/issues/new"
_LEAK = re.compile(r"/home/|/Users/|/mnt/|/root/|/tmp/|/var/|/etc/|[A-Za-z]:[\\/]|\\\\|~|%|://|@|!\[|\]\(", re.I)  # paths, users, links


def build(root: Path) -> str:
    """The issue body: outcome, version, OS, runner, top unknown wordings, blocked tasks by cause, last 20 log lines."""
    from .. import AGENT_DIR, __version__, signals
    from ..report import run_journal
    run = run_journal(root)
    runner = "unknown"
    try:
        from ..config import Config
        cfg = Config.load(root)
        backend = str(cfg.get("agent.backend", "claude_cli"))
        runner = "claude" if backend == "claude_cli" else str(cfg.get("agent.preset") or "command")
    except Exception:  # a broken config still gives an issue
        pass
    unknown = signals.read_unknown() or []
    top = signals.tally(unknown, [])["unknown"][:5]
    ev = signals.read_events(root / AGENT_DIR / "state.db")
    parked = signals.tally_project(ev)["parked"] if ev else {}
    try:
        log = (root / AGENT_DIR / "logs" / "autopilot.log").read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
    except OSError:
        log = []
    out = [f"Outcome: {run.get('outcome') or 'unknown'}", f"Version: {__version__}",
           f"OS: {platform.system()} {platform.release()}", f"Runner: {runner}", "", "Top unknown wordings:"]
    out += [f"- {n}x {cause}: {text}" for n, cause, text in top] or ["- none"]
    out += ["", "Blocked tasks by cause:"] + ([f"- {c}: {n}" for c, n in sorted(parked.items())] or ["- none"])
    out += ["", "Last log lines:"] + log  # every line still passes redact and the _LEAK drop below
    body = signals.redact("\n".join(out))
    return "\n".join(ln for ln in body.splitlines() if not _LEAK.search(ln)) + "\n"


def cmd_issue(args) -> int:
    body = build(Path(getattr(args, "path", None) or ".").resolve())
    if getattr(args, "show", False):
        print(body, end="")
        return 0
    f = Path(tempfile.mkdtemp(prefix="ap-issue-")) / "issue.md"
    f.write_text(body, encoding="utf-8")
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"  # Windows: never a gh.exe planted in the checkout
    gh = shutil.which("gh")
    if gh and Path(gh).resolve().parent in (Path.cwd().resolve(), Path(getattr(args, "path", None) or ".").resolve()):
        gh = None
    try:
        ok = bool(gh) and subprocess.run([gh, "auth", "status"], capture_output=True, timeout=30).returncode == 0
        if ok:
            subprocess.run([gh, "issue", "create", "--repo", REPO, "--title", "Autopilot run report",
                            "--body-file", str(f)], check=True, timeout=60)
            return 0
    except (OSError, subprocess.SubprocessError):
        pass
    print(f"payload: {f}\n{COPY}")
    return 0
