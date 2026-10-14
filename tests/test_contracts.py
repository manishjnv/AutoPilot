"""W36: feature contracts in features/, given to the tasks whose files_in_scope touch them."""
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from autopilot.config import Config
from autopilot.context import ContextBuilder
from autopilot.contracts import (HEADING, SECTIONS, added_duplicates, contract_problems, contracts_block, contracts_for,
                                 named, sections)
from autopilot.gate import task_gate
from autopilot.gitops import Git
from autopilot.orchestrator import Orchestrator
from autopilot.plan import Plan
from test_autopilot import FakeBackend, make_project
from test_routing import Recorder

REPO = Path(__file__).resolve().parents[1]
PAGES = ["gate.md", "watch-screen.md"]


def task_prompt(tmp_path, scope):
    root = make_project(tmp_path, [{"id": "P01", "title": "One", "tasks": [
        {"id": "P01-T01", "title": "t", "files_in_scope": scope}]}])
    shutil.copytree(REPO / "features", root / "features")
    orch = Orchestrator(root, backend=Recorder(), sleep=lambda s: None)
    plan = Plan.load(orch.ad / "plan.yaml")
    return ContextBuilder(orch.cfg, plan, orch.state).task_prompt(plan.all_tasks()[0], 1, None)


def test_a_task_scoped_to_dash_term_gets_the_watch_contract(tmp_path):
    pages = contracts_for(REPO, ["autopilot/dash_term.py"])
    assert len(pages) == 1 and pages[0].startswith("# Feature contract: the watch screen")
    assert contracts_for(REPO, [r"autopilot\dash_term.py", "autopilot/gate.py"])[1].startswith(
        "# Feature contract: the watch screen")  # Windows separators and a second page, in file name order
    prompt = task_prompt(tmp_path, ["autopilot/dash_term.py"])
    assert HEADING in prompt and "the watch screen" in prompt and "the gate" not in prompt.split(HEADING)[1][:200]


def test_a_task_scoped_to_plan_py_gets_no_contract(tmp_path):
    assert contracts_for(REPO, ["autopilot/plan.py"]) == []
    assert contracts_block(REPO, ["autopilot/plan.py"]) == ""
    assert contracts_for(tmp_path, ["autopilot/dash_term.py"]) == []  # no features/ folder
    assert HEADING not in task_prompt(tmp_path, ["autopilot/plan.py"])


def test_a_glob_scope_matches_and_the_block_is_capped():
    assert len(contracts_for(REPO, ["autopilot/*.py"])) == 2
    block = contracts_block(REPO, ["autopilot/*.py"], cap=500)
    assert block.startswith(HEADING) and len(block) < 500 + len(HEADING) + 60


def test_both_committed_pages_parse_and_name_real_tests():
    for name in PAGES:
        text = (REPO / "features" / name).read_text(encoding="utf-8")
        assert all(s in sections(text) and sections(text)[s].strip() for s in SECTIONS), name
        assert all((REPO / f).is_file() for f in named(text, "Files")), name
        tests = named(text, "Tests that guard it")
        assert tests, name
        for node in tests:
            path, test = node.split("::")
            source = (REPO / path).read_text(encoding="utf-8")
            assert re.search(rf"^def {re.escape(test)}\(", source, re.M), node
        assert re.search(r"^- \d{4}-\d{2}-\d{2}: ", sections(text)["Changes"], re.M), name


# ---- W36b: the gate guards the contract's tests; the docs session edits sections in place
GUARDED = "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n"
PAGE = ("# Feature contract: x\n\n## Files\n\n- `src/x.py`\n\n## Tests that guard it\n\n- `tests/test_x.py::test_b`\n\n"
        "## Changes\n\n- 2026-10-01: first contract.\n")


