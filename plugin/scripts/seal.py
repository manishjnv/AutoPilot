"""W5: Stop hook. Refuses "done" while the project tests fail or a test file lost lines. Stdlib only."""
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Copy of autopilot.gate.TEST_GLOBS (a test pins them equal; the plugin must not import autopilot).
TEST_GLOBS = ["tests/**", "test/**", "**/tests/**", "**/test/**", "test_*.py", "*_test.py", "*_test.go", "*.test.*",
              "*.spec.*", "**/__tests__/**", "src/test/**"]
MAX_BLOCKS, TIMEOUT = 5, 300


def match(path, globs=TEST_GLOBS):
    return any(fnmatch.fnmatch(path if "/" in g else path.rsplit("/", 1)[-1], g) for g in globs)


def test_command(root):
    cfg = root / ".agent" / "project.yaml"
    if cfg.is_file():
        m = re.search(r"^commands:[ \t]*\n((?:[ \t]+.*\n?|[ \t]*\n)*)", cfg.read_text(encoding="utf-8", errors="replace"), re.M)
        t = re.search(r"^[ \t]+test:[ \t]*(.+?)[ \t]*$", m.group(1), re.M) if m else None
        if t:
            cmd = re.sub(r"[ \t]+#.*$", "", t.group(1)).strip()
            if len(cmd) > 1 and cmd[0] == cmd[-1] and cmd[0] in "'\"":
                cmd = cmd[1:-1]
            if cmd:
                return cmd
    if (root / "tests").is_dir():
        return "python -m pytest -q"
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            if json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}).get("test"):
                return "npm test"
        except (ValueError, OSError):
            pass
    return ""


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
    return r.stdout if r.returncode == 0 else None


def shrunk(root):
    for f in (git(root, "diff", "--name-only", "HEAD") or "").splitlines():
        f = f.strip()
        old = git(root, "show", f"HEAD:{f}") if f and match(f) else None
        p = root / f
        if old is None or not p.is_file():
            continue
        if len(p.read_text(encoding="utf-8", errors="replace").splitlines()) < len(old.splitlines()):
            return f
    return ""


def counter(session):
    return Path(tempfile.gettempdir()) / f"autopilot-seal-{re.sub(r'[^A-Za-z0-9_.-]', '_', session)}.count"


def reason(root, cmd):
    if cmd:
        try:
            r = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, timeout=TIMEOUT)
            if r.returncode != 0:
                return f"The test command failed: {cmd}. Fix the failing tests before you stop."
        except subprocess.TimeoutExpired:
            return f"The test command timed out after {TIMEOUT} seconds: {cmd}."
    f = shrunk(root)
    return f"The test file {f} has fewer lines than at HEAD. Restore the removed tests." if f else ""


def listed(root):
    """X1: only projects that Autopilot set up on this computer (`projects.txt`) may run a command."""
    f = Path(os.environ.get("AUTOPILOT_HOME") or Path.home() / ".autopilot") / "projects.txt"
    try:
        return str(root.resolve()) in f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    root = Path(data.get("cwd") or ".")
    if not listed(root):
        return 0
    cmd = test_command(root)
    if not cmd and not (root / ".git").exists():
        return 0
    why = reason(root, cmd)
    if not why:
        return 0
    c = counter(str(data.get("session_id") or "none"))
    try:
        n = int(c.read_text())
    except (OSError, ValueError):
        n = 0
    if n >= MAX_BLOCKS:
        return 0
    try:
        c.write_text(str(n + 1))
    except OSError:
        pass
    print(json.dumps({"decision": "block", "reason": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
