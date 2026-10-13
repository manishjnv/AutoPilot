"""W29: unknown session errors are written to unknown.jsonl, once per wording per day, scrubbed, with no path."""
import json

import pytest

from autopilot import __version__, signals

UNKNOWN = "the frobnicator returned a strange answer: widget mismatch 42"


def rows(home):
    p = home / "unknown.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


@pytest.mark.parametrize("project", ["/tmp/work/myproj", "C:\\work\\myproj", "C:\\work\\myproj\\", "myproj"])
def test_unknown_text_writes_one_line_without_path(tmp_path, project):
    assert signals.record_unknown(UNKNOWN, "claude_cli", project, "retried", home=tmp_path)
    raw = (tmp_path / "unknown.jsonl").read_text(encoding="utf-8")
    assert len(raw.splitlines()) == 1
    assert "work" not in raw and "/" not in raw and "\\\\" not in raw  # no folder path, on any host
    row = json.loads(raw)
    assert row["project"] == "myproj"
    assert row["cause"] == "unknown" and row["count"] == 1 and row["action"] == "retried"
    assert row["runner"] == "claude_cli" and row["version"] == __version__ and row["text"] == UNKNOWN
    assert len(row["date"]) == 10


@pytest.mark.parametrize("text", ["API Error: Connection error.", "Please run /login",
                                  "You've hit your limit · resets 3pm", "API Error: 429 rate_limit_error"])
def test_known_infra_or_limit_text_writes_none(tmp_path, text):
    assert signals.cause_of(text) in ("infra", "limit")
    assert not signals.record_unknown(text, "claude_cli", "proj", "retried", home=tmp_path)
    assert rows(tmp_path) == []


def test_repeat_same_day_counts_two(tmp_path):
    signals.record_unknown(UNKNOWN, "claude_cli", "proj", "retried", home=tmp_path)
    signals.record_unknown(UNKNOWN, "claude_cli", "proj", "parked", home=tmp_path)
    got = rows(tmp_path)
    assert len(got) == 1 and got[0]["count"] == 2


def test_same_first_200_chars_is_one_wording(tmp_path):
    head = "x" * 200
    signals.record_unknown(head + " first tail", "codex", "proj", "retried", home=tmp_path)
    signals.record_unknown(head + " other tail", "codex", "proj", "retried", home=tmp_path)
    signals.record_unknown("a different unknown wording", "codex", "proj", "retried", home=tmp_path)
    got = rows(tmp_path)
    assert [r["count"] for r in got] == [2, 1]


def test_secret_looking_token_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-value-example-0001")
    token = "sk-ant-fakeexampletoken0123456789abcdef"
    text = f"odd failure with key {token} and env dummy-value-example-0001"
    signals.record_unknown(text, "claude_cli", "proj", "parked", home=tmp_path)
    raw = (tmp_path / "unknown.jsonl").read_text(encoding="utf-8")
    assert token not in raw and "dummy-value-example-0001" not in raw
    assert "REDACTED" in raw


def test_text_is_cut_to_2000(tmp_path):
    signals.record_unknown("q" * 5000, "claude_cli", "proj", "retried", home=tmp_path)
    assert len(rows(tmp_path)[0]["text"]) == 2000


def test_cause_from_gate_problem_shapes():
    assert signals.cause_of("PROBLEM: outside files_in_scope: ['x.py']") == "scope"
    assert signals.cause_of("$ pytest -q\n(exit 1)\nFAILED tests/test_a.py::test_b") == "tests"
    assert signals.cause_of(UNKNOWN) == "unknown"
    assert set(signals.CAUSES) == {"scope", "tests", "environment", "limit", "infra", "unknown"}


def test_autopilot_home_is_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    signals.record_unknown(UNKNOWN, "claude_cli", "proj", "healed")
    assert rows(tmp_path)[0]["action"] == "healed"
