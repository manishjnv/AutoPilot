"""Run the suite on WSL (or Linux) and the host, then the changed tests on the host; --ci also runs the CI workflow.

Exit 1 on any red step. Steps come from the pure function `plan`; `run_steps` takes an injectable runner.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sh(argv):
    p = subprocess.run(argv, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout


def plan(windows, wsl_root, tests, ci, branch, py="python"):
    """Return [(name, argv)]. wsl_root is the WSL path of the repo (Windows only)."""
    if windows:
        steps = [("suite on WSL", ["wsl", "-e", "sh", "-c", f"cd {wsl_root} && python3 -m pytest -q -n auto"])]
    else:
        steps = [("suite", [py, "-m", "pytest", "-q", "-n", "auto"])]
    if tests:
        steps.append(("changed tests on the host", [py, "-m", "pytest", "-q", *tests]))
    if ci:
        steps.append(("dispatch CI", ["gh", "workflow", "run", "ci.yml", "--ref", branch]))
    return steps


def run_steps(steps, run=sh):
    red = 0
    for name, argv in steps:
        rc, out = run(argv)
        print(f"{'ok ' if rc == 0 else 'RED'} {name}")
        if rc:
            print("\n".join(out.splitlines()[-25:]))
            red = 1
    return red


def ci_result(branch, run=sh, wait=time.sleep):
    """Wait for the newest ci.yml run on the branch; print one line per job. Return 0 when all passed."""
    wait(5)  # ponytail: fixed pause for the dispatched run to appear
    rc, out = run(["gh", "run", "list", "--workflow", "ci.yml", "--branch", branch, "--limit", "1", "--json", "databaseId"])
    if rc or not json.loads(out or "[]"):
        print("RED CI run not found")
        return 1
    rid = str(json.loads(out)[0]["databaseId"])
    run(["gh", "run", "watch", rid, "--exit-status"])
    rc, out = run(["gh", "run", "view", rid, "--json", "jobs"])
    jobs = json.loads(out)["jobs"] if rc == 0 else []
    for j in jobs:
        print(f"{j['conclusion'] or j['status']:10} {j['name']}")
    return 0 if jobs and all(j["conclusion"] == "success" for j in jobs) else 1


def main(argv=None, run=sh, windows=None):
    argv = sys.argv[1:] if argv is None else argv
    ci = "--ci" in argv
    windows = sys.platform == "win32" if windows is None else windows
    wsl_root = run(["wsl", "wslpath", "-a", str(ROOT)])[1].strip() if windows else ""
    tests = [t for t in run(["git", "diff", "--name-only", "main...HEAD", "--", "tests"])[1].split() if t.endswith(".py")]
    branch = run(["git", "branch", "--show-current"])[1].strip()
    red = run_steps(plan(windows, wsl_root, tests, ci, branch, sys.executable), run)
    if ci and not red:
        red = ci_result(branch, run)
    return red


if __name__ == "__main__":
    sys.exit(main())
