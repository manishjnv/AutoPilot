import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("premerge", Path(__file__).resolve().parent.parent / "scripts" / "premerge.py")
pm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pm)


def fake(red=()):
    calls = []

    def run(argv):
        calls.append(argv)
        if argv[:2] == ["git", "diff"]:
            return 0, "tests/test_a.py\nREADME.md\n"
        if argv[:2] == ["wsl", "wslpath"]:
            return 0, "/mnt/e/x\n"
        if argv[:2] == ["git", "branch"]:
            return 0, "br\n"
        return (1, "boom") if any(r in " ".join(argv) for r in red) else (0, "")
    return run, calls


def test_windows_plan_uses_wsl_then_host_tests():
    s = pm.plan(True, "/mnt/e/x", ["tests/test_a.py"], False, "br", "py")
    assert s[0][1][:3] == ["wsl", "-e", "sh"] and "cd /mnt/e/x && python3 -m pytest -q -n auto" in s[0][1][-1]
    assert s[1][1] == ["py", "-m", "pytest", "-q", "tests/test_a.py"]


def test_linux_plan_runs_pytest_directly():
    s = pm.plan(False, "", [], False, "br", "py")
    assert s == [("suite", ["py", "-m", "pytest", "-q", "-n", "auto"])]


def test_red_step_exits_1_and_green_exits_0():
    run, _ = fake(red=("-n auto",))
    assert pm.main([], run, windows=False) == 1
    run, _ = fake()
    assert pm.main([], run, windows=False) == 0


def test_no_gh_without_ci_flag():
    run, calls = fake()
    pm.main([], run, windows=True)
    assert not any(c[0] == "gh" for c in calls)
    assert any(c[0] == "wsl" for c in calls)
    assert pm.plan(False, "", [], True, "br")[-1][1][:3] == ["gh", "workflow", "run"]
