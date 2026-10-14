"""W45: a default or a doc change runs the full tests, a doc change adds the doc tests; the review does not run the suite."""
from types import SimpleNamespace

from autopilot.config import Config
from autopilot.context import ContextBuilder
from autopilot.gate import changed_tests
from autopilot.orchestrator import review_tests
from autopilot.plan import Plan
from test_autopilot import make_project
from test_lean import PLAN

CMD = "python -m pytest -q"


def cfg_for(tmp_path):
    root = make_project(tmp_path, PLAN, {"profile": "lean", "commands": {"test": [CMD]}})
    (root / "tests").mkdir()
    (root / "tests" / "test_foo.py").write_text("")
    (root / "tests" / "test_readme_words.py").write_text("open('README.md')\n")
    (root / "tests" / "test_other.py").write_text("x = 1\n")
    return root, Config.load(root)


def test_default_paths_run_the_full_command(tmp_path):
    _, cfg = cfg_for(tmp_path)
    for f in ("autopilot/templates/agent/project.yaml", "autopilot/config.py", "autopilot/schemas.py", "autopilot/prompts/review.md"):
        assert changed_tests(cfg, CMD, [f, "autopilot/foo.py"]) == CMD


def test_a_code_file_runs_only_its_tests(tmp_path):
    _, cfg = cfg_for(tmp_path)
    assert changed_tests(cfg, CMD, ["autopilot/foo.py"]) == f"{CMD} tests/test_foo.py"


def test_a_doc_adds_the_tests_that_name_it(tmp_path):
    _, cfg = cfg_for(tmp_path)
    assert changed_tests(cfg, CMD, ["autopilot/foo.py", "README.md"]) == f"{CMD} tests/test_foo.py tests/test_readme_words.py"
    assert changed_tests(cfg, CMD, ["README.md"]) == f"{CMD} tests/test_readme_words.py"


def test_review_prompt_says_do_not_run_tests_and_holds_the_gate_block(tmp_path):
    root, _ = cfg_for(tmp_path)
    plan = Plan.load(root / ".agent" / "plan.yaml")
    ctx = ContextBuilder(Config.load(root), plan, None)
    gate = SimpleNamespace(results=[SimpleNamespace(cmd="pytest", rc=0, output="3 passed")])
    text = ctx.review_prompt(plan.phases[0].tasks[0], "+x") + review_tests(gate)
    assert "Do not run the test suite or any test command" in text and "## Test output" in text and "3 passed" in text


def test_a_hostile_file_name_is_quoted_in_the_test_command(tmp_path):
    import os
    import subprocess
    root, cfg = cfg_for(tmp_path)
    name = "tests/a$(touch MARK).py"
    out = changed_tests(cfg, CMD, [name])
    if os.name == "nt":  # cmd.exe cannot quote `(`: such a name drops out of the narrowed list, the full command runs
        assert out == CMD
        assert changed_tests(cfg, CMD, ["tests/a b.py"]) == f"{CMD} {subprocess.list2cmdline(['tests/a b.py'])}"
    else:
        assert out == f"{CMD} 'tests/a$(touch MARK).py'"
    if os.name != "nt":  # run the built string through a real shell: the name stays data
        subprocess.run(out.replace(CMD, "echo"), shell=True, cwd=root, check=True, capture_output=True)
        assert not (root / "MARK").exists()
    vit = changed_tests(cfg, "npx vitest run", ["src/a$(x).ts"])
    if os.name == "nt":
        assert vit == "npx vitest run"  # the only name is unsafe for cmd.exe: the full command runs
    else:
        assert vit.count("$(x)") == 1 and "'src/a$(x).ts'" in vit
