"""W63: when every login is out, wait for the earliest refill in slices, then resume by itself, with one line."""
import json

import pytest

from autopilot import usage
from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator, Stop
from autopilot.report import status_line
from test_autopilot import FakeBackend, make_project
from test_window import tasks

T0 = 1_800_000_000.0
H = 3600.0


def login_dirs(tmp_path, names=("two", "three"), expired=()):
    out = []
    for n in names:
        d = tmp_path / f"login-{n}"
        d.mkdir()
        exp = {"expiresAt": (T0 - H) * 1000} if n in expired else {}
        (d / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-" + n, **exp}}), encoding="utf-8")
        out.append(str(d))
    return out


class Scenario:
    """Fake `usage.figures`: `bars[folder]` = (five, week, five_reset, week_reset); `room_at` = {folder: time}: from
    that time on the folder's 5-hour bar reads 10 percent. Records every fresh read."""

    def __init__(self, bars, room_at=None):
        self.bars, self.room_at, self.reads = bars, room_at or {}, []

    def __call__(self, state, cfg=None, acct="default", *, now=None, fresh=False, **kw):
        t = now() if now else T0
        folder = "" if acct == "default" else acct
        five, week, r5, r7 = self.bars[folder]
        if fresh:
            self.reads.append((folder, t))
        if folder in self.room_at and t >= self.room_at[folder]:
            five = 0.1
        return {"five_hour": {"pct": five, "reset": r5}, "seven_day": {"pct": week, "reset": r7}, "models": {}, "surfaces": {},
                "source": "live", "check": False}


def orch_with_clock(tmp_path, folders, cfg=None):
    root = make_project(tmp_path, tasks(1), {"agent": {"fallback": [{"claude_cli": {"CLAUDE_CONFIG_DIR": f}} for f in folders]},
                                            **(cfg or {})})
    clock = [T0]
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch._now = lambda: clock[0]
    orch._mono = lambda: clock[0] - T0
    orch._nap = lambda s: clock.__setitem__(0, clock[0] + s)
    orch.run_info["state"] = "Code"
    return orch, clock


def waits(orch):
    return [e["message"] for e in reversed(orch.state.events(200)) if e["kind"] == "wait"]  # oldest first


def test_waits_toward_the_earliest_reset_and_resumes_on_the_login_that_shows_room(tmp_path, monkeypatch):
    two, three = login_dirs(tmp_path)
    orch, clock = orch_with_clock(tmp_path, [two, three])
    monkeypatch.setattr(usage, "token_expired", lambda folder="", now=None: False)
    sc = Scenario({"": (1.0, 0.5, T0 + 3 * H, T0 + 9 * H), two: (1.0, 0.6, T0 + 5 * H, T0 + 9 * H), three: (0.99, 0.6, T0 + 9 * H, T0 + 9 * H)},
                  room_at={two: T0 + H})
    monkeypatch.setattr(usage, "figures", sc)
    # at +1h the owner touches a credentials file (a new login): the watch triggers a fresh fetch, login two shows room
    import os
    real_nap = orch._nap

    def nap(s):
        real_nap(s)
        if clock[0] >= T0 + H and not getattr(nap, "touched", False):
            nap.touched = True
            os.utime(os.path.join(two, ".credentials.json"), (clock[0], clock[0]))
    orch._nap = nap
    assert orch.wait_for_refill(0.0) is True
    assert orch.state.get_meta("active_account") == two
    msgs = waits(orch)
    assert len(msgs) == 2 and msgs[0].startswith("Waiting · all logins out · default refills ") and "(in 3h00m)" in msgs[0]
    assert msgs[1].startswith(f"Resumed on login {two.replace(chr(92), '/').rsplit('/', 1)[-1]} after: Waiting")
    assert T0 + H <= clock[0] < T0 + H + 30 and orch.run_info["state"] == "Code" and orch.run_info["current"] == ""
    assert all(t >= T0 + H for _, t in sc.reads)  # no fetch for hours before a known reset
    assert orch.outage_waits == 0  # never an outage


def test_a_stop_file_ends_the_wait_within_one_slice_with_stopped(tmp_path, monkeypatch):
    two, three = login_dirs(tmp_path)
    orch, clock = orch_with_clock(tmp_path, [two, three])
    monkeypatch.setattr(usage, "token_expired", lambda folder="", now=None: False)
    monkeypatch.setattr(usage, "figures", Scenario({"": (1.0, 0.5, T0 + 3 * H, T0 + 9 * H), two: (1.0, 0.6, T0 + 5 * H, T0 + 9 * H),
                                                    three: (1.0, 0.6, T0 + 9 * H, T0 + 9 * H)}))
    real_nap = orch._nap

    def nap(s):
        real_nap(s)
        if clock[0] >= T0 + 1800:
            (orch.ad / "STOP").write_text("", encoding="utf-8")
    orch._nap = nap
    with pytest.raises(Stop) as exc:
        orch.wait_for_refill(0.0)
    assert exc.value.word == "STOPPED" and clock[0] <= T0 + 1800 + 2 * orch.WAIT_SLICE


def test_a_fetch_at_the_target_that_shows_every_login_out_keeps_waiting_with_the_next_reset(tmp_path, monkeypatch):
    two, three = login_dirs(tmp_path)
    orch, clock = orch_with_clock(tmp_path, [two, three])
    monkeypatch.setattr(usage, "token_expired", lambda folder="", now=None: False)
    sc = Scenario({"": (1.0, 0.5, T0 + 3 * H, T0 + 9 * H), two: (1.0, 0.6, T0 + 5 * H, T0 + 9 * H), three: (1.0, 0.6, T0 + 9 * H, T0 + 9 * H)},
                  room_at={two: T0 + 5 * H})
    monkeypatch.setattr(usage, "figures", sc)
    assert orch.wait_for_refill(0.0) is True
    assert T0 + 5 * H <= clock[0] < T0 + 5 * H + 1200 and orch.state.get_meta("active_account") == two
    lines = waits(orch)
    assert "default refills" in lines[0]
    assert any("two refills" in r for r in [orch.run_info.get("current", "")] + lines) or orch.run_info.get("current") == ""
    assert sc.reads and sc.reads[0][1] >= T0 + 3 * H - orch.WAIT_WINDOW  # the first fetch inside the 30-minute window


def test_an_expired_token_login_is_never_the_wake_target():
    figs = {"": {"five_hour": {"pct": 1.0, "reset": T0 + 5 * H}, "seven_day": {"pct": 0.5, "reset": T0 + 9 * H}, "models": {}},
            "/x": {"five_hour": {"pct": 1.0, "reset": T0 + H}, "seven_day": {"pct": 0.5, "reset": T0 + 9 * H}, "models": {}}}
    wake, who = usage.wake_target([("", "default"), ("/x", "x")], lambda f: figs[f], now=lambda: T0,
                                  expired=lambda f, now=None: f == "/x")
    assert (wake, who) == (T0 + 5 * H, "default")
    assert usage.wake_target([("/x", "x")], lambda f: figs[f], now=lambda: T0, expired=lambda f, now=None: True) == (0.0, "")
    assert usage.waiting_line("default", T0 + 2 * H + 14 * 60, now=lambda: T0).endswith("(in 2h14m)")
    assert usage.waiting_line("default", 0.0) == "Waiting · all logins out · no reset time known"


def test_token_expired_reads_the_credentials_file(tmp_path):
    two, three = login_dirs(tmp_path, expired=("three",))
    assert usage.token_expired(three, now=lambda: T0) is True and usage.token_expired(two, now=lambda: T0) is False
    assert usage.token_expired(str(tmp_path / "none"), now=lambda: T0) is False


def test_a_refill_beyond_the_cap_stops_at_entry_and_the_switch_can_turn_the_wait_off(tmp_path, monkeypatch):
    two, three = login_dirs(tmp_path)
    orch, clock = orch_with_clock(tmp_path, [two, three])
    monkeypatch.setattr(usage, "token_expired", lambda folder="", now=None: False)
    monkeypatch.setattr(usage, "figures", Scenario({"": (1.0, 1.0, T0 + 60 * H, T0 + 60 * H), two: (1.0, 1.0, T0 + 70 * H, T0 + 70 * H),
                                                    three: (1.0, 1.0, T0 + 80 * H, T0 + 80 * H)}))
    with pytest.raises(Stop) as exc:
        orch.wait_for_refill(0.0)
    assert exc.value.word == "STOPPED" and "no login had room for 48 h; run ap start to continue" in exc.value.reason
    orch2, _ = orch_with_clock(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, [two, three], {"usage": {"wait_for_refill": False}})
    assert orch2.wait_for_refill(0.0) is False  # the old sleep applies


def test_the_line_is_the_same_in_the_status_bar_the_card_and_the_page(tmp_path):
    from autopilot.dash_web import render
    from autopilot.dashboard import dashboard_data
    from autopilot.report import status_panel
    from test_dashboard import built
    orch = built(tmp_path)
    line = usage.waiting_line("default", T0 + 2 * H, now=lambda: T0)
    run = {"status": "running", "state": "Wait", "current": line, "started_at": "2026-10-15T01:00:00", "pid": None}
    bar = status_line(orch.cfg, orch.plan, orch.state, run)
    assert line in bar
    data = dashboard_data(orch.cfg, orch.plan, orch.state, run)
    assert data["asof"]["wait_text"] == line
    assert line in render(data)
    assert any(line in cell for cell in status_panel(orch.cfg, orch.plan, orch.state, run))
