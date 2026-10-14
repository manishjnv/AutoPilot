"""W59 core: the OAuth usage endpoint is parsed into plain bars, read at most once a minute per login, behind a kill
switch, and the token never leaves the request."""
import json
import time

from autopilot import usage

RESET_5H = "2026-10-14T20:20:00.355441+00:00"
RESET_7D = "2026-10-19T00:00:00.355461+00:00"
BODY = {  # the live shape of 2026-10-14, numbers changed
    "five_hour": {"utilization": 54.0, "resets_at": RESET_5H},
    "seven_day": {"utilization": 42.0, "resets_at": RESET_7D},
    "seven_day_opus": None,
    "limits": [
        {"kind": "session", "group": "session", "percent": 54, "severity": "normal", "scope": None, "is_active": True,
         "resets_at": RESET_5H},
        {"kind": "weekly_all", "group": "weekly", "percent": 42, "severity": "normal", "scope": None,
         "is_active": False, "resets_at": RESET_7D},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 22, "severity": "normal",
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}, "is_active": False,
         "resets_at": RESET_7D},
    ],
    "seven_day_breakdown": {"as_of": RESET_5H, "rows": [{"key": "claude_code", "display_name": "Claude Code", "percent": 100},
                                                        {"key": "chat", "display_name": "Chats", "percent": 0}]},
    "weekly_scoped_shares": [{"limit_index": 2, "used_percent_of_weekly": 11, "allowance_percent_of_weekly": 50}],
}


def test_parse_gives_the_three_bars_and_the_surfaces():
    bars = usage.parse(BODY)
    assert bars["five_hour"]["pct"] == 0.54 and bars["seven_day"]["pct"] == 0.42
    assert bars["five_hour"]["reset"] == usage._when(RESET_5H) > 1.7e9
    assert bars["models"] == {"fable": {"pct": 0.22, "reset": usage._when(RESET_7D), "cap": 0.5, "used": 0.11}}  # W62: the cap
    assert bars["surfaces"] == {"claude_code": 1.0, "chat": 0.0}


def test_odd_values_and_unknown_shapes_are_dropped_not_trusted():
    body = json.loads(json.dumps(BODY))
    body["limits"][0]["percent"] = "54"  # a string
    body["limits"][1]["resets_at"] = "soon"  # not a time
    body["limits"][2]["percent"] = 140  # over the scale
    body["five_hour"]["utilization"] = float("nan")
    bars = usage.parse(body)
    assert "five_hour" not in bars and bars["models"] == {}
    assert bars["seven_day"]["pct"] == 0.42  # the flat object filled the gap left by the odd limits row
    assert usage.parse(None) == {"models": {}, "surfaces": {}} and usage.parse({"limits": "x"})["models"] == {}


class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return json.dumps(self.body).encode()


def login(tmp_path, token="tok-secret-123"):
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": token}}), encoding="utf-8")
    return str(tmp_path)


