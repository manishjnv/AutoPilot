"""Release bump in two safe steps (run from the repo root, on main):

    python scripts/bump.py X.Y.Z          # writes the version, commits, PUSHES main (no tag yet)
    python scripts/bump.py X.Y.Z --tag    # when CI is green on that commit: tags vX.Y.Z and pushes the tag

Writes the version in four places, moves Unreleased under the new header, sets MIN_VERSION in both install
scripts. The tag step refuses while CI on HEAD is missing, running or red, so a release never ships untested
(RCA 2026-10-12: v0.4.0 and v0.5.0 were both tagged before CI ran on the bump commit, and both needed a fix).
Commits and tags carry the GitHub noreply identity (never `git config`).
"""
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autopilot.github_util import identity_env  # noqa: E402

GIT = ["git", "-c", "core.filemode=false"]  # a Windows checkout must not stage mode-only changes


def sub(path, pattern, repl):
    p = Path(path)
    if p.exists():
        p.write_text(re.sub(pattern, lambda m: repl, p.read_text(encoding="utf-8"), count=1, flags=re.M),
                     encoding="utf-8", newline="")


def git(*args, **kw):
    kw.setdefault("timeout", 300)
    return subprocess.run([*GIT, *args], check=True, env={**os.environ, **identity_env()}, **kw)


def head():
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=300).stdout.strip()


def has_origin() -> bool:
    """A repository without `origin` (a test fixture, a plain clone) bumps and tags locally; the guard needs a remote."""
    return subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=300).returncode == 0


def ci_state(sha) -> str:
    """'success', 'failure', 'pending' or 'none' for the CI workflow on this commit (needs gh)."""
    p = subprocess.run(["gh", "run", "list", "--commit", sha, "--workflow", "CI", "--json", "status,conclusion",
                        "--limit", "1"], capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        sys.exit("gh run list failed; is gh logged in?\n" + p.stderr)
    runs = json.loads(p.stdout or "[]")
    if not runs:
        return "none"
    r = runs[0]
    return "pending" if r["status"] != "completed" else ("success" if r["conclusion"] == "success" else "failure")


LEAD = "**In plain words:**"
MAX_WORDS = 25  # same limit as .vale/styles/Autopilot/SentenceLength.yml


def unreleased(text):
    m = re.search(r"^## \[Unreleased\]\n(.*?)(?=^## \[|\Z)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


def long_sentences(block):
    """Sentences over MAX_WORDS words in the bullet lines of a changelog block."""
    out = []
    for line in block.splitlines():
        if line.lstrip().startswith(("- ", "* ")):
            out += [s for s in re.split(r"(?<=[.!?])\s+", line.lstrip()[2:]) if len(s.split()) > MAX_WORDS]
    return out


def check_notes(text):
    """Release-notes rule (W49): the Unreleased block opens with the plain-words lead; every sentence is short."""
    block = unreleased(text)
    if not block.strip().startswith(LEAD):
        sys.exit(f"release notes rule: the [Unreleased] block of CHANGELOG.md must start with a line that begins {LEAD}")
    bad = long_sentences(block)
    if bad:
        sys.exit(f"release notes rule: a CHANGELOG sentence is over {MAX_WORDS} words: {bad[0][:80]}... ({len(bad)} found)")


def bump(ver):
    check_notes(Path("CHANGELOG.md").read_text(encoding="utf-8"))
    sub("pyproject.toml", r'^version = ".*"', f'version = "{ver}"')
    sub("plugin/.claude-plugin/plugin.json", r'"version": ".*?"', f'"version": "{ver}"')
    sub("autopilot/__init__.py", r'^__version__ = ".*"', f'__version__ = "{ver}"')
    sub("CHANGELOG.md", r"^## \[Unreleased\]\n", f"## [Unreleased]\n\n## [{ver}] - {datetime.date.today()}\n")
    sub("install.sh", r"^MIN_VERSION=.*", f"MIN_VERSION={ver}")  # T1: the script's own version; DEFAULT_REF stays main
    sub("install.ps1", r"^\$MinVersion = .*", f"$MinVersion = '{ver}'")
    git("add", "-u")
    git("commit", "-m", f"release: v{ver}")
    if not has_origin():
        print(f"bump commit {head()[:7]} made; no origin, nothing pushed. Tag with: python scripts/bump.py {ver} --tag")
        return
    git("push", "origin", "HEAD")
    print(f"pushed the bump commit {head()[:7]}. When CI is green: python scripts/bump.py {ver} --tag")


def tag(ver):
    sha = head()
    if has_origin():
        state = ci_state(sha)
        if state != "success":
            sys.exit(f"CI on {sha[:7]} is {state}; tag only on green. Check: gh run list --commit {sha}")
    git("tag", "-a", f"v{ver}", "-m", f"v{ver}")
    if not has_origin():
        print(f"tagged v{ver} on {sha[:7]}; no origin, nothing pushed")
        return
    git("push", "origin", f"v{ver}")
    print(f"tagged v{ver} on {sha[:7]} and pushed; the Release workflow publishes it")


def main(argv):
    if len(argv) not in (1, 2) or not re.fullmatch(r"\d+\.\d+\.\d+", argv[0]) or (len(argv) == 2 and argv[1] != "--tag"):
        sys.exit(__doc__)
    if subprocess.run([*GIT, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=300).stdout.strip() \
            and len(argv) == 1:
        sys.exit("the working tree has changes; commit or stash them first")
    (tag if len(argv) == 2 else bump)(argv[0])


if __name__ == "__main__":
    main(sys.argv[1:])
