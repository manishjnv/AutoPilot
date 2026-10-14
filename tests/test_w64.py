"""W64: the API credit runs low and medium tasks through the Cline CLI preset, not through a new backend."""
import json
import os
import sys

from autopilot import usage
from autopilot.backends import SessionRequest, get_backend
from autopilot.backends.command import DEFAULT_MODEL_MAP, PRESETS, _cline_stream, command_template, model_flag
from test_presets import cfg_with
from test_usage import Cfg, FakeState

RUN_RESULT = {"ts": "2026-10-15T00:00:00Z", "type": "run_result", "finishReason": "completed", "iterations": 1,
              "usage": {"inputTokens": 5523, "outputTokens": 100, "totalCost": 0.000843775},
              "aggregateUsage": {"inputTokens": 5523, "outputTokens": 100, "totalCost": 0.000843775},
              "text": "Submission recorded: done.\n\n```json\n{\"status\": \"done\", \"summary\": \"ok\"}\n```",
              "model": {"id": "claude-haiku-5-5", "provider": "anthropic"}}


def fake_cline(tmp_path, monkeypatch):
    """A stand-in `cline` that prints the JSON event stream of CLI 3.0.71 (shape recorded live 2026-10-15)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "fake.py").write_text(
        "import json,sys\nprompt = sys.stdin.read()\n"
        "print(json.dumps({'type': 'agent_event', 'event': {'type': 'content_start', 'argv': sys.argv[1:], 'stdin': prompt}}))\n"
        f"print(json.dumps({json.dumps(RUN_RESULT)}))\n")
    if sys.platform == "win32":
        (bindir / "cline.cmd").write_text(f'@"{sys.executable}" "%~dp0fake.py" %*\n')
    else:
        exe = bindir / "cline"
        exe.write_text(f"#!{sys.executable}\n" + (bindir / "fake.py").read_text())
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))


def test_the_cline_preset_runs_with_the_json_stream_and_reports_the_cost(tmp_path, monkeypatch):
    fake_cline(tmp_path, monkeypatch)
    cfg = cfg_with(tmp_path, {"preset": "cline"})
    tpl = command_template(cfg)
    assert tpl.startswith("cline -y --json -P anthropic") and "{model_flag}" in tpl and "standard input" in tpl
    assert model_flag(cfg, "haiku") == " -m claude-haiku-5-5" and DEFAULT_MODEL_MAP["cline"]["sonnet"] == "claude-sonnet-5-5"
    res = get_backend(cfg).run(SessionRequest(prompt="build the login page", model="haiku", cwd=str(tmp_path), system_append="CTX"))
    assert res.ok and res.report == {"status": "done", "summary": "ok"} and res.cost == 0.000843775
    assert res.text.startswith("Submission recorded")  # the final text, not the raw stream
    assert "cline" in PRESETS and set(PRESETS) >= {"codex", "gemini", "copilot", "cline"}


def test_cline_stream_parsing_handles_errors_and_plain_text():
    out = json.dumps({"type": "error", "message": "JSON output mode requires a prompt argument or piped stdin"}) + "\n"
    assert _cline_stream(out) == ("", 0.0, "JSON output mode requires a prompt argument or piped stdin")
    assert _cline_stream("plain text\n```json\n{\"status\": \"done\"}\n```") == ("plain text\n```json\n{\"status\": \"done\"}\n```", 0.0, "")
    text, cost, err = _cline_stream(json.dumps(RUN_RESULT))
    assert cost == 0.000843775 and "status" in text and err == ""


def test_the_api_source_runs_only_with_the_cline_fallback_and_a_credit(monkeypatch):
    monkeypatch.setattr(usage, "figures", lambda state, cfg=None, acct="default", **kw: {"five_hour": {"pct": 0.2, "reset": 2e9},
                                                                                        "seven_day": {"pct": 0.2, "reset": 2e9}, "models": {}})
    credit = {"usage.api_credit": {"usd": 109, "entered": "2026-10-14", "expires": "2026-12-01"}}
    rows = {r["name"]: r for r in usage.sources(Cfg({**credit, "agent.fallback": ["cline"]}), FakeState())}
    assert rows["api"]["can_run"] is True and rows["api"]["note"] == "low and medium tasks through cline"
    rows = {r["name"]: r for r in usage.sources(Cfg(credit), FakeState())}
    assert rows["api"]["can_run"] is False and rows["api"]["note"].startswith("needs backend")
    rows = {r["name"]: r for r in usage.sources(Cfg({"agent.fallback": ["cline"]}), FakeState())}
    assert rows["api"]["can_run"] is False and rows["api"]["usd"] == 0.0
    assert usage.api_runner(Cfg({"agent.fallback": ["cline", {"claude_cli": {"CLAUDE_CONFIG_DIR": "/x"}}]})) == "cline"


def test_the_planner_picks_the_api_credit_for_low_and_medium_tasks_only():
    now = usage._day("2026-11-20")
    rows = [{"name": "login:default", "kind": "login", "folder": "", "room": 0.5, "five": 0.5, "week": 0.5, "resets": now + 100,
             "week_resets": now + 5 * 86400, "expires": 0.0, "usd": 0.0, "can_run": True, "off": False, "note": ""},
            {"name": "api", "kind": "api", "folder": "", "room": 1.0, "five": None, "week": None, "resets": 0.0, "week_resets": 0.0,
             "expires": usage._day("2026-12-01"), "usd": 109.0, "can_run": True, "off": False, "note": ""}]
    assert usage.plan_source(rows, "login:default", 50, risk="low", now=lambda: now)["source"] == "api"
    assert usage.plan_source(rows, "login:default", 50, risk="medium", now=lambda: now)["reason"] == "expires soon"
    assert usage.plan_source(rows, "login:default", 50, risk="high", now=lambda: now) == {}
    assert usage.plan_source(rows, "login:default", 50, risk="critical", now=lambda: now) == {}
    rows[1]["can_run"] = False
    assert usage.plan_source(rows, "login:default", 50, risk="low", now=lambda: now) == {}


def test_the_credit_counts_down_by_the_cline_sessions_since_the_entry():
    st = FakeState()
    cfg = Cfg({"usage.api_credit": {"usd": 109, "entered": "2026-10-14", "expires": "2026-12-01"}})
    usage.note_api_spend(st, cfg, 0.5)
    usage.note_api_spend(st, cfg, 0.25)
    assert st.get_meta("api_spent") == {"since": "2026-10-14", "usd": 0.75}
    assert usage.balances(cfg, st)["api"]["usd"] == 108.25 and usage.balances(cfg)["api"]["usd"] == 109.0
    cfg2 = Cfg({"usage.api_credit": {"usd": 50, "entered": "2026-11-01"}})  # a new entry resets the count
    assert usage.balances(cfg2, st)["api"]["usd"] == 50.0
    usage.note_api_spend(st, cfg2, 1.0)
    assert st.get_meta("api_spent") == {"since": "2026-11-01", "usd": 1.0}


def test_auto_mode_switches_a_low_task_to_cline_and_ap_source_api_works(tmp_path, monkeypatch):
    from argparse import Namespace

    from autopilot.cli import _open_state, cmd_source
    from autopilot.orchestrator import Orchestrator
    from test_autopilot import FakeBackend, make_project
    from test_handoff import PHASES
    now = usage._day("2026-11-20")
    monkeypatch.setattr(usage, "figures", lambda state, cfg=None, acct="default", **kw: {"five_hour": {"pct": 0.2, "reset": now + 3600},
                                                                                        "seven_day": {"pct": 0.2, "reset": now + 86400}, "models": {}, "source": "live"})
    root = make_project(tmp_path, PHASES, {"agent": {"fallback": ["cline"]}, "usage": {"switch": "auto", "api_credit": {"usd": 109, "entered": "2026-10-14", "expires": "2026-12-01"}}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch._now = lambda: now
    from types import SimpleNamespace
    task = SimpleNamespace(id="P01-T01", risk="low", files_in_scope=[], title="a")  # the plan loads at run(); the planner needs only the risk
    line = orch.plan_source(task)
    assert orch.state.get_meta("handoff_runner") == "cline" and line.startswith("suggest: switch to api (expires soon")
    msgs = [e["message"] for e in orch.state.events(50) if e["kind"] == "source"]
    assert msgs and msgs[-1].startswith("default -> api (expires soon: api credit $109 expires Dec 01)")
    # `ap source api` by hand
    orch.state.set_meta("handoff_runner", None)
    assert cmd_source(Namespace(path=str(root), name="api")) == 0
    _, _, state = _open_state(root)
    assert state.get_meta("handoff_runner") == "cline"
