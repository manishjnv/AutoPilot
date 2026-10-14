"""W28: a second Claude login (another CLAUDE_CONFIG_DIR) as the fallback at a usage limit (fake runners only)."""
import os
import time

from autopilot import handoff
from autopilot.backends import SessionResult
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project
from test_handoff import PHASES, Claude, build, tasks_of
from test_orchestrator import events


class Second(FakeBackend):
    """The same runner on the second folder: may be limited once itself; reports a usage window."""

    def __init__(self, wait=0):
        super().__init__()
        self.envs, self.wait, self.limited = [], wait, False

    def run(self, req):
        if self.wait and not self.limited and "implement task P01-T01" in req.prompt:
            self.limited = True
            return SessionResult(ok=False, error="limit", rate_limited=True, reset_at=time.time() + self.wait)
        res = super().run(req)
        res.window = {"five_hour": {"pct": 0.5, "reset": time.time() + 3600}}
        return res


def setup(tmp_path, monkeypatch, wait_a=7200, wait_b=0):
    folder = str(tmp_path / "claude-2")
    root = make_project(tmp_path, PHASES, {"agent": {"fallback": [{"claude_cli": {"CLAUDE_CONFIG_DIR": folder}}]}})
    second, sleeps = Second(wait_b), []

    def factory(cfg):
        second.envs.append(cfg.get("agent.env"))
        return second
    monkeypatch.setattr(handoff, "get_backend", factory)
    orch = Orchestrator(root, backend=Claude(wait_a), sleep=sleeps.append)
    return folder, orch, second, sleeps


def test_next_session_runs_on_the_second_folder(tmp_path, monkeypatch):
    folder, orch, second, _ = setup(tmp_path, monkeypatch)
    assert orch.run() == "app complete"
    assert second.envs[0] == {"CLAUDE_CONFIG_DIR": folder}
    assert tasks_of(second)[0] == "P01-T01"
    msg = events(orch, "handoff")[0]
    assert "usage limit on default" in msg and "next session on " + folder in msg


def test_window_state_is_per_folder(tmp_path, monkeypatch):
    folder, orch, _second, _ = setup(tmp_path, monkeypatch)
    orch.run()
    assert orch.state.get_meta("window_seen@" + folder)["five_hour"]["pct"] == 0.5
    assert not orch.state.get_meta("window_seen")  # the default folder keeps its own state
    assert orch.state.get_meta("window_start")  # learned from the first login's limit hit, under the default key
    assert orch.state.get_meta("window_start@" + folder) is None


def test_both_folders_limited_waits_for_the_earliest_reset(tmp_path, monkeypatch):
    _folder, orch, _second, sleeps = setup(tmp_path, monkeypatch, wait_a=7200, wait_b=10000)
    assert orch.run() == "app complete"
    assert any(7000 < s < 7400 for s in sleeps) and not any(s > 9000 for s in sleeps)


def test_plain_runner_name_still_works(tmp_path):
    root, orch, _claude, codex = build(tmp_path, 7200, ["codex"])
    assert orch.run() == "app complete"
    assert tasks_of(codex)[0] == "P01-T01" and "continues with codex" in events(orch, "handoff")[0]
    assert not [e for e in Config.load(root).validate() if "fallback" in e]


def test_bad_mapping_entry_is_refused(tmp_path):
    root = make_project(tmp_path, PHASES, {"agent": {"fallback": [{"claude_cli": {}}]}})
    assert any("agent.fallback" in e for e in Config.load(root).validate())


def test_window_sizes_are_learned_per_login(tmp_path, monkeypatch):  # W50
    folder, orch, _second, _ = setup(tmp_path, monkeypatch)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 60))
    for acct, cost in (("", 3.0), (folder, 5.0)):
        orch.state.db.execute("INSERT INTO sessions(kind, started_at, cost, account) VALUES('task', ?, ?, ?)",
                              (now, cost, acct))
    start = time.time() - 600
    assert orch._window_used(start) == 3.0  # the default login does not count the second login's session
    orch.state.set_meta("handoff_until", time.time() + 999)
    orch.state.set_meta("handoff_runner", {"claude_cli": {"CLAUDE_CONFIG_DIR": folder}})
    assert orch._window_used(start) == 5.0


def test_status_and_dashboard_follow_the_active_login(tmp_path, monkeypatch):  # W50
    from autopilot.dashboard import dashboard_data
    from autopilot.report import window_line
    folder, orch, _second, _ = setup(tmp_path, monkeypatch)
    orch.run()
    st = orch.state
    st.set_meta("window_seen", {"five_hour": {"pct": 0.2, "reset": time.time() + 3000}})
    st.set_meta(f"window_seen@{folder}", {"five_hour": {"pct": 0.5, "reset": time.time() + 3000}})
    st.set_meta("active_account", folder)
    line = window_line(st)
    assert "login: claude-2" in line and "50%" in line  # the second login's figures, not the default's 20%
    assert "login:" not in window_line(st, live=False) and "20%" in window_line(st, live=False)  # default login: old wording
    assert dashboard_data(orch.cfg, orch.plan, st, {})["project"]["account"] == "default"  # no run: default login
    run = {"status": "running", "pid": os.getpid()}
    data = dashboard_data(orch.cfg, orch.plan, st, run)
    assert data["project"]["account"] == "claude-2" and data["usage"]["five"] == 0.5


def test_old_database_gets_the_account_column(tmp_path):  # W50
    import sqlite3

    from autopilot.state import State
    p = tmp_path / "state.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, task_id TEXT, phase TEXT, "
                "attempt INTEGER, model TEXT, started_at TEXT, ended_at TEXT, cost REAL DEFAULT 0, ok INTEGER, "
                "claude_session_id TEXT, summary TEXT, error TEXT, log_path TEXT)")
    con.commit()
    con.close()
    st = State(p)
    assert "account" in {r["name"] for r in st.db.execute("PRAGMA table_info(sessions)")}
    sid = st.start_session("task", "T", "P", 1, "m", account="x")
    assert st.db.execute("SELECT account FROM sessions WHERE id=?", (sid,)).fetchone()[0] == "x"
