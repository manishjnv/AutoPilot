"""W33: a read-only command may fall back to the last project; a spending one never does silently."""
from autopilot import cli
from autopilot.cli import main as cli_main
from test_autopilot import make_project, phases_basic


def setup(tmp_path, monkeypatch):
    root = make_project(tmp_path, phases_basic())
    assert cli_main(["status", "-C", str(root)]) == 0  # now the last project used
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    started = []
    monkeypatch.setattr(cli, "start_detached", lambda r, a: started.append((r, a)) or 0)
    monkeypatch.setattr(cli, "_tty", lambda: False)
    return root, started


def test_status_prints_the_last_used_line_first(tmp_path, monkeypatch, capsys):
    root, _ = setup(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cli_main(["status"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"project: {root} (last used)"


def test_start_without_a_terminal_exits_3_with_the_hint(tmp_path, monkeypatch, capsys):
    root, started = setup(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cli_main(["start"]) == 3
    out = capsys.readouterr().out
    assert f"project: {root} (last used)" in out and "name the project with -C <folder>" in out
    assert started == []


def test_yes_and_dash_c_skip_the_question(tmp_path, monkeypatch):
    root, started = setup(tmp_path, monkeypatch)
    assert cli_main(["start", "--yes"]) == 0
    assert cli_main(["start", "-C", str(root)]) == 0
    assert len(started) == 2


def test_a_terminal_gets_the_question(tmp_path, monkeypatch, capsys):
    root, started = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "_tty", lambda: True)
    asked = []
    monkeypatch.setattr(cli, "_ask", lambda p: asked.append(p) or "n")
    assert cli_main(["start"]) == 1 and started == []
    assert asked == [f"Build {root}? [y/N] "]
    monkeypatch.setattr(cli, "_ask", lambda p: "y")
    assert cli_main(["start"]) == 0 and len(started) == 1
