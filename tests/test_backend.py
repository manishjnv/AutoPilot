"""Backend hardening: limit detection, reset parsing, least-privilege env, Windows shim argv."""
import sys
from datetime import datetime, timezone

from autopilot.backends import SessionRequest, detect_limit, parse_reset
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_parse_reset_variants():
    assert parse_reset("3:45pm", NOW) == at(2026, 10, 1, 15, 45)
    assert parse_reset("3pm", NOW) == at(2026, 10, 1, 15)
    assert parse_reset("15:45", NOW) == at(2026, 10, 1, 15, 45)
    assert parse_reset("11am", NOW) == at(2026, 10, 2, 11)            # already past today -> tomorrow
    assert parse_reset("Oct 3, 9am", NOW) == at(2026, 10, 3, 9)
    assert parse_reset("Oct 3 at 9am", NOW) == at(2026, 10, 3, 9)
    assert parse_reset("Sep 3, 9am", NOW) == at(2027, 9, 3, 9)        # past date -> next year
    assert parse_reset("garbage", NOW) is None and parse_reset("", NOW) is None and parse_reset("13pm", NOW) is None


def test_parse_reset_timezone_and_unknown_zone():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Asia/Calcutta")
    except Exception:  # noqa: BLE001
        return
    assert parse_reset("Oct 3, 9am (Asia/Calcutta)", NOW) == at(2026, 10, 3, 3, 30)
    assert parse_reset("3pm (Not/AZone)", NOW) == at(2026, 10, 1, 15)  # unknown zone -> now's own zone


def test_detect_limit():
    assert detect_limit("You've hit your session limit · resets 3:45pm", NOW) == (True, at(2026, 10, 1, 15, 45))
    assert detect_limit("You've hit your weekly limit · resets Oct 3, 9am (UTC)", NOW) == (True, at(2026, 10, 3, 9))
    assert detect_limit("You've hit your Opus limit · resets 5pm", NOW) == (True, at(2026, 10, 1, 17))
    assert detect_limit("API Error: 529 {\"type\":\"overloaded_error\"}", NOW) == (True, None)
    assert detect_limit("Implemented a rate limiter with quota handling", NOW) == (False, None)
    assert detect_limit("You've hit your session limit · resets soonish", NOW) == (True, None)


def stub_claude(tmp_path, body):
    (tmp_path / "stub.py").write_text("import json,os,sys\nsys.stdin.read()\n" + body)
    if sys.platform == "win32":
        stub = tmp_path / "claude.cmd"
        stub.write_text(f'@"{sys.executable}" "%~dp0stub.py" %*\n')
    else:
        stub = tmp_path / "claude"
        stub.write_text(f"#!{sys.executable}\n" + (tmp_path / "stub.py").read_text())
        stub.chmod(0o755)
    return str(stub)


def run_stub(tmp_path, monkeypatch, body):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    return ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))


def test_agent_prose_is_not_a_rate_limit(tmp_path, monkeypatch):
    res = run_stub(tmp_path, monkeypatch,
                   "print(json.dumps({'is_error': True, 'result': 'built a rate limiter'}))\n")
    assert not res.ok and res.rate_limited is False and res.reset_at is None


def test_subscription_limit_sets_reset(tmp_path, monkeypatch):
    res = run_stub(tmp_path, monkeypatch,
                   "print(json.dumps({'is_error': True, 'result': \"You've hit your session limit \\u00b7 resets 4pm\"}))\n")
    assert res.rate_limited is True and res.reset_at and res.reset_at > datetime.now().timestamp()


def test_agent_env_is_least_privilege(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TG_TOKEN", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    res = run_stub(tmp_path, monkeypatch,
                   "print(json.dumps({'is_error': False, 'result': ','.join(os.environ)}))\n")
    keys = res.text.split(",")
    assert res.ok and "AUTOPILOT_TG_TOKEN" not in keys and "ANTHROPIC_API_KEY" in keys


def test_shim_keeps_system_text_out_of_argv(tmp_path, monkeypatch):
    req = SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path), system_append="line1\nline2")
    cfg = Config.load(tmp_path)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", "C:/x/claude.CMD")
    assert "--append-system-prompt" not in ClaudeCLIBackend(cfg).build_cmd(req)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", "/usr/bin/claude")
    assert "--append-system-prompt" in ClaudeCLIBackend(cfg).build_cmd(req)


def test_limit_text_inside_prose_is_not_a_limit():
    assert detect_limit("I stopped because the user may have hit your session limit · resets 3pm")[0] is False
    assert detect_limit("Retrying failed: API Error: 529 overloaded_error")[0] is False
    assert detect_limit("done\nYou've hit your session limit · resets 3pm")[0] is True
