import json

from autopilot import cli


def line(content, model="claude-sonnet-fake"):
    return json.dumps({"message": {"role": "assistant", "model": model, "content": content,
                                   "usage": {"input_tokens": 1000, "output_tokens": 500}}})


def call(i, cmd):
    return line([{"type": "tool_use", "id": i, "name": "Bash", "input": {"command": cmd}}])


def result(i, err=True):
    return json.dumps({"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": i, "is_error": err, "content": "boom"}]}})


def make_home(tmp_path):
    d = tmp_path / ".claude" / "projects" / "-home-example-demo"
    d.mkdir(parents=True)
    ls = []
    for n in range(3):
        ls += [call(f"t{n}", "make secretcmd-example"), result(f"t{n}")]
    (d / "a.jsonl").write_text("\n".join(ls + ["not json", "[1]", '{"message": 5}']), encoding="utf-8")
    (d / "b.jsonl").write_text("\n".join([call("x", "ls"), result("x", False)]), encoding="utf-8")
    (d / "c.jsonl").write_text(line("hello secret prompt example", model="unknown-fake"), encoding="utf-8")
    return tmp_path / ".claude"


def test_history_counts_repeat_and_hides_text(tmp_path, capsys, monkeypatch):
    home = make_home(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)  # no project here
    before = sorted(p.name for p in tmp_path.rglob("*"))
    assert cli.main(["audit", "--history", "--home", str(home)]) == 0
    out = capsys.readouterr().out
    assert "secretcmd" not in out and "secret prompt" not in out
    row = [ln for ln in out.splitlines() if ln.startswith("Total")][0].split()
    assert row[1] == "3" and row[5] == "1" and float(row[6]) > 0
    assert "Retries cost about $" in out
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_history_missing_home(tmp_path, capsys):
    assert cli.main(["audit", "--history", "--home", str(tmp_path / "nope")]) == 0
    assert capsys.readouterr().out.strip() == "No Claude Code history found."


def test_plain_audit_keeps_completion_kind(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "remember", lambda p: None)
    monkeypatch.setattr("autopilot.upgrade.auto_update", lambda *a, **k: None)
    monkeypatch.setattr(cli, "cmd_review", lambda a: seen.update(kind=a.kind, history=a.history) or 0)
    cli.main(["audit", "-C", str(tmp_path)])
    assert seen == {"kind": "completion", "history": False}
