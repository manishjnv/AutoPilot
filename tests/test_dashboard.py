"""J9: the data of the dashboard: one plain dict for the browser page and the terminal window."""
import json

from autopilot.dashboard import dashboard_data, live_rows
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project, phases_basic

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


def built(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.run()
    return orch


def test_data_is_plain_and_has_every_part(tmp_path):
    orch = built(tmp_path)
    data = dashboard_data(orch.cfg, orch.plan, orch.state, {})
    json.dumps(data)  # only plain types: a view never needs the plan or the state
    assert set(data) == {"project", "progress", "tasks", "live", "usage", "files", "health", "next", "line",
                         "needs_you", "blocked_why", "size", "phases", "recent"}
    assert data["phases"][0] == {"id": "P01", "title": data["phases"][0]["title"], "total": 2, "done": 2, "status": "done"}
    assert len(data["recent"]) == 3 and {"n", "title", "time"} == set(data["recent"][0])
    assert data["project"]["status"] == "idle" and data["project"]["state_words"] == "No build is active."
    assert data["progress"] == {"done": 3, "total": 3, "pct": 100, "phases_done": 2, "phases_total": 2,
                                "blocked": 0, "questions": 0, "warnings": 0, "warned": [], "working": 0, "waiting": 0,
                                "active": 0}
    assert data["project"]["now"] is None and data["project"]["tone"] == "" and data["needs_you"] == []
    assert [t["status"] for t in data["tasks"]] == ["done"] * 3 and data["tasks"][0]["n"] == 1
    assert data["files"] is None and data["usage"]["context"] is None


def test_a_running_build_marks_its_task_and_its_context(tmp_path):
    orch = built(tmp_path)
    orch.state.set_task("P02-T01", status="pending")
    run = {"status": "running", "state": "Code", "task": "P02-T01", "attempt": 2, "model": "claude-haiku-4-5",
           "started_at": "2026-10-03T10:00:00", "context_tokens": 68000, "git": "OK", "build": "OK"}
    data = dashboard_data(orch.cfg, orch.plan, orch.state, run)
    assert data["project"]["status"] == "running" and data["project"]["state_words"] == "Writes the code."
    assert data["project"]["model"] == "Haiku" and data["project"]["attempt"] == 2
    assert [t["status"] for t in data["tasks"]] == ["done", "done", "running"]
    assert data["usage"]["context"] == 0.34 and data["health"] == {"git": "OK", "checks": "OK", "words": ""}
    assert data["project"]["now"]["n"] == 3 and data["project"]["now"]["attempt"] == 2  # J10: what it does now
    assert data["project"]["tone"] == "good" and data["progress"]["active"] == 3 and data["progress"]["working"] == 1
    assert data["project"]["branch"] == orch.cfg.get("main_branch", "main")  # never the task branch
    red = dashboard_data(orch.cfg, orch.plan, orch.state, {**run, "build": "Red", "state": "Block", "task": ""})
    assert red["health"]["words"] == "The checks fail on main." and red["project"]["tone"] == "wait"
    assert red["project"]["now"] is None
    assert set(data["files"]) == {"added", "modified", "deleted"}
    done = dashboard_data(orch.cfg, orch.plan, orch.state, {"status": "finished", "outcome": "plan complete"})
    assert done["project"]["status"] == "finished" and done["project"]["state_words"] == "The build is complete."


def test_live_rows_have_a_kind(tmp_path):
    orch = built(tmp_path)
    log = orch.cfg.root / ".agent" / "logs" / "autopilot.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("2026-10-03 18:07:35 INFO   ▸ P01-T01 a [haiku] · Write /x/x.py; Bash pytest -q · 0m17s\n"
                   "2026-10-03 18:09:00 INFO task P01-T01 attempt 1 failed: tests\n"
                   "2026-10-03 18:10:00 INFO task P01-T01 done (haiku, $0.45)\n", encoding="utf-8")
    rows = live_rows(orch.cfg.root, orch.plan)
    assert [r["kind"] for r in rows] == ["blank", "heading", "step", "bad", "good"]
    assert rows[1] == {"at": "", "text": "Task 1 of 3: a", "kind": "heading"}
    assert rows[2] == {"at": "18:07", "text": "Writes x.py. Runs the tests.", "kind": "step"}


def test_size_counts_code_tests_and_docs(tmp_path):
    import subprocess

    from autopilot.dashboard import project_size
    files = (("src/app.py", "a = 1\nb = 2\n"),
             ("tests/test_app.py", "def test_a():\n    pass\n\ndef test_b():\n    pass\n"),
             ("README.md", "# x\n"), (".agent/plan.yaml", "x: 1\n"), ("logo.png", "binary"))
    for rel, text in files:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    assert project_size(tmp_path) == {"code": 2, "tests": 5, "docs": 1, "test_count": 2}  # .agent/ and images: not counted


def test_an_open_question_and_a_blocked_task_are_named(tmp_path):
    orch = built(tmp_path)
    orch.state.set_task("P02-T01", status="blocked", last_error="PROBLEM: the tests fail on Windows. More text.")
    orch.state.add_decision(kind="blocked", task_id="P02-T01", title="P02-T01 the tests fail", question="What now?",
                            status="OPEN")
    data = dashboard_data(orch.cfg, orch.plan, orch.state, {})
    assert data["blocked_why"] == {"id": "P02-T01", "why": "the tests fail on Windows. More text."}
    assert data["needs_you"] == [{"id": data["needs_you"][0]["id"], "title": "P02-T01 the tests fail"}]
    assert data["progress"]["blocked"] == 1 and data["progress"]["questions"] == 1
