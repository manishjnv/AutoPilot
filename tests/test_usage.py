"""W59 core: the OAuth usage endpoint is parsed into plain bars, read at most once a minute per login, behind a kill
switch, and the token never leaves the request."""
import json

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
}


def test_parse_gives_the_three_bars_and_the_surfaces():
    bars = usage.parse(BODY)
    assert bars["five_hour"]["pct"] == 0.54 and bars["seven_day"]["pct"] == 0.42
    assert bars["five_hour"]["reset"] == usage._when(RESET_5H) > 1.7e9
    assert bars["models"] == {"fable": {"pct": 0.22, "reset": usage._when(RESET_7D)}}
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


def test_fetch_sends_the_token_only_to_the_endpoint_and_caches_for_a_minute(tmp_path):
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


def test_kill_switch_no_token_and_a_failed_call_give_empty_without_a_raise(tmp_path):
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