def test_fetch_sends_the_token_only_to_the_endpoint_and_caches_for_a_minute(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOPILOT_NO_LIVE_USAGE", raising=False)  # conftest sets it: no other test calls the endpoint
    calls, clock = [], [1000.0]

    def urlopen(url, headers):
        calls.append((url, headers))
        return Resp(BODY)
    folder = login(tmp_path)
    cache = {}
    bars = usage.fetch(folder, urlopen=urlopen, now=lambda: clock[0], cache=cache)
    assert bars["five_hour"]["pct"] == 0.54 and bars["at"] == 1000.0
    assert calls[0][0] == usage.URL and calls[0][1]["Authorization"] == "Bearer tok-secret-123"
    assert calls[0][1]["anthropic-beta"] == usage.BETA
    assert "tok-secret-123" not in repr(bars)  # the token is not part of the result
    clock[0] = 1030.0
    assert usage.fetch(folder, urlopen=urlopen, now=lambda: clock[0], cache=cache) is bars and len(calls) == 1
    clock[0] = 1061.0
    usage.fetch(folder, urlopen=urlopen, now=lambda: clock[0], cache=cache)
    assert len(calls) == 2


def test_kill_switch_no_token_and_a_failed_call_give_empty_without_a_raise(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOPILOT_NO_LIVE_USAGE", raising=False)
    calls = []

    def boom(url, headers):
        calls.append(url)
        raise OSError("down")

    class Cfg:
        def get(self, key, default=None):
            return False if key == "usage.live" else default
    folder = login(tmp_path)
    assert usage.fetch(folder, cfg=Cfg(), urlopen=boom, cache={}) == {} and calls == []  # the kill switch
    assert usage.fetch(str(tmp_path / "nowhere"), urlopen=boom, cache={}) == {} and calls == []  # no login here
    cache = {}
    assert usage.fetch(folder, urlopen=boom, now=lambda: 5.0, cache=cache) == {} and len(calls) == 1
    assert usage.fetch(folder, urlopen=boom, now=lambda: 20.0, cache=cache) == {} and len(calls) == 1  # failures are cached too

    def odd(url, headers):
        return Resp({"limits": [], "hello": 1})
    assert usage.fetch(folder, urlopen=odd, cache={}) == {}  # an unknown shape: the CLI figures stay the source


def test_read_token_and_config_dir(tmp_path, monkeypatch):
    assert usage.read_token(login(tmp_path, "abc")) == "abc"
    assert usage.read_token(str(tmp_path / "missing")) == ""
    (tmp_path / ".credentials.json").write_text("{not json", encoding="utf-8")
    assert usage.read_token(str(tmp_path)) == ""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "env"))
    assert usage.config_dir("") == tmp_path / "env" and usage.config_dir("default") == tmp_path / "env"
    assert usage.config_dir(str(tmp_path / "two")) == tmp_path / "two"


# ---------- part 2: figures per login, the headroom pick, the one line, the balances ----------
class FakeState:
    def __init__(self):
        self.meta = {}

    def get_meta(self, key, default=None):
        return self.meta.get(key, default)

    def set_meta(self, key, value):
        self.meta[key] = value


def rank(m):
    return {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}.get(m, 1)


def test_figures_prefer_live_cache_in_meta_and_mark_a_mismatch_with_check():
    st, clock, calls = FakeState(), [1000.0], []
    live = {"five_hour": {"pct": 0.54, "reset": 5000.0}, "seven_day": {"pct": 0.42, "reset": 9000.0},
            "models": {"fable": {"pct": 0.22, "reset": 9000.0}}, "surfaces": {}, "at": 1000.0}

    def fetch(folder, cfg=None, now=None):
        calls.append(folder)
        return live
    st.set_meta("window_seen", {"five_hour": {"pct": 0.40, "reset": 5000.0}})  # the CLI figure, 14 points apart
    figs = usage.figures(st, None, "default", now=lambda: clock[0], live_fetch=fetch)
    assert figs["source"] == "live" and figs["five_hour"]["pct"] == 0.54 and figs["check"] is True
    assert figs["models"]["fable"]["pct"] == 0.22 and st.get_meta("usage_live")["bars"] is live
    clock[0] = 1030.0
    usage.figures(st, None, "default", now=lambda: clock[0], live_fetch=fetch)
    assert calls == [""]  # the meta row is the cache: the second read made no call
    figs = usage.figures(st, None, "/logins/two", now=lambda: clock[0], live_fetch=fetch)
    assert calls == ["", "/logins/two"] and "usage_live@/logins/two" in st.meta  # one row per login


def test_figures_fall_back_to_the_cli_figures_marked_cli():
    st = FakeState()
    st.set_meta("window_seen", {"five_hour": {"pct": 0.40, "reset": 5000.0}, "seven_day": {"pct": 0.61, "reset": 9000.0}})
    figs = usage.figures(st, None, "default", now=lambda: 2000.0, live_fetch=lambda *a, **k: {})
    assert figs["source"] == "cli" and figs["five_hour"]["pct"] == 0.40 and figs["seven_day"]["pct"] == 0.61
    assert usage.figures(st, None, "default", now=lambda: 50000.0, live_fetch=lambda *a, **k: {})["source"] == ""  # expired
    line = usage.now_line(figs, "sonnet", "default", "subscription")
    assert line.startswith("now: sonnet (login default) · 5h 40% (cli) · week 61% · subscription · resets ")


