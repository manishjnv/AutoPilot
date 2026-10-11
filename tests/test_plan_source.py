"""N13: an item added to the plan document becomes a task at the next start; an unchanged document costs no session."""
from pathlib import Path

import yaml

from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}
ROADMAP = "# Roadmap\n\n- N1 first\n- N2 second\n- N3 third\n"


class Planner(FakeBackend):
    """The replanner adds N4 and N5 and renames the pending N3, as the diff says."""

    def __init__(self):
        super().__init__()
        self.replans = []

    def run(self, req):
        if "replan remaining work" not in req.prompt:
            return super().run(req)
        self.replans.append(req.prompt)
        p = Path(req.cwd) / ".agent" / "plan.yaml"
        plan = yaml.safe_load(p.read_text(encoding="utf-8"))
        tasks = plan["phases"][0]["tasks"]
        tasks[2]["title"] = "third renamed"
        tasks += [{"id": "N4", "title": "fourth"}, {"id": "N5", "title": "fifth"}]
        p.write_text(yaml.safe_dump(plan), encoding="utf-8")
        return SessionResult(ok=True, report={"summary": "synced", "added": ["N4", "N5"], "changed": ["N3"]})


def test_new_roadmap_items_become_tasks_and_a_second_start_costs_nothing(tmp_path):
    tasks = [{"id": f"N{i}", "title": t, **({"status": "done"} if i < 3 else {})}
             for i, t in ((1, "first"), (2, "second"), (3, "third"))]
    root = make_project(tmp_path, [{"id": "P01", "title": "One", "tasks": tasks}], BASE)
    plan = root / ".agent" / "plan.yaml"
    plan.write_text(plan.read_text(encoding="utf-8") + "plan_source: ROADMAP.md\n", encoding="utf-8")
    (root / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    (root / ".agent" / "plan_source.txt").write_text(ROADMAP, encoding="utf-8")  # what `onboard --plan-doc` leaves
    fake = Planner()

    (root / "ROADMAP.md").write_text(ROADMAP.replace("third", "third renamed") + "- N4 fourth\n- N5 fifth\n",
                                     encoding="utf-8")
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert len(fake.replans) == 1 and "+- N4 fourth" in fake.replans[0] and "+- N3 third renamed" in fake.replans[0]
    st = orch.state.status_map()
    assert sorted(st) == ["N1", "N2", "N3", "N4", "N5"] and all(v == "done" for v in st.values())
    assert orch.plan.task_by_id["N3"].title == "third renamed"
    assert yaml.safe_load(plan.read_text(encoding="utf-8"))["plan_source"] == "ROADMAP.md"

    assert Orchestrator(root, backend=fake, sleep=lambda s: None).run() == "plan complete"
    assert len(fake.replans) == 1  # no edit, no session
