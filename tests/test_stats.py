"""M3: `autopilot stats`, the publishable numbers of a run."""
from autopilot.cli import main as cli_main
from autopilot.orchestrator import Orchestrator
from autopilot.report import proof_stats
from test_autopilot import FakeBackend, make_project, phases_basic

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


def test_stats_after_a_run(tmp_path, capsys):
    root = make_project(tmp_path, phases_basic()[:1], BASE)
    orch = Orchestrator(root, backend=FakeBackend({"P01-T01": ["break", "ok"]}), sleep=lambda s: None)
    orch.run()
    out = proof_stats(orch.cfg, orch.plan, orch.state)
    assert "| Tasks finished | 2 of 2 (100%) |" in out
    assert "| Passed the gate on the first try | 1 of 2 (50%) |" in out  # P01-T01 needed a retry
    assert "| Tasks stuck (blocked) | 0 |" in out and "| Owner: hours spent | (fill in) |" in out
    assert "Wall-clock" in out and out.rstrip().splitlines()[-1].startswith("Tokens:")
    assert cli_main(["stats", "-C", str(root)]) in (0, None) and "Tasks finished" in capsys.readouterr().out


def test_stats_before_any_run(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.reload_plan()
    out = proof_stats(orch.cfg, orch.plan, orch.state)
    assert "| Tasks finished | 0 of 3 (0%) |" in out and "| Agent sessions | 0 |" in out and "? |" in out


# ---- G3: the overnight digest: what is built, what is stuck, what needs the owner, about how much is left ----

class Timed(FakeBackend):
    """Every task session takes one minute of agent time."""

    def run(self, req):
        res = super().run(req)
        res.duration_ms = 60_000
        return res


def five():
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"t{i}", "risk": "low"} for i in range(1, 6)]}]


def test_digest_says_what_is_built_and_about_how_much_is_left(tmp_path):
    from autopilot.report import build_report, digest
    orch = Orchestrator(make_project(tmp_path, five(), BASE), backend=Timed(), sleep=lambda s: None, max_sessions=3)
    orch.run()  # stops at the session limit with two tasks to go
    text = digest(orch.cfg, orch.plan, orch.state)
    assert "Built: 3 tasks this run, 3 of 5 in total." in text
    assert "Left: 2 tasks, about 2 min and $0.50 at this run's pace." in text
    done = [e["message"] for e in orch.state.events(50) if e["kind"] == "run_done"]
    assert "Built: 3 tasks this run" in done[-1] and "Left: 2 tasks" in done[-1]  # the end-of-run message carries it
    assert "Built: 3 tasks this run" in build_report(orch.cfg, orch.plan, orch.state)


def test_digest_names_stuck_tasks_and_open_decisions_and_never_guesses_from_too_little(tmp_path):
    from autopilot.report import digest
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend({"P01-T01": ["blocked"]}),
                        sleep=lambda s: None)
    orch.run()
    text = digest(orch.cfg, orch.plan, orch.state)
    assert "Blocked: P01-T01." in text and "Needs you: D-001" in text
    assert "about" not in text  # fewer than three finished tasks: no estimate


def test_digest_of_a_finished_plan(tmp_path):
    from autopilot.report import digest
    orch = Orchestrator(make_project(tmp_path, phases_basic(), BASE), backend=FakeBackend(), sleep=lambda s: None)
    orch.run()
    text = digest(orch.cfg, orch.plan, orch.state)
    assert "Built: 3 tasks this run, 3 of 3 in total." in text and "Left: nothing." in text
    assert "Blocked" not in text and "Needs you" not in text and "Not verified" not in text


# ---- G11: the report says what no check covered ----

def test_digest_and_report_say_what_is_not_verified(tmp_path):
    from autopilot.report import build_report, digest
    plan = [{"id": "P01", "title": "One", "features": ["GET /items lists items"], "tasks": [
        {"id": "P01-T01", "title": "a", "risk": "low", "files_in_scope": ["lib/**"]},  # the fake agent writes in src/
        {"id": "P01-T02", "title": "b", "risk": "low"}]}]
    root = make_project(tmp_path, plan, {**BASE, "functional": {"enabled": False}})  # no check: the feature stays open
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch.run()
    line = "Not verified: 1 task merged with gate warnings, 1 feature not checked."
    assert line in digest(orch.cfg, orch.plan, orch.state)
    assert f"- {line}" in build_report(orch.cfg, orch.plan, orch.state)


# ---- I1: what sessions load from the owner's Claude config ----
import json  # noqa: E402

from autopilot.backends.claude_cli import config_load  # noqa: E402
from autopilot.report import build_report  # noqa: E402

SECRET = "C:/Users/me/.claude/plugins/secret-path"
INIT = {"type": "system", "subtype": "init",
        "plugins": [{"name": "alpha", "path": SECRET, "source": "x", "version": "9.9.9"}, {"name": "beta", "path": SECRET}],
        "mcp_servers": [{"name": "m1", "status": "connected", "source": SECRET}, {"name": "m2", "status": "failed"}]}
HOOK = {"type": "system", "subtype": "hook_started", "hook_name": "SessionStart:startup", "hook_event": "SessionStart"}
STREAM = "\n".join(json.dumps(e) for e in (INIT, HOOK, {**HOOK, "hook_event": "Stop"}))


def test_config_load_reads_names_and_counts_only():
    got = config_load(STREAM)
    assert got == {"plugins": ["alpha", "beta"], "mcp": {"connected": 1, "other": 1}, "mcp_names": ["m1", "m2"], "hooks": 1}
    assert SECRET not in json.dumps(got) and "9.9.9" not in json.dumps(got)


def test_config_load_says_nothing_when_the_cli_does_not():
    assert config_load("") == {} and config_load("not json") == {}
    assert config_load(json.dumps({"type": "system", "subtype": "init", "session_id": "s"})) == {}
    junk = {"type": "system", "subtype": "init", "plugins": "x", "mcp_servers": [1, None, {"name": "m", "status": 3}]}
    assert config_load(json.dumps(junk)) == {"plugins": [], "mcp": {"connected": 0, "other": 1}, "mcp_names": ["m"],
                                             "hooks": 0}


class Configured(FakeBackend):
    def run(self, req):
        res = super().run(req)
        res.config = config_load(STREAM)
        return res


LINE = "Sessions load from your Claude config: 2 plugins, 2 MCP servers (1 connected), 1 startup hooks"


def test_report_and_doctor_show_the_config_a_session_loaded(tmp_path):
    from autopilot.config import Config
    from autopilot.doctor import checks
    root = make_project(tmp_path, phases_basic()[:1], BASE)
    orch = Orchestrator(root, backend=Configured(), sleep=lambda s: None)
    orch.run()
    report = build_report(orch.cfg, orch.plan, orch.state)
    assert f"- {LINE}" in report and SECRET not in report
    rows = {n: d for _, n, d in checks(Config.load(root))}
    assert rows["claude config"] == LINE + " (from the last session)"
    (tmp_path / "b").mkdir()
    plain = Orchestrator(make_project(tmp_path / "b", phases_basic()[:1], BASE), backend=FakeBackend(), sleep=lambda s: None)
    plain.run()
    assert "Sessions load from" not in build_report(plain.cfg, plain.plan, plain.state)
    assert "claude config" not in {n for _, n, _ in checks(Config.load(tmp_path / "b"))}