def test_pick_skips_an_out_model_downward_never_upward():
    figs = {"models": {"opus": {"pct": 1.0, "reset": 9000.0}, "sonnet": {"pct": 0.3, "reset": 9000.0}}}
    assert usage.pick("opus", ["sonnet", "opus", "opus"], figs, 95, rank) == ("sonnet", "opus is out until " + usage._hm(9000.0) + ", running on sonnet")
    assert usage.pick("sonnet", ["sonnet", "opus"], figs, 95, rank) == ("sonnet", "")  # has room: unchanged
    assert usage.pick("opus", ["opus", "opus"], figs, 95, rank)[0] == "opus"  # nothing lower: the lowest, with a why
    assert "every model of the ladder is out" in usage.pick("opus", ["opus"], figs, 95, rank)[1]
    assert usage.pick("haiku", ["haiku", "sonnet", "opus"], figs, 95, rank) == ("haiku", "")  # never up
    assert usage.out_until(figs, "claude-opus-4-7", 95) == 9000.0 and usage.out_until(figs, "sonnet", 95) == 0.0
    assert usage.out_until(figs, "sonnet", 25) == 9000.0  # the reserve is the threshold


def test_now_line_has_every_part_in_the_spec_order():
    figs = {"five_hour": {"pct": 0.4, "reset": 9000.0}, "seven_day": {"pct": 0.61, "reset": 9000.0},
            "models": {"fable": {"pct": 0.22, "reset": 9000.0}}, "source": "live", "check": False}
    line = usage.now_line(figs, "fable", "claude-2", "subscription")
    assert line == f"now: fable (login claude-2) · 5h 40% · week 61% · fable week 22% · subscription · resets {usage._hm(9000.0)}"
    assert usage.now_line({"models": {}}, "", "default") == ""
    assert usage.now_line({**figs, "check": True}, "sonnet").endswith(" · check")


class Cfg:
    def __init__(self, d):
        self.d = d

    def get(self, key, default=None):
        return self.d.get(key, default)


def test_balances_and_the_balance_text():
    cfg = Cfg({"usage.api_credit": {"usd": 109, "entered": "2026-10-14", "expires": "2026-12-01"},
               "usage.cloud_credit": {"usd": "x"}})
    assert usage.balances(cfg) == {"api": {"usd": 109.0, "entered": "2026-10-14", "expires": "2026-12-01"}}
    assert usage.balance_text(cfg, "api") == "api credit $109 (entered 2026-10-14), expires 2026-12-01"
    assert usage.balance_text(cfg, "subscription") == "subscription" and usage.balance_text(Cfg({}), "api") == "api key"


def test_write_balance_keeps_comments_and_records_the_entry_date(tmp_path):
    yml = tmp_path / "project.yaml"
    yml.write_text("budget_usd:\n  total: 20   # cap\nusage:                 # the window\n  billing: subscription\n  reserve_pct: 15\n", encoding="utf-8")
    assert usage.write_balance(yml, "cloud", 149, "2026-11-05", entered="2026-10-14")
    text = yml.read_text(encoding="utf-8")
    assert "# cap" in text and "# the window" in text and "reserve_pct: 15" in text
    assert "  cloud_credit: {usd: 149, entered: '2026-10-14', expires: '2026-11-05'}" in text
    assert usage.write_balance(yml, "cloud", 100, entered="2026-10-15")  # a second entry replaces the line
    assert "cloud_credit: {usd: 100, entered: '2026-10-15'}" in yml.read_text(encoding="utf-8")
    import yaml
    assert yaml.safe_load(yml.read_text(encoding="utf-8"))["usage"]["cloud_credit"]["usd"] == 100
    empty = tmp_path / "new.yaml"
    assert usage.write_balance(empty, "api", 109, entered="2026-10-14")
    assert yaml.safe_load(empty.read_text(encoding="utf-8")) == {"usage": {"api_credit": {"usd": 109, "entered": "2026-10-14"}}}


