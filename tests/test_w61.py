"""W61: spend every bar: a step up needs room (1), the task must fit the login (2), free CLIs run the side sessions
(3), a limit answer marks the model out (4), the review follows the tier (5), subagents on haiku (6), the same gate
failure twice parks the task (7)."""
import time

import yaml

from autopilot import usage
from autopilot.backends import SessionResult, limit_model
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator, first_failure
from test_autopilot import FakeBackend, make_project
from test_window import Metered, run, tasks

TWO = "/logins/two"
FALLBACK = {"agent": {"fallback": [{"claude_cli": {"CLAUDE_CONFIG_DIR": TWO}}]}}


def sub(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return d


def figs_by_login(table, now):
    """A fake usage.figures: `table[folder] = (five, week, models)`."""
    def figures(state, cfg=None, acct="default", **kw):
        five, week, models = table.get("" if acct == "default" else acct, (0.1, 0.1, {}))
        return {"five_hour": {"pct": five, "reset": now + 3600}, "seven_day": {"pct": week, "reset": now + 86400},
                "models": {k: {"pct": v, "reset": now + 86400} for k, v in models.items()}, "surfaces": {},
                "source": "live", "check": False}
    return figures


# ---------- rule 1: a step up needs room ----------
def test_a_step_up_without_room_is_held_on_the_current_model(tmp_path, monkeypatch):
    now = time.time()
    monkeypatch.setattr(usage, "figures", figs_by_login({"": (0.4, 0.96, {"opus": 0.6})}, now))
    orch, _, _ = run(tmp_path, tasks(1, "high"), {}, Metered([0.2]))
    assert orch.model_for("high", 1, -1, prev="sonnet") == "sonnet"  # the ladder says opus; the week bar is at 96%
    assert orch.state.get_meta("usage_why") == "opus held, week 96%"
    assert orch.model_for("high", 1, -1, prev="") == "opus"  # a first attempt is not a step up
    assert usage.step_up_room({"five_hour": {"pct": 0.97, "reset": 1}, "models": {}}, "opus") == "5h 97%"
    assert usage.step_up_room({"models": {"opus": {"pct": 0.95, "reset": 1}}}, "opus") == "opus week 95%"
    assert usage.step_up_room({"models": {"opus": {"pct": 0.5, "reset": 1}}, "seven_day": {"pct": 0.5, "reset": 1}}, "opus") == ""


def test_a_step_up_moves_to_a_login_where_the_model_has_room(tmp_path, monkeypatch):
    now = time.time()
    monkeypatch.setattr(usage, "figures", figs_by_login({"": (0.4, 0.96, {}), TWO: (0.1, 0.2, {})}, now))
    orch, _, _ = run(tmp_path, tasks(1, "high"), FALLBACK, Metered([0.2]))
    assert orch.model_for("high", 1, -1, prev="sonnet") == "opus"
    assert orch.state.get_meta("active_account") == TWO
    msgs = [e["message"] for e in orch.state.events(100) if e["kind"] == "source"]
    assert msgs and msgs[-1].startswith("default -> two (limit: opus has room on login two)")


# ---------- rule 2: the task must fit the room ----------
def test_expected_share_is_the_p75_over_the_window_and_the_planner_moves_a_task_that_does_not_fit():
    assert usage.expected_share([1.0, 2.0, 3.0, 4.0], 20.0) == 0.15  # p75 of four values = the third (index round(2.25))
    assert usage.expected_share([], 20.0) == 0.0 and usage.expected_share([5.0], 0.0) == 0.0
    assert usage.expected_share([30.0], 20.0) == 1.0  # capped at the whole window
    now = 1_800_000_000.0
    rows = [{"name": "login:default", "kind": "login", "folder": "", "room": 0.08, "five": 0.92, "week": 0.5, "resets": now + 100,
             "week_resets": now + 5 * 86400, "expires": 0, "usd": 0, "can_run": True, "off": False, "note": ""},
            {"name": "login:two", "kind": "login", "folder": TWO, "room": 0.7, "five": 0.3, "week": 0.2, "resets": now + 100,
             "week_resets": now + 5 * 86400, "expires": 0, "usd": 0, "can_run": True, "off": False, "note": ""}]
    pick = usage.plan_source(rows, "login:default", 50, need=0.12, now=lambda: now)
    assert pick == {"source": "login:two", "reason": "limit", "text": "task needs ~12%, 8% left"}
    assert usage.plan_source(rows, "login:default", 50, need=0.05, now=lambda: now) == {}  # it fits: stay
    rows[1]["five"] = 0.95  # nowhere fits: no move, the room floor decides as before
    assert usage.plan_source(rows, "login:default", 50, need=0.12, now=lambda: now) == {}


# ---------- rule 3: free CLIs run the side sessions ----------
def test_docs_session_runs_on_the_cli_preset_and_falls_back_once_to_claude(tmp_path, monkeypatch):
    from test_docs_session import PLAN
    fake = FakeBackend()
    root = make_project(tmp_path, PLAN, {"profile": "lean", "decide": {"enabled": False}, "docs": {"session": True},
                                         "models": {"docs": "gemini:flash"}})
    cli_calls = []

    def cli_run(self, preset, req):
        cli_calls.append((preset, req.model))
        return SessionResult(ok=False, error="gemini: not on PATH")
    monkeypatch.setattr(Orchestrator, "_cli_run", cli_run)
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    docs = [c for c in fake.calls if c[0] == "docs"]
    assert cli_calls == [("gemini", "flash")] * 2 and len(docs) == 2  # each phase: the CLI failed, then Claude once
    assert orch.state.get_meta("cli_sessions") == {"docs": {"run": 2, "fallback": 2}}
    assert [r["model"] for r in orch.state.db.execute("SELECT model FROM sessions WHERE kind='docs'").fetchall()] == ["flash", "flash"]
    from autopilot.report import build_report
    assert "Free CLI side sessions: docs 2 (2 fell back to Claude)" in build_report(orch.cfg, orch.plan, orch.state)


def test_a_good_cli_answer_needs_no_claude_session(tmp_path, monkeypatch):
    from test_docs_session import PLAN
    fake, side = FakeBackend(), FakeBackend()
    root = make_project(tmp_path, PLAN, {"profile": "lean", "decide": {"enabled": False}, "docs": {"session": True},
                                         "models": {"docs": "gemini:flash"}})
    monkeypatch.setattr(Orchestrator, "_cli_run", lambda self, preset, req: side.run(req))
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    assert not [c for c in fake.calls if c[0] == "docs"] and len([c for c in side.calls if c[0] == "docs"]) == 2
    assert orch.state.get_meta("cli_sessions") == {"docs": {"run": 2, "fallback": 0}}


def test_a_cli_preset_is_refused_for_a_load_bearing_role(tmp_path):
    root = make_project(tmp_path, tasks(1), {"models": {"review": "codex:gpt-5"}})
    errs = Config.load(root).validate()
    assert any("models.review: a CLI preset" in e for e in errs)
    root2 = make_project(sub(tmp_path, "b"), tasks(1), {"models": {"docs": "codex:gpt-5"}})
    assert not any("CLI preset" in e for e in Config.load(root2).validate())


# ---------- rule 4: a limit answer marks the model out ----------
def test_a_limit_answer_marks_the_model_out_until_its_reset_or_ten_minutes():
    assert limit_model("Opus not available until Thu 21:30") == "opus"
    assert limit_model("You have hit the Sonnet weekly limit") == "sonnet"
    assert limit_model("Claude AI usage limit reached|1760000000") == "" and limit_model("") == ""

    class St:
        def __init__(self):
            self.meta = {}

        def get_meta(self, k, d=None):
            return self.meta.get(k, d)

        def set_meta(self, k, v):
            self.meta[k] = v
    st, now = St(), 1000.0
    assert usage.mark_out(st, "Opus", 5000.0, now=lambda: now) == 5000.0
    assert usage.mark_out(st, "sonnet", 0.0, "/two", now=lambda: now) == 1600.0  # no time: a 10-minute cooldown
    empty = lambda *a, **k: {}  # noqa: E731
    figs = usage.figures(st, None, "default", now=lambda: now, live_fetch=empty)
    assert figs["models"]["opus"] == {"pct": 1.0, "reset": 5000.0} and usage.out_until(figs, "opus") == 5000.0
    # a live bar older than the mark keeps it; a newer live bar with room clears it
    live_old = {"five_hour": {"pct": 0.1, "reset": 9000.0}, "models": {"opus": {"pct": 0.2, "reset": 9000.0}}, "at": 500.0}
    st.meta["usage_live"] = {"at": now, "bars": live_old}
    assert usage.figures(st, None, "default", now=lambda: now, live_fetch=empty)["models"]["opus"]["pct"] == 1.0
    now = 1100.0
    live_new = {**live_old, "at": 1090.0}
    st.meta["usage_live"] = {"at": 500.0, "bars": {}}  # stale row: the fetch runs and returns the newer bars
    figs = usage.figures(st, None, "default", now=lambda: now, live_fetch=lambda *a, **k: live_new)
    assert figs["models"]["opus"]["pct"] == 0.2 and "opus" not in st.meta["usage_out"]
    now = 2000.0
    assert "sonnet" not in usage.figures(st, None, "/two", now=lambda: now, live_fetch=empty)["models"]  # cooldown over


def test_the_next_attempt_skips_a_model_marked_out(tmp_path, monkeypatch):
    now = time.time()
    monkeypatch.setattr(usage, "fetch", lambda *a, **k: {})
    orch, _, _ = run(tmp_path, tasks(1, "high"), {}, Metered([0.2]))
    usage.mark_out(orch.state, "opus", now + 3600)
    assert orch.model_for("high", 1) == "sonnet" and orch.state.get_meta("usage_why").startswith("opus is out until")


# ---------- rule 5: the review follows the tier ----------
def test_review_model_and_effort_follow_the_tier_map(tmp_path):
    cfg = {"models": {"review": {"medium": "sonnet", "high": "opus", "critical": "opus"}},
           "review": {"effort": {"medium": "medium", "high": "high"}}}
    orch, _, _ = run(tmp_path, tasks(1), cfg, Metered([0.2]))
    assert orch.tier_value("models.review", "medium", "opus") == "sonnet"
    assert orch.tier_value("models.review", "low", "opus") == "opus"  # a tier the map does not name: the default
    assert orch.tier_value("review.effort", "critical", "high") == "high"
    orch2, _, _ = run(sub(tmp_path, "b"), tasks(1), {}, Metered([0.2]))
    assert orch2.tier_value("models.review", "medium", "opus") == "opus"  # one name = every tier
    root = make_project(sub(tmp_path, "c"), tasks(1), {"models": {"review": {"medium": "sonnet", "huge": "opus"}}})
    assert any("models.review map keys must be risk tiers" in e for e in Config.load(root).validate())


# ---------- rule 6: subagents on haiku ----------
def test_the_template_sets_the_subagent_model_and_the_backend_passes_it(tmp_path):
    from pathlib import Path

    from autopilot.backends.claude_cli import ClaudeCLIBackend
    tpl = yaml.safe_load(Path("autopilot/templates/agent/project.yaml").read_text(encoding="utf-8"))
    assert tpl["models"]["subagent"] == "haiku"
    root = make_project(tmp_path, tasks(1), {"models": {"subagent": "haiku"}})
    assert ClaudeCLIBackend(Config.load(root)).env()["CLAUDE_CODE_SUBAGENT_MODEL"] == "haiku"


# ---------- rule 7: the same gate failure twice parks the task ----------
def test_first_failure_picks_the_failing_line():
    assert first_failure("PROBLEM: tests failed (exit 1)\nFAILED tests/test_a.py::test_x - assert 1 == 2\n") == "PROBLEM: tests failed (exit 1)"
    assert first_failure("ran 3 tests\nFAILED tests/test_a.py::test_x\n") == "FAILED tests/test_a.py::test_x"
    assert first_failure("") == "" and first_failure("just a line\n") == "just a line"


def test_the_same_gate_failure_twice_parks_instead_of_a_third_attempt(tmp_path):
    fake = FakeBackend(behaviours={"P01-T01": ["break", "break", "ok"]})
    root = make_project(tmp_path, tasks(1), {"decide": {"enabled": False}, "unstick": {"enabled": False}})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    row = orch.state.task("P01-T01")
    assert row["status"] == "blocked" and row["attempts"] == 2 and "NOT PROVEN: same failure twice" in row["last_error"]
    assert orch.state.db.execute("SELECT COUNT(*) FROM sessions WHERE kind='task'").fetchone()[0] == 2  # no third attempt on opus
    assert any("same failure twice" in e["message"] for e in orch.state.events(100) if e["kind"] == "task_blocked")
