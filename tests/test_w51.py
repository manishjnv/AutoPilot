"""W51: ap report --issue, the slow-steps table and the failed-trace fixtures."""
import json
import os
import stat
import time
from datetime import datetime
from pathlib import Path

import pytest

from autopilot import signals
from autopilot.cli import main

TRACES = Path(__file__).parent / "fixtures" / "traces"


@pytest.mark.parametrize("f", sorted(TRACES.glob("*.jsonl")), ids=lambda f: f.name)
def test_every_trace_keeps_its_cause(f):
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows
    for r in rows:
        assert signals.cause_of(r["text"]) == r["cause"], r["text"]


def project(tmp_path, log_lines=()):
    root = tmp_path / "proj"
    (root / ".agent" / "logs").mkdir(parents=True)
    (root / ".agent" / "project.yaml").write_text("project: {name: example}\n", encoding="utf-8")
    (root / ".agent" / "run.json").write_text(json.dumps({"outcome": "VERIFIED"}), encoding="utf-8")
    (root / ".agent" / "logs" / "autopilot.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return root


LEAKY = ["leak /home/bob/x", "leak C:\\Users\\bob\\x", "leak /Users/bob/x", "mail bob@example.com"]


def test_issue_show_has_outcome_and_no_path_or_at(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    root = project(tmp_path, ["fine line", *LEAKY, "token sk-ant-fakeexampletoken0123456789abcdef"])
    assert main(["report", "--issue", "--show", "-C", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Outcome: VERIFIED" in out and "fine line" in out
    assert "@" not in out and "/home/" not in out and "Users" not in out and "sk-ant" not in out


def fake_gh(tmp_path, monkeypatch, auth_rc):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    gh = bin_ / "gh"
    gh.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/gh.argv"\n[ "$1 $2" = "auth status" ] && exit {auth_rc}\nexit 0\n')
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return tmp_path / "gh.argv"


@pytest.mark.skipif(os.name == "nt", reason="the fake gh is a shell script")
def test_issue_calls_gh_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    argv = fake_gh(tmp_path, monkeypatch, 0)
    assert main(["report", "--issue", "-C", str(project(tmp_path))]) == 0
    calls = argv.read_text().splitlines()
    assert [c for c in calls if c.startswith("issue create")] and len([c for c in calls if c.startswith("issue create")]) == 1
    assert "--body-file" in calls[-1] and "manishjnv/AutoPilot" in calls[-1]


def test_issue_without_gh_prints_copy_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda *_: None)
    assert main(["report", "--issue", "-C", str(project(tmp_path))]) == 0
    assert "gh is not logged in; copy the file into a new issue at https://github.com/manishjnv/AutoPilot/issues/new" in capsys.readouterr().out


def test_slow_steps_two_tasks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    t0 = time.time() - 600

    def ts(s):
        return datetime.fromtimestamp(t0 + s).strftime("%Y-%m-%d %H:%M:%S")

    def task(tid, sid, base, edit, test, last, done):
        return [f"{ts(base)} INFO session #{sid} task {tid} model=haiku attempt=1",
                f"{ts(base + edit)} INFO   ▸ {tid} a [haiku] · Write /x/x.py · 0m10s",
                f"{ts(base + test)} INFO   ▸ {tid} a [haiku] · Bash pytest -q · 0m10s",
                f"{ts(base + last)} INFO   ▸ {tid} a [haiku] · Write /x/y.py · 0m10s",
                f"{ts(base + done)} INFO task {tid} done"]
    root = project(tmp_path, task("P1-T1", 1, 0, 10, 40, 60, 70) + task("P1-T2", 2, 100, 30, 100, 120, 140))
    assert main(["audit", "--signals", "-C", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Slow steps" in out
    row = [ln for ln in out.splitlines() if ln.split()[-2:-1] == ["write"] or " write " in ln][0]
    assert row.split() == ["50", "write", "P1-T2"]  # median of 30 and 70 seconds


def test_slow_steps_skipped_without_marks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    (tmp_path / "unknown.jsonl").write_text(json.dumps({"date": "2999-01-01", "cause": "unknown", "text": "x", "count": 1}) + "\n")
    assert main(["audit", "--signals", "-C", str(project(tmp_path))]) == 0
    assert "skipped: no step marks" in capsys.readouterr().out
