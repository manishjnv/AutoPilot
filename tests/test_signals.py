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


# ---------- W29b: ap audit --signals
from datetime import date, timedelta  # noqa: E402

from autopilot.cli import main  # noqa: E402
from autopilot.state import State  # noqa: E402


def make_project(home, name, events):
    root = home / name
    (root / ".agent").mkdir(parents=True)
    (root / ".agent" / "project.yaml").write_text("project: {name: example}\n", encoding="utf-8")
    st = State(root / ".agent" / "state.db")
    for kind, msg in events:
        st.event(kind, msg)
    st.db.close()
    with open(home / "recent", "a", encoding="utf-8") as fh:
        fh.write(f"{root}\n")
    return root


def write_unknown(home, rows_):
    (home / "unknown.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_), encoding="utf-8")


def section(out, title):
    """{name: count} of one table section."""
    lines = out.split(title + "\n", 1)[1].split("\n\n", 1)[0].splitlines()[1:]
    return {ln.split(None, 1)[1]: int(ln.split(None, 1)[0]) for ln in lines}


def test_signals_table_counts_from_fixtures(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    today, old = date.today().isoformat(), (date.today() - timedelta(days=90)).isoformat()
    write_unknown(tmp_path, [
        {"date": today, "cause": "unknown", "text": UNKNOWN, "count": 3},
        {"date": today, "cause": "unknown", "text": UNKNOWN, "count": 2},
        {"date": today, "cause": "scope", "text": "PROBLEM: outside files_in_scope: ['y.py'] " + "z" * 200, "count": 1},
        {"date": old, "cause": "unknown", "text": "an old wording out of the window", "count": 9},
    ])
    make_project(tmp_path, "proj", [
        ("task_blocked", "P1-T1 Add x parked after 3 attempts: PROBLEM: outside files_in_scope: ['a.py']"),
        ("quality", "P1-T1 · sonnet · high · attempts 3 · reworked Y · 10k tokens"),
        ("task_blocked", "P1-T2 Add y parked after 2 attempts: $ pytest -q\n(exit 1)\nFAILED tests/test_a.py::test_b"),
        ("quality", "P1-T2 · sonnet · medium · attempts 2 · reworked Y · 5k tokens"),
        ("task_blocked", "P1-T3 Add z parked after 3 attempts: REVIEW of the high task found problems (fix them):"),
        ("quality", "P1-T4 · opus · high · attempts 2 · reworked Y · 8k tokens"),
        ("quality", "P1-T5 · opus · low · attempts 1 · reworked N · 1k tokens"),
        ("quality", "after 20 tasks, model ladder suggestions (see REPORT.md):\n- x"),
    ])
    assert main(["audit", "--signals"]) == 0
    out = capsys.readouterr().out
    assert f"    5  unknown  {UNKNOWN}" in out
    assert "    1  scope    PROBLEM: outside files_in_scope: ['y.py'] " + "z" * 38 + "\n" in out  # 80 characters
    assert "old wording" not in out
    assert section(out, "Parked by cause") == {"scope": 1, "tests": 1, "unknown": 1}
    assert section(out, "Gate failures by kind") == {"scope": 1, "tests": 1, "review": 1}
    assert section(out, "Retries by cause") == {"scope": 2, "tests": 1, "recovered": 1}


def test_parked_task_retries_are_not_recovered():
    t = signals.tally([], [[("task_blocked", "P1-T1 Add x parked after 3 attempts: " + UNKNOWN),
                            ("quality", "P1-T1 · sonnet · high · attempts 3 · reworked Y · 10k tokens")]])
    assert t["retries"] == {"unknown": 2}


def test_same_task_id_in_two_projects_is_tallied_per_project(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    make_project(tmp_path, "proj_a", [
        ("task_blocked", "P01-T01 Add x parked after 3 attempts: PROBLEM: outside files_in_scope: ['a.py']"),
        ("quality", "P01-T01 · sonnet · high · attempts 3 · reworked Y · 10k tokens")])
    make_project(tmp_path, "proj_b", [("quality", "P01-T01 · opus · high · attempts 4 · reworked Y · 9k tokens")])
    assert main(["audit", "--signals"]) == 0
    assert section(capsys.readouterr().out, "Retries by cause") == {"recovered": 3, "scope": 2}


def test_signals_no_data_prints_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    assert main(["audit", "--signals", "--days", "7"]) == 0
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1 and "No signals in the last 7 days" in out


def test_signals_skips_missing_project_with_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    write_unknown(tmp_path, [{"date": date.today().isoformat(), "cause": "unknown", "text": UNKNOWN, "count": 1}])
    root = tmp_path / "nodb"
    (root / ".agent").mkdir(parents=True)
    (root / ".agent" / "project.yaml").write_text("project: {name: example}\n", encoding="utf-8")
    (tmp_path / "recent").write_text(f"{root}\n", encoding="utf-8")
    assert main(["audit", "--signals"]) == 0
    out = capsys.readouterr().out
    assert out.count("skipped: nodb") == 1 and f"    1  unknown  {UNKNOWN}" in out
    assert not (root / ".agent" / "state.db").exists()  # read-only: nothing created


def test_gate_kind_names_the_gate_check():
    assert signals.gate_kind("the session produced no file changes") == "no_change"
    assert signals.gate_kind("possible Anthropic key added: sk-a…") == "secret"
    assert signals.gate_kind("file grew past the budget: a.py 300 -> 500 lines (limit 400). Split") == "growth"
    assert signals.gate_kind("it is possible that nothing happened") == "other"