def sh(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def put(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def repo(tmp_path):
    sh(tmp_path, "init", "-q")
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("core.autocrlf", "false")):
        sh(tmp_path, "config", k, v)
    put(tmp_path, "tests/test_x.py", GUARDED)
    put(tmp_path, "features/x.md", PAGE)
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-qm", "init")
    return tmp_path


def gate(repo, report=None, allow=True):
    cfg = Config.load(repo)
    cfg.data["commands"]["test"] = [f'"{sys.executable}" -c "pass"']
    task = SimpleNamespace(allow_no_changes=False, allow_test_changes=allow, files_in_scope=["**"], verify=[])
    return task_gate(cfg, Git(repo), task, report=report)


def test_deleting_a_contract_test_fails_the_gate_without_a_reason(repo):
    put(repo, "tests/test_x.py", "def test_a():\n    assert 1\n\n\ndef test_c():\n    assert 3\n")  # count kept
    g = gate(repo)
    assert not g.ok and "contract x: test test_b removed" in g.problems  # even with allow_test_changes
    for report in ({}, {"contracts": [{"id": "x", "status": "kept"}]},
                   {"contracts": [{"id": "x", "status": "changed", "why": "  "}]}):
        assert "contract x: test test_b removed" in gate(repo, report).problems
    assert contract_problems(None, Git(repo), None) == ["contract x: test test_b removed"]


def test_a_changed_contract_with_a_reason_passes(repo):
    put(repo, "tests/test_x.py", "def test_a():\n    assert 1\n")
    assert "contract x: test count dropped in tests/test_x.py: 2 -> 1" in gate(repo).problems
    why = {"contracts": [{"id": "features/x.md", "status": "changed", "why": "test_b moved into test_a"}]}
    g = gate(repo, why)
    assert g.ok and not any(p.startswith("contract") for p in g.problems)


def test_renaming_a_guarded_test_file_does_not_hide_a_removed_test(repo):
    sh(repo, "mv", "tests/test_x.py", "tests/test_y.py")
    put(repo, "tests/test_y.py", "def test_a():\n    assert 1\n")
    assert "contract x: test test_b removed" in contract_problems(None, Git(repo), {})


def test_a_contract_page_edit_needs_a_new_dated_line(repo):
    put(repo, "features/x.md", PAGE.replace("- `src/x.py`", "- `src/x.py`\n- `src/y.py`"))
    msg = "contract x: page changed without a new dated line under ## Changes"
    assert msg in gate(repo, {"contracts": [{"id": "x", "status": "changed", "why": "w"}]}).problems
    put(repo, "features/x.md", PAGE + "- 2026-10-14: test_b guards the new rule.\n")
    assert gate(repo).ok
    (repo / "features/x.md").unlink()
    assert "contract x: page deleted" in gate(repo).problems
    assert gate(repo, {"contracts": [{"id": "x", "status": "changed", "why": "feature removed"}]}).ok


def test_added_duplicates_counts_only_new_top_headings():
    assert added_duplicates("# T\n## Safety\n", "# T\n## Safety\ntext\n##  safety \n") == ["## Safety"]
    assert added_duplicates("## A\n## A\n", "## A\n## A\n") == []  # already there
    assert added_duplicates("", "### Usage\n### Usage\n```\n## Safety\n## Safety\n```\n") == []  # sub-headings, code


class DuplicateHeading(FakeBackend):
    def _docs(self, cwd, prompt):
        res = super()._docs(cwd, prompt)
        with (cwd / "README.md").open("a", encoding="utf-8") as f:
            f.write("\n## Safety\n\nOne.\n\n## Safety\n\nTwo.\n")
        return res


def test_a_docs_result_with_a_duplicate_heading_is_dropped_with_the_reason(tmp_path):
    root = make_project(tmp_path, [{"id": "P01", "title": "One", "features": [
        {"id": "P01-F01", "title": "Check a file", "journey": "run check"}], "tasks": [
        {"id": "P01-T01", "title": "a", "risk": "low"}]}], {"profile": "lean", "decide": {"enabled": False},
                                                             "docs": {"session": True}})
    orch = Orchestrator(root, backend=DuplicateHeading(), sleep=lambda s: None)
    orch.run()
    assert "[autopilot] docs for phase" not in orch.git.run("log", "--format=%s")
    assert any(e["kind"] == "docs" and "result dropped (duplicate heading in README.md: ## Safety)" in e["message"]
               for e in orch.state.events(50))
    assert orch.git.is_clean()


def test_docs_prompt_says_edit_the_existing_section():
    text = (REPO / "autopilot" / "prompts" / "docs.md").read_text(encoding="utf-8")
    assert "find the section that already covers the change and edit it there" in text
    assert "Never add a second section on the same topic" in text


def test_a_glob_in_the_contract_files_list_matches_a_literal_scope(tmp_path):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "g.md").write_text("# G\n\n## Files\n\n- `autopilot/dash_*.py`\n", encoding="utf-8")
    assert len(contracts_for(tmp_path, ["autopilot/dash_term.py"])) == 1
    assert contracts_for(tmp_path, ["autopilot/gate.py"]) == []
