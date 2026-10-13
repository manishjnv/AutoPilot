"""W36: feature contracts in features/, given to the tasks whose files_in_scope touch them."""
import re
import shutil
from pathlib import Path

from autopilot.context import ContextBuilder
from autopilot.contracts import HEADING, SECTIONS, contracts_block, contracts_for, named, sections
from autopilot.orchestrator import Orchestrator
from autopilot.plan import Plan
from test_autopilot import make_project
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
