import subprocess
import sys

from todo.cli import main


def run(tmp_path, *args):
    env = {"TODO_FILE": str(tmp_path / "t.json"), "PATH": ""}
    return subprocess.run([sys.executable, "-m", "todo", *args],
                          capture_output=True, text=True, env=env)


def test_end_to_end_subprocess(tmp_path):
    assert run(tmp_path, "add", "milk").stdout.strip() == "Added 1"
    run(tmp_path, "add", "eggs")
    assert run(tmp_path, "done", "1").returncode == 0
    out = run(tmp_path, "list").stdout.splitlines()
    assert out == ["1 [x] milk", "2 [ ] eggs"]


def test_done_missing_id(tmp_path):
    r = run(tmp_path, "done", "9")
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_main_argv_and_default_file(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TODO_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["add", "x"]) == 0
    assert (tmp_path / "todo.json").exists()
    main(["list"])
    assert "1 [ ] x" in capsys.readouterr().out
