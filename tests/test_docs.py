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


# W9: proof.svg and BADGE.md written next to PHASE.md when a phase closes
import xml.etree.ElementTree as ET  # noqa: E402

from autopilot.docs import today  # noqa: E402
from autopilot.state import State  # noqa: E402


def close_phase(tmp_path, phase_title="Proof card"):
    plan = Plan.from_dict({"goal": "g", "phases": [{"id": "P09", "title": phase_title, "tasks": [
        {"id": "P09-T01", "title": "a", "acceptance_criteria": []},
        {"id": "P09-T02", "title": "b", "acceptance_criteria": []}],
        "features": [{"id": "F1", "journey": "j"}, {"id": "F2", "journey": "k"}]}]})
    cfg = Config(tmp_path, {})
    st = State(tmp_path / "state.db")
    st.sync_plan(plan)
    st.set_task("P09-T01", status="done")
    st.set_task("P09-T02", status="blocked")
    st.set_meta("features", {"F1": {"passes": True}, "F2": {"passes": False}})
    sid = st.start_session("build", "P09-T01", "P09", 1, "m")
    st.end_session(sid, cost=1.5, ok=True)
    Documenter(cfg).phase_done(plan.phases[0], st, "done")
    folder = tmp_path / ".agent" / "history" / "P09"
    return folder, (folder / "proof.svg").read_text(encoding="utf-8")


def test_phase_close_writes_a_parseable_card_with_counts_cost_and_date(tmp_path):
    folder, svg = close_phase(tmp_path)
    assert (folder / "PHASE.md").exists()
    ET.fromstring(svg)  # raises when the XML is not valid
    assert "tasks merged 1 of 2" in svg
    assert "verified 1" in svg
    assert "cost $1.50" in svg
    assert today() in svg
    assert str(tmp_path) not in svg
    assert tmp_path.as_posix() not in svg


def test_a_title_with_angle_bracket_and_ampersand_still_parses(tmp_path):
    _, svg = close_phase(tmp_path, phase_title="Build & <ship>")
    root = ET.fromstring(svg)
    texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert "P09 Build & <ship>" in texts


def test_badge_md_has_one_markdown_image_line_pointing_at_proof_svg(tmp_path):
    folder, _ = close_phase(tmp_path)
    badge = (folder / "BADGE.md").read_text(encoding="utf-8")
    image_lines = [ln for ln in badge.splitlines() if ln.startswith("![")]
    assert image_lines == ["![Built by Autopilot](proof.svg)"]
    assert badge.count("![") == 1
    assert ".agent/history/P09/proof.svg" in badge
