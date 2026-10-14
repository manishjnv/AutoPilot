"""W28: a second Claude login (another CLAUDE_CONFIG_DIR) as the fallback at a usage limit (fake runners only)."""
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
