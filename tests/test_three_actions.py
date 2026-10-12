"""N5.5: the three-action path: auto-start, open the page once, the idea from a file."""
import pytest
import yaml

from autopilot import cli
from autopilot.cli import idea_file, main as cli_main
from test_quickstart import adopt_folder, guided


def fake_quickstart(monkeypatch, risk="low", owner_only=False):
    """cmd_quickstart without a model: writes a one-task plan and records the idea."""
    seen = {}

    def fake(args):
        seen["idea"] = args.idea
        agent = cli.Path(args.path) / ".agent"
        agent.mkdir(parents=True, exist_ok=True)
        task = {"id": "P01-T01", "title": "first", "acceptance_criteria": ["ok"], "risk": risk, "owner_only": owner_only}
        (agent / "plan.yaml").write_text(yaml.safe_dump({"version": 1, "goal": "g", "phases": [
            {"id": "P01", "title": "All", "goal": "g", "tasks": [task]}]}))
        return 0
    monkeypatch.setattr("autopilot.cli.cmd_quickstart", fake)
    return seen


def run_calls(monkeypatch):
    calls = []
    monkeypatch.setattr("autopilot.cli.cmd_run", lambda a: calls.append(a.path) or 0)
    return calls


def test_a_plain_plan_starts_without_the_question(tmp_path, monkeypatch, capsys):
    guided(tmp_path, monkeypatch, ["a todo app", ""])  # idea, folder; a third input() would fail
    fake_quickstart(monkeypatch)
    calls = run_calls(monkeypatch)
    assert cli_main([]) == 0
    out = capsys.readouterr().out
    assert len(calls) == 1 and "Starting. Stop with ap stop." in out
    assert "Done: 0 of 1 tasks." in out and "Open: 1." in out and "Next: P01-T01 first" in out
    assert "1  start now" not in out


@pytest.mark.parametrize("kw", [{"risk": "critical"}, {"owner_only": True}])
def test_a_critical_or_owner_task_keeps_the_question(tmp_path, monkeypatch, capsys, kw):
    guided(tmp_path, monkeypatch, ["a todo app", "", "2"])
    fake_quickstart(monkeypatch, **kw)
    calls = run_calls(monkeypatch)
    assert cli_main([]) == 0
    assert calls == [] and "1  start now" in capsys.readouterr().out


def test_ask_keeps_the_question(tmp_path, monkeypatch, capsys):
    guided(tmp_path, monkeypatch, ["a todo app", "", "2"])
    fake_quickstart(monkeypatch)
    calls = run_calls(monkeypatch)
    assert cli_main(["--ask"]) == 0
    assert calls == [] and "1  start now" in capsys.readouterr().out


def test_an_adopted_project_keeps_the_question(tmp_path, monkeypatch, capsys):
    adopt_folder(tmp_path, monkeypatch, ["2"])
    calls = run_calls(monkeypatch)
    assert cli_main([]) == 0
    assert calls == [] and "1  start now" in capsys.readouterr().out


def test_idea_md_is_the_idea_and_nothing_is_asked(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, [])  # any input() fails the test
    (work / "IDEA.md").write_text("A todo app with due dates.\n")
    seen = fake_quickstart(monkeypatch)
    calls = run_calls(monkeypatch)
    assert cli_main([]) == 0
    assert seen["idea"] == "A todo app with due dates." and calls == [str(work.resolve())]


def test_the_idea_file_rule(tmp_path):
    assert idea_file(tmp_path) == ""
    (tmp_path / "notes.md").write_text("one two three")
    assert idea_file(tmp_path) == "one two three"
    (tmp_path / "two.md").write_text("x")
    assert idea_file(tmp_path) == ""  # two .md files and no IDEA.md
    (tmp_path / "IDEA.md").write_text("the idea")
    assert idea_file(tmp_path) == "the idea"
    (tmp_path / "IDEA.md").unlink()
    (tmp_path / "two.md").unlink()
    (tmp_path / "app.py").write_text("print(1)")
    assert idea_file(tmp_path) == ""  # code beside the document
    (tmp_path / "app.py").unlink()
    (tmp_path / "notes.md").write_text("word " * 2000)
    assert idea_file(tmp_path) == ""  # too long


def page_env(monkeypatch, ssh=False):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, new=0: opened.append(url))
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    if ssh:
        monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5 6.7.8.9 22")
    return opened


def test_the_page_opens_once_per_project(tmp_path, monkeypatch):
    (tmp_path / ".agent").mkdir()
    opened = page_env(monkeypatch)
    cli.open_page_once(tmp_path, "http://127.0.0.1:8765/")
    cli.open_page_once(tmp_path, "http://127.0.0.1:8765/")
    assert opened == ["http://127.0.0.1:8765/"]


def test_an_ssh_session_does_not_open_the_page(tmp_path, monkeypatch):
    (tmp_path / ".agent").mkdir()
    opened = page_env(monkeypatch, ssh=True)
    cli.open_page_once(tmp_path, "http://127.0.0.1:8765/")
    assert opened == [] and not (tmp_path / ".agent" / "page_opened").exists()
