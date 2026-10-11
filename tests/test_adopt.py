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
