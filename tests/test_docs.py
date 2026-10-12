"""W3: PROOF.md ends its header with a `## Not proven` section."""
from autopilot.config import Config
from autopilot.docs import NOTHING_OPEN, Documenter
from autopilot.plan import Plan


def setup(tmp_path, criteria, test_text, cmds=("pytest",)):
    plan = Plan.from_dict({"goal": "g", "phases": [{"id": "P01", "title": "p", "tasks": [
        {"id": "P01-T01", "title": "a", "acceptance_criteria": criteria}]}]})
    cfg = Config(tmp_path, {"commands": {"test": list(cmds)}})
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(test_text, encoding="utf-8")
    hist = tmp_path / ".agent" / "history" / "P01"
    hist.mkdir(parents=True)
    (hist / "P01-T01.md").write_text("# P01-T01\n\n## Files changed\n- tests/test_a.py\n- a.py\n\n## Tests added\n",
                                     encoding="utf-8")
    doc = Documenter(cfg)
    doc.proof(plan.phases[0], {})
    return doc.proof_path("P01").read_text(encoding="utf-8")


def test_a_criterion_without_a_test_is_listed_with_its_task_id(tmp_path):
    proof = setup(tmp_path, ["The report lists every open item", "Exports a signed receipt file"],
                  "def test_x():\n    # the report lists every open item\n    pass\n")
    assert "## Not proven" in proof
    assert "- Criterion without a test, P01-T01: Exports a signed receipt file" in proof
    assert "every open item" not in proof.partition("## Not proven")[2]
    assert NOTHING_OPEN not in proof


def test_a_fully_tested_phase_prints_the_one_sentence(tmp_path):
    proof = setup(tmp_path, ["The report lists every open item"], "# the report lists every open item\n")
    assert proof.partition("## Not proven")[2].strip() == NOTHING_OPEN


def test_a_task_without_any_check_command_is_listed(tmp_path):
    proof = setup(tmp_path, [], "", cmds=())
    assert "- P01-T01: no verify command and no test command" in proof
