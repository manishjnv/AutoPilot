"""N1: `status: done` in plan.yaml records work that exists before Autopilot."""
import pytest

from autopilot.plan import Plan, PlanError
from autopilot.state import State


def plan_of(statuses):
    tasks = [{"id": f"T{i}", "title": f"task {i}", **({"status": s} if s else {})} for i, s in enumerate(statuses, 1)]
    return Plan.from_dict({"goal": "g", "phases": [{"id": "P01", "title": "p", "tasks": tasks}]})


def test_done_tasks_are_done_and_next_ready_is_first_open(tmp_path):
    st = State(tmp_path / "state.db")
    plan = plan_of(["done"] * 6 + [None, None])
    st.sync_plan(plan)
    sm = st.status_map()
    assert [sm[f"T{i}"] for i in range(1, 7)] == ["done"] * 6
    assert sm["T7"] == sm["T8"] == "pending"
    assert plan.next_ready(sm).id == "T7"
    assert st.task("T1")["note"] == "done before Autopilot"


def test_other_status_value_fails_naming_the_task():
    with pytest.raises(PlanError) as e:
        plan_of([None, "blocked"])
    assert "T2" in str(e.value.errors) and "blocked" in str(e.value.errors)


@pytest.mark.parametrize("current", ["running", "blocked", "skipped"])
def test_existing_task_state_is_not_changed(tmp_path, current):
    st = State(tmp_path / "state.db")
    st.sync_plan(plan_of([None]))
    st.set_task("T1", status=current)
    st.sync_plan(plan_of(["done"]))
    assert st.status_map()["T1"] == current


def test_pending_row_becomes_done_and_removing_key_keeps_it(tmp_path):
    st = State(tmp_path / "state.db")
    st.sync_plan(plan_of([None]))
    st.sync_plan(plan_of(["done"]))
    assert st.status_map()["T1"] == "done"
    st.sync_plan(plan_of([None]))
    assert st.status_map()["T1"] == "done"


def test_plan_without_status_loads_as_before():
    assert plan_of([None]).task_by_id["T1"].status == ""


# N1: discovery pack
import subprocess
import sys

from autopilot.config import Config
from autopilot.context import PACK_CAP, discovery_pack


def _git(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _repo(tmp_path):
    for d in ("notes", ".cursor/rules", "node_modules/x", ".venv/lib"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "PLAN.md").write_text("# Plan\n- [x] login page\n- [ ] export csv\n", encoding="utf-8")
    (tmp_path / "notes/session-3.md").write_text("did things\n", encoding="utf-8")
    (tmp_path / ".cursor/rules/x.mdc").write_text("rule\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    (tmp_path / "node_modules/x/README.md").write_text("junk\n", encoding="utf-8")
    (tmp_path / ".venv/lib/NOTES.md").write_text("junk\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "a@example.com")
    _git(tmp_path, "config", "user.name", "dummy")
    for i, m in enumerate(["first change", "second change", "third change"]):
        (tmp_path / f"f{i}.txt").write_text(m, encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", m)


def _cfg(tmp_path, **test):
    return Config(tmp_path, {"commands": {"test": test.get("cmd", [])}, "onboard": {"test_timeout_sec": test.get("t", 300)}})


def test_pack_has_commits_paths_and_checkboxes(tmp_path):
    _repo(tmp_path)
    cmd = f'"{sys.executable}" -c "print(\'tests ok\')"'
    pack = discovery_pack(tmp_path, _cfg(tmp_path, cmd=[cmd]))
    for s in ("first change", "second change", "third change", "PLAN.md", "notes/session-3.md",
              ".cursor/rules/x.mdc", "pyproject.toml", "- [x] login page", "- [ ] export csv"):
        assert s in pack
    assert "node_modules" not in pack and ".venv" not in pack and ".git/" not in pack
    assert "exit code: 0" in pack and "tests ok" in pack


def test_hanging_test_command_is_stopped_and_reported(tmp_path):
    cmd = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    pack = discovery_pack(tmp_path, _cfg(tmp_path, cmd=[cmd], t=1))
    assert "timed out after 1 s" in pack


def test_not_a_git_repo_and_no_test_command(tmp_path):
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    pack = discovery_pack(tmp_path, _cfg(tmp_path))
    assert "## Git log" in pack and "(no git history)" in pack
    assert "no test command" in pack and "README.md" in pack


def test_pack_is_capped_and_marks_truncation(tmp_path):
    (tmp_path / "docs").mkdir()
    for i in range(1500):
        (tmp_path / "docs" / f"document-number-{i:05d}-with-a-long-name.md").write_text("x", encoding="utf-8")
    pack = discovery_pack(tmp_path, _cfg(tmp_path))
    assert len(pack) <= PACK_CAP + 200 and "truncated" in pack
