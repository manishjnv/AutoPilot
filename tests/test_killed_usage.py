"""A session killed before its result event (stuck, timeout) still records tokens and an estimated cost, so the
ledger and the U4 window budget don't undercount."""
import json
import time

from autopilot.backends import SessionRequest
from autopilot.backends.claude_cli import ClaudeCLIBackend, partial_usage
from autopilot.config import Config
from test_backend import stub_claude


def assistant(mid, model="claude-sonnet-5-5", tool=None, **usage):
    content = [{"type": "tool_use", "name": "Bash", "input": {"command": tool}}] if tool else [{"type": "text"}]
    return json.dumps({"type": "assistant", "message": {"id": mid, "model": model, "content": content,
                                                        "usage": usage}})


def test_activity_lines_show_what_the_session_is_doing():
    from autopilot.backends.claude_cli import activity
    edit = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Now   the\nplan."},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/app/cli.py", "old_string": "x"}}]}})
    assert activity(edit) == '"Now the plan."; Edit src/app/cli.py'
    assert activity(assistant("m1", tool="pytest -q", input_tokens=1)) == "Bash pytest -q"
    assert activity(json.dumps({"type": "result", "result": "done"})) == "" and activity("not json") == ""


def test_partial_usage_sums_messages_and_prices_them():
    raw = "\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
        assistant("m1", input_tokens=1000, output_tokens=100),
        assistant("m1", input_tokens=1000, output_tokens=200),  # same message, later event: counted once (last)
        assistant("m2", input_tokens=500, output_tokens=0, cache_read_input_tokens=10_000,
                  cache_creation_input_tokens=2000),
        assistant("m3", model="claude-haiku-4-5", input_tokens=1_000_000),
        "not json"])
    u = partial_usage(raw, "sonnet")
    s = u["claude-sonnet-5-5"]
    assert (s["input"], s["output"], s["cache_read"], s["cache_write"]) == (1500, 200, 10_000, 2000)
    # 1500*2 + 200*10 + 10000*0.2 + 2000*2.5 = 12000 per MTok
    assert abs(s["cost"] - 0.012) < 1e-9 and u["claude-haiku-4-5"]["cost"] == 1.0
    assert partial_usage(assistant("x", model="mystery", output_tokens=1_000_000), "sonnet")["mystery"]["cost"] == 20.0
    assert partial_usage("", "sonnet") == {}


def test_stuck_session_keeps_its_tokens(tmp_path, monkeypatch):
    lines = [assistant(f"m{i}", tool="npm test", input_tokens=1000, output_tokens=100) for i in range(4)]
    body = (f"print(json.dumps({{'type': 'system', 'session_id': 'sx'}}), flush=True)\n"
            f"for l in {lines!r}: print(l, flush=True)\n"
            "import time; time.sleep(60)\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert res.stuck and not res.ok and res.session_id == "sx"
    assert res.usage["claude-sonnet-5-5"]["input"] == 4000 and abs(res.cost - 0.012) < 1e-9


def test_timed_out_session_keeps_its_tokens(tmp_path, monkeypatch):
    body = (f"print({assistant('m1', input_tokens=2000, output_tokens=0)!r}, flush=True)\n"
            "import time; time.sleep(60)\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    t0 = time.time()
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(
        SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path), timeout_sec=3))
    assert time.time() - t0 < 45 and res.timed_out and not res.ok
    assert res.usage["claude-sonnet-5-5"]["input"] == 2000 and abs(res.cost - 0.004) < 1e-9