def test_ap_budget_enters_the_credits_without_a_cap(tmp_path, capsys):
    from argparse import Namespace

    from autopilot.cli import cmd_budget
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "project.yaml").write_text("usage:\n  billing: subscription\n", encoding="utf-8")
    rc = cmd_budget(Namespace(path=str(tmp_path), usd=None, cloud_credit=149.0, api_credit=109.0, expires="2026-11-05"))
    out = capsys.readouterr().out
    assert rc == 0 and "cloud credit $149 entered today, expires 2026-11-05" in out and "api credit $109" in out
    text = (tmp_path / ".agent" / "project.yaml").read_text(encoding="utf-8")
    assert "cloud_credit: {usd: 149, entered: " in text and "api_credit: {usd: 109, entered: " in text
    assert cmd_budget(Namespace(path=str(tmp_path), usd=None, cloud_credit=None, api_credit=None, expires="")) == 1


def test_the_ladder_moves_down_when_the_model_is_out_and_the_log_says_why(tmp_path, monkeypatch):
    from test_window import Metered, run, tasks
    live = {"five_hour": {"pct": 0.2, "reset": 1e10}, "seven_day": {"pct": 0.3, "reset": 1e10},
            "models": {"opus": {"pct": 1.0, "reset": 1e10}}, "surfaces": {}, "at": 1.0}
    monkeypatch.setattr(usage, "fetch", lambda *a, **k: dict(live))
    orch, _, _ = run(tmp_path, tasks(1), {"models": {"ladder": {"low": ["sonnet", "opus", "opus"]}}}, Metered([0.2]))
    assert orch.model_for("low", 1) == "sonnet"  # attempt 2 would be opus: out at 100%, so down to sonnet
    assert orch.model_for("low", 0) == "sonnet"
    assert orch.state.get_meta("usage_why").startswith("opus is out until")
    assert orch.usage_line("sonnet").startswith("now: sonnet (login default) · 5h 20% · week 30% · subscription · resets ")


# ---------- W60: the source planner ----------
def figs_for(default_week, two_week, now, reset_in=86400):
    """A fake `usage.figures` keyed by login folder: the default login and `/logins/two`."""
    def figures(state, cfg=None, acct="default", **kw):
        week = default_week if acct in ("", "default") else two_week
        return {"five_hour": {"pct": 0.1, "reset": now + 3600}, "seven_day": {"pct": week, "reset": now + reset_in},
                "models": {}, "surfaces": {}, "source": "live", "check": False}
    return figures


FALLBACK = [{"claude_cli": {"CLAUDE_CONFIG_DIR": "/logins/two"}}]


