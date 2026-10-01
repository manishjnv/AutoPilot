"""Wave 4: token ledger, token footer, claude_cli usage parsing."""
import re
import sqlite3

from autopilot.orchestrator import Orchestrator
from autopilot.report import build_report, token_footer
from autopilot.state import State
from test_autopilot import FakeBackend, make_project, phases_basic
from test_backend import run_stub

NO_AUDIT = {"audit": {"completion_audit": False}}
NO_DECIDE = {"decide": {"enabled": False}}  # these tests pin exact session totals


def u(i, o, r=0, w=0, cost=0.0):
    return {"input": i, "output": o, "cache_read": r, "cache_write": w, "cost": cost}


class UsageBackend(FakeBackend):
    """FakeBackend that reports tokens: sonnet for tasks, opus for audits and repairs."""

    def run(self, req):
        res = super().run(req)
        if self.calls[-1][0] in ("audit", "fixer", "unstick"):
            res.usage = {"claude-opus": u(100, 20000, cost=0.5)}
        else:
            res.usage = {"claude-sonnet": u(1000, 500, cost=0.25)}
        res.num_turns, res.duration_ms = 3, 1500
        return res


def test_cli_parses_model_usage_for_two_models(tmp_path, monkeypatch):
    mu = {"claude-sonnet-x": {"inputTokens": 10, "outputTokens": 20, "cacheReadInputTokens": 30,
                              "cacheCreationInputTokens": 40, "costUSD": 0.5},
          "claude-haiku-x": {"inputTokens": 1, "outputTokens": 2, "costUSD": 0.01}}
    res = run_stub(tmp_path, monkeypatch, f"print(json.dumps({{'result': 'ok', 'modelUsage': {mu!r}, "
                                          "'num_turns': 4, 'duration_ms': 900, 'total_cost_usd': 0.51}))\n")
    assert res.ok and res.num_turns == 4 and res.duration_ms == 900
    assert res.usage["claude-sonnet-x"] == u(10, 20, 30, 40, 0.5)
    assert res.usage["claude-haiku-x"] == u(1, 2, 0, 0, 0.01)


def test_cli_falls_back_to_plain_usage_and_never_raises(tmp_path, monkeypatch):
    res = run_stub(tmp_path, monkeypatch,
                   "print(json.dumps({'result': 'ok', 'total_cost_usd': 0.2, 'usage': {'input_tokens': 5, "
                   "'output_tokens': 6, 'cache_read_input_tokens': 7, 'cache_creation_input_tokens': 8}}))\n")
    assert res.usage == {"sonnet": u(5, 6, 7, 8, 0.2)}
    odd = run_stub(tmp_path, monkeypatch, "print(json.dumps({'result': 'ok', 'modelUsage': {'m': 'junk'}, "
                                          "'usage': 'x', 'num_turns': 'many'}))\n")
    assert odd.ok and odd.usage == {} and odd.num_turns == 0


def test_old_database_without_new_columns_still_opens(tmp_path):
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, task_id TEXT, phase TEXT, "
                "attempt INTEGER, model TEXT, started_at TEXT, ended_at TEXT, cost REAL DEFAULT 0, ok INTEGER, "
                "claude_session_id TEXT, summary TEXT, error TEXT, log_path TEXT)")
    con.execute("INSERT INTO sessions(kind, model, started_at) VALUES('task', 'sonnet', '2026-01-01T00:00:00')")
    con.commit()
    con.close()
    st = State(db)
    sid = st.start_session("task", "T1", "P1", 1, "sonnet")
    st.end_session(sid, cost=1.0, ok=True, usage={"m": u(1, 2, 3, 4, 1.0)}, num_turns=2, duration_ms=5)
    assert st.token_totals("model") == [("m", {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4,
                                               "total": 10, "cost": 1.0})]
    assert st.session_count() == 2
    State(db).close()  # reopening an already migrated database is fine


def test_token_totals_by_model_kind_after_a_fake_run(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_DECIDE)
    orch = Orchestrator(root, backend=UsageBackend(), sleep=lambda s: None)
    assert orch.run() == "app complete"
    models = orch.state.token_totals("model")
    assert [m for m, _ in models] == ["claude-opus", "claude-sonnet"]  # biggest first
    assert dict(models)["claude-sonnet"]["total"] == 3 * 1500 and dict(models)["claude-opus"]["total"] == 20100
    kinds = dict(orch.state.token_totals("kind"))
    assert kinds["task"]["total"] == 4500 and kinds["audit"]["total"] == 20100
    assert dict(orch.state.token_totals("task"))["P01-T01"]["total"] == 1500
    assert sum(v["total"] for _, v in orch.state.token_totals("day")) == 24600
    assert orch.state.token_totals("model", since_session=orch.state.next_session_id()) == []
    assert orch.state.recent_sessions(1)[0]["num_turns"] == 3


def test_report_tokens_section_footer_and_verification_share(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_DECIDE)
    orch = Orchestrator(root, backend=UsageBackend(), sleep=lambda s: None)
    orch.run()
    report = (root / ".agent" / "REPORT.md").read_text(encoding="utf-8")
    assert "## Tokens" in report and "| claude-opus |" in report and "| audit |" in report
    assert "Verification share is above 20%: checks are using more than intended." in report
    footer = token_footer(orch.state)
    m = re.fullmatch(r"Tokens: [\d.]+k total — claude-opus \S+ (\d+)% · claude-sonnet \S+ (\d+)% · verification (\d+)%", footer)
    assert m, footer
    assert 98 <= int(m[1]) + int(m[2]) <= 102 and int(m[3]) == 82
    assert build_report(orch.cfg, orch.plan, orch.state).count("## Tokens") == 1


def test_no_verification_warning_when_checks_are_cheap(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    orch = Orchestrator(root, backend=UsageBackend(), sleep=lambda s: None)
    orch.run()
    report = (root / ".agent" / "REPORT.md").read_text(encoding="utf-8")
    assert "## Tokens" in report and "Verification share is above 20%" not in report
    assert token_footer(orch.state).endswith("verification 0%")


def test_run_done_notification_carries_the_footer(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    orch = Orchestrator(root, backend=UsageBackend(), sleep=lambda s: None)
    orch.run()
    done = [e["message"] for e in orch.state.events(50) if e["kind"] == "run_done"]
    assert done and "Tokens: " in done[0] and "claude-sonnet" in done[0]
