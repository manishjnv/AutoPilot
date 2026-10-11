"""J13 rows 15 and 16: a task's time counts every try, tasks + other = elapsed, and the ETA shows its basis."""
from autopilot.dashboard import dashboard_data
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project
from test_dashboard import BASE


def many(tmp_path, n=8):
    tasks = [{"id": f"T{i:02d}", "title": f"t{i}", "risk": "low"} for i in range(1, n + 1)]
    orch = Orchestrator(make_project(tmp_path, [{"id": "P01", "title": "One", "tasks": tasks}], BASE),
                        backend=FakeBackend(), sleep=lambda s: None)
    orch.reload_plan()
    return orch


def at(m):  # minute m of the run as an ISO time
    return f"2026-10-11T{10 + m // 60:02d}:{m % 60:02d}:00"


def session(orch, kind, tid, start, end):
    orch.state.db.execute("INSERT INTO sessions(kind, task_id, started_at, ended_at) VALUES(?,?,?,?)",
                          (kind, tid, at(start), at(end)))


def finish(orch, tid, start, end, tries=1):
    orch.state.set_task(tid, status="done", attempts=tries, started_at=at(start), finished_at=at(end))


def test_task_time_counts_every_try_and_tasks_plus_other_is_elapsed(tmp_path):
    orch = many(tmp_path, 3)
    # T01: a cut try at 0-5, a retry at 8-12, merged at 14 -> 14m; a research session (20-30) belongs to no task
    session(orch, "task", "T01", 0, 5)
    session(orch, "task", "T01", 8, 12)
    finish(orch, "T01", 8, 14, tries=2)
    session(orch, "research", None, 20, 30)
    session(orch, "task", "T02", 31, 40)
    finish(orch, "T02", 31, 44)
    run = {"status": "finished", "started_at": at(0), "updated_at": at(50)}
    data = dashboard_data(orch.cfg, orch.plan, orch.state, run)
    t = data["tasks"]
    assert t[0]["time"] == "14m" and t[0]["detail"].endswith("2 tries") and t[1]["time"] == "13m"
    s = data["project"]["time_secs"]
    assert s == {"tasks": 27 * 60, "other": 23 * 60, "elapsed": 50 * 60} and s["tasks"] + s["other"] == s["elapsed"]
    assert data["project"]["other"] == "23m"


def test_eta_shows_its_basis_and_waits_for_three_tasks(tmp_path):
    orch = many(tmp_path)
    live = {"status": "running", "state": "Code", "task": "", "started_at": at(0), "updated_at": at(60)}
    for i, (a, b) in enumerate([(0, 10), (10, 24), (24, 53)], 1):
        session(orch, "task", f"T{i:02d}", a, b)
        if i < 3:
            finish(orch, f"T{i:02d}", a, b)
    early = dashboard_data(orch.cfg, orch.plan, orch.state, live)
    assert early["project"]["eta"] == "after 3 tasks (2 done)"
    finish(orch, "T03", 24, 53)  # 10m, 14m, 29m -> median 14m, 5 left, parallel 1
    data = dashboard_data(orch.cfg, orch.plan, orch.state, live)
    assert data["project"]["eta"] == "~70m (5 × 14m)"
