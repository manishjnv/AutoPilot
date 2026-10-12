"""Release bump: python scripts/bump.py X.Y.Z (run from the repo root).

Writes the version in four places, moves Unreleased under the new header,
sets MIN_VERSION in both install scripts, makes one commit and one tag vX.Y.Z.
"""
import datetime
import re
import subprocess
import sys
from pathlib import Path


def sub(path, pattern, repl):
    p = Path(path)
    if p.exists():
        p.write_text(re.sub(pattern, lambda m: repl, p.read_text(encoding="utf-8"), count=1, flags=re.M),
                     encoding="utf-8", newline="")


def main(ver):
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        sys.exit("version must look like X.Y.Z")
    sub("pyproject.toml", r'^version = ".*"', f'version = "{ver}"')
    sub("plugin/.claude-plugin/plugin.json", r'"version": ".*?"', f'"version": "{ver}"')
    sub("autopilot/__init__.py", r'^__version__ = ".*"', f'__version__ = "{ver}"')
    sub("CHANGELOG.md", r"^## \[Unreleased\]\n", f"## [Unreleased]\n\n## [{ver}] - {datetime.date.today()}\n")
    sub("install.sh", r"^MIN_VERSION=.*", f"MIN_VERSION={ver}")  # T1: the script's own version; DEFAULT_REF stays main
    sub("install.ps1", r"^\$MinVersion = .*", f"$MinVersion = '{ver}'")
    for cmd in (["add", "-u"], ["commit", "-m", f"release: v{ver}"], ["tag", f"v{ver}"]):
        subprocess.run(["git", *cmd], check=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else sys.exit(__doc__))