def test_sources_table_lists_logins_api_and_cloud_with_room_and_notes(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(usage, "figures", figs_for(1.0, 0.12, now))
    cfg = Cfg({"agent.fallback": FALLBACK, "usage.api_credit": {"usd": 109, "entered": "2026-10-14", "expires": "2026-12-01"},
               "usage.cloud_credit": {"usd": 149, "entered": "2026-10-14", "expires": "2026-11-05"}, "usage.sources_off": ["cloud"]})
    rows = {r["name"]: r for r in usage.sources(cfg, FakeState(), now=lambda: now)}
    assert rows["login:default"]["room"] == 0.0 and rows["login:two"]["room"] == 0.88 and rows["login:two"]["folder"] == "/logins/two"
    assert rows["api"]["note"].startswith("needs backend") and rows["api"]["can_run"] is False and rows["api"]["usd"] == 109
    assert rows["cloud"]["off"] is True and rows["cloud"]["expires"] == usage._day("2026-11-05")


def test_plan_source_prefers_an_idle_window_then_the_most_room_and_names_the_limit(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(usage, "figures", figs_for(1.0, 0.12, now))
    cfg = Cfg({"agent.fallback": FALLBACK})
    rows = usage.sources(cfg, FakeState(), now=lambda: now)
    pick = usage.plan_source(rows, "login:default", 50, now=lambda: now)
    assert pick["source"] == "login:two" and pick["reason"] == "window idle" and "week 12% used" in pick["text"]
    assert usage.suggest_line(pick).startswith("suggest: switch to login:two (window idle: login two week 12% used, resets ")
    assert usage.suggest_line(pick).endswith("; say ap source two")
    # the window of login two is not in its last two days: the default login is out, so the reason is the limit
    monkeypatch.setattr(usage, "figures", figs_for(1.0, 0.12, now, reset_in=5 * 86400))
    rows = usage.sources(cfg, FakeState(), now=lambda: now)
    pick = usage.plan_source(rows, "login:default", 50, now=lambda: now)
    assert pick["reason"] == "limit" and pick["source"] == "login:two"
    # the current login has room and nothing is idle: stay
    monkeypatch.setattr(usage, "figures", figs_for(0.3, 0.6, now, reset_in=5 * 86400))
    rows = usage.sources(cfg, FakeState(), now=lambda: now)
    assert usage.plan_source(rows, "login:default", 50, now=lambda: now) == {}
    # a source marked off is never picked, and cloud is never a target
    monkeypatch.setattr(usage, "figures", figs_for(1.0, 0.12, now))
    rows = usage.sources(Cfg({"agent.fallback": FALLBACK, "usage.sources_off": ["login:two"],
                             "usage.cloud_credit": {"usd": 149, "entered": "2026-10-14", "expires": "2026-11-05"}}), FakeState(), now=lambda: now)
    assert usage.plan_source(rows, "login:default", 50, now=lambda: now) == {}


def test_expiring_credits_give_the_two_alert_texts():
    now = usage._day("2026-11-03")
    cfg = Cfg({"usage.cloud_credit": {"usd": 149, "entered": "2026-10-14", "expires": "2026-11-05"},
               "usage.api_credit": {"usd": 109, "entered": "2026-10-14", "expires": "2026-12-01"}})
    assert usage.expiring(cfg, now=lambda: now) == [("cloud", 149.0, "2026-11-05")]
    assert usage.expiry_text("cloud", 149, "2026-11-05") == "cloud credit $149 expires 2026-11-05: schedule a Routine run"
    assert usage.expiry_text("api", 109, "2026-12-01").startswith("api credit $109 expires 2026-12-01: set usage.switch auto")


def test_auto_mode_switches_to_the_idle_login_between_tasks_and_logs_the_reason(tmp_path, monkeypatch):
    from autopilot import handoff
    from autopilot.orchestrator import Orchestrator
    from test_autopilot import FakeBackend, make_project
    from test_handoff import PHASES
    folder = str(tmp_path / "claude-2")
    now = time.time()
    monkeypatch.setattr(usage, "figures", figs_for(1.0, 0.12, now))  # default week 100%, login 2 at 12%, resets in a day
    root = make_project(tmp_path, PHASES, {"agent": {"fallback": [{"claude_cli": {"CLAUDE_CONFIG_DIR": folder}}]},
                                           "usage": {"switch": "auto"}})
    second, envs = FakeBackend(), []

    def factory(cfg):
        envs.append(cfg.get("agent.env"))
        return second
    monkeypatch.setattr(handoff, "get_backend", factory)
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "app complete"
    assert envs and envs[0] == {"CLAUDE_CONFIG_DIR": folder}  # the first task already ran on login 2
    msgs = [e["message"] for e in orch.state.events(200) if e["kind"] == "source"]
    assert msgs and msgs[0].startswith("default -> claude-2 (window idle: login claude-2 week 12% used")
    assert orch.state.get_meta("active_account") == folder


def test_ap_source_lists_and_picks_a_login(tmp_path, monkeypatch, capsys):
    from argparse import Namespace

    from autopilot.cli import cmd_source
    from test_autopilot import make_project
    from test_handoff import PHASES
    folder = str(tmp_path / "claude-2")
    now = time.time()
    monkeypatch.setattr(usage, "figures", figs_for(0.4, 0.12, now))
    root = make_project(tmp_path, PHASES, {"agent": {"fallback": [{"claude_cli": {"CLAUDE_CONFIG_DIR": folder}}]}})
    assert cmd_source(Namespace(path=str(root), name=None)) == 0
    out = capsys.readouterr().out
    assert "login:default" in out and "login:claude-2" in out and "60% room" in out and "needs backend" in out
    assert cmd_source(Namespace(path=str(root), name="claude-2")) == 0
    assert "source: login:claude-2 (owner:" in capsys.readouterr().out
    from autopilot.cli import _open_state
    _, _, state = _open_state(root)
    assert state.get_meta("active_account") == folder and state.get_meta("handoff_runner") == {"claude_cli": {"CLAUDE_CONFIG_DIR": folder}}
    assert cmd_source(Namespace(path=str(root), name="nobody")) == 1
