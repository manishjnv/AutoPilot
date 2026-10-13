"""W20: the phase docs session result must pass the project test command before it is committed to main."""
import re
from pathlib import Path

from autopilot.orchestrator import Orchestrator
from test_autopilot import TEST_CMD, FakeBackend, make_project

PLAN = [{"id": "P01", "title": "One", "features": [{"id": "P01-F01", "title": "Check a file", "journey": "run check"}],
         "tasks": [{"id": "P01-T01", "title": "a", "risk": "low"}]}]
README_CMD = ("python -c \"import pathlib,sys; f=pathlib.Path('README.md'); ok=not f.exists() or 'TOO LONG' not in f.read_text(encoding='utf-8'); "
              "print('' if ok else 'FAILED tests/test_readme.py::test_word_budget'); sys.exit(0 if ok else 1)\"")


class LongReadme(FakeBackend):
    def _docs(self, cwd, prompt):
        res = super()._docs(cwd, prompt)
        with (cwd / "README.md").open("a", encoding="utf-8") as f:
            f.write("TOO LONG\n")
        return res


def run(tmp_path, fake, tests):
    root = make_project(tmp_path, PLAN, {"profile": "lean", "decide": {"enabled": False}, "docs": {"session": True},
                                         "commands": {"test": tests, "lint": [TEST_CMD] if not tests else []}})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    return root, orch


def test_red_tests_drop_the_docs_result(tmp_path):
    root, orch = run(tmp_path, LongReadme(), [TEST_CMD, README_CMD])
    assert "[autopilot] docs for phase" not in orch.git.run("log", "--format=%s")
    assert not (root / "README.md").exists() or "TOO LONG" not in (root / "README.md").read_text(encoding="utf-8")
    assert orch.git.is_clean()
    assert any(e["kind"] == "docs" and "tests: FAILED tests/test_readme.py::test_word_budget" in e["message"]
               for e in orch.state.events(50))


def test_green_tests_commit_the_docs_result(tmp_path):
    root, orch = run(tmp_path, FakeBackend(), [TEST_CMD, README_CMD])
    assert "[autopilot] docs for phase P01" in orch.git.run("log", "--format=%s")
    assert orch.git.is_clean()


def test_no_test_command_commits_as_before(tmp_path):
    root, orch = run(tmp_path, LongReadme(), [])
    assert "[autopilot] docs for phase P01" in orch.git.run("log", "--format=%s")
    assert "TOO LONG" in (root / "README.md").read_text(encoding="utf-8")


def test_prompt_states_the_readme_cap():
    root = Path(__file__).resolve().parent.parent
    cap = re.search(r"<= (\d+)", (root / "tests" / "test_opening.py").read_text(encoding="utf-8")).group(1)
    assert cap in (root / "autopilot" / "prompts" / "docs.md").read_text(encoding="utf-8")
