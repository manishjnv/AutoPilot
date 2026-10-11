"""N3, P03-T02: detect_runner finds the first installed and logged-in agent CLI on PATH."""
import json
import os
import sys
import time

import pytest

from autopilot import doctor
from autopilot.doctor import RUNNERS, detect_runner

FAKE = (
    "import json,sys,time\n"
    "mode, log = sys.argv[1], sys.argv[2]\n"
    "open(log, 'a', encoding='utf-8').write(json.dumps(sys.argv[3:]) + '\\n')\n"
    "if mode == 'hang': time.sleep(60)\n"
    "if mode == 'in': print('Logged in as fake-user@example.com'); sys.exit(0)\n"
    "if mode == 'out0': print('Not logged in'); sys.exit(0)\n"
    "print('Not logged in. Run login first.'); sys.exit(1)\n")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    """No real key from this machine may count: every key variable of RUNNERS is removed."""
    for _, _, _, keys in RUNNERS:
        for k in keys:
            monkeypatch.delenv(k, raising=False)


def fake_bin(tmp_path, **modes):
    """A tmp PATH folder with one fake CLI per name; mode is `in`, `out`, `out0` or `hang`. Each call is logged."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "fake.py").write_text(FAKE)
    for name, mode in modes.items():
        log = tmp_path / f"{name}.log"
        if sys.platform == "win32":
            (bindir / f"{name}.cmd").write_text(f'@"{sys.executable}" "%~dp0fake.py" {mode} "{log}" %*\n')
        else:
            exe = bindir / name
            exe.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" \"{bindir / 'fake.py'}\" {mode} \"{log}\" \"$@\"\n")
            exe.chmod(0o755)
    return str(bindir)


def calls(tmp_path, name):
    log = tmp_path / f"{name}.log"
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def env_with(path, **extra):
    return {**os.environ, "PATH": path, **extra}


def test_only_kiro_logged_in(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "in"})
    assert detect_runner(env_with(path)) == "kiro"
    assert calls(tmp_path, "kiro-cli") == [["whoami"]]


def test_claude_logged_out_falls_through_to_kiro(tmp_path):
    path = fake_bin(tmp_path, claude="out", **{"kiro-cli": "in"})
    assert detect_runner(env_with(path)) == "kiro"
    assert calls(tmp_path, "claude") == [["auth", "status"]]


def test_order_is_respected(tmp_path):
    path = fake_bin(tmp_path, claude="in", **{"kiro-cli": "in"})
    assert detect_runner(env_with(path)) == "claude_cli"
    assert calls(tmp_path, "kiro-cli") == []  # never asked: claude came first


def test_empty_path_is_none(tmp_path):
    assert detect_runner({"PATH": ""}) is None
    assert detect_runner({}) is None
    assert detect_runner(env_with(str(tmp_path))) is None  # a folder with no agent CLI


def test_hanging_login_check_is_stopped_by_the_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "LOGIN_TIMEOUT", 1)
    path = fake_bin(tmp_path, **{"kiro-cli": "hang", "cursor-agent": "in"})
    start = time.monotonic()
    assert detect_runner(env_with(path)) == "cursor"
    assert time.monotonic() - start < 30
    assert calls(tmp_path, "cursor-agent") == [["status"]]


def test_logged_out_wording_with_exit_0_is_not_logged_in(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "out0", "codex": "in"})
    assert detect_runner(env_with(path)) == "codex"
    assert calls(tmp_path, "codex") == [["login", "status"]]


def test_key_variable_counts_without_a_status_command(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "out", "gemini": "out", "aider": "out"})
    assert detect_runner(env_with(path)) is None  # gemini and aider have no status command and no key
    assert detect_runner(env_with(path, GEMINI_API_KEY="fake-example-key")) == "gemini"
    assert detect_runner(env_with(path, KIRO_API_KEY="fake-example-key")) == "kiro"
    assert detect_runner(env_with(path, OPENROUTER_API_KEY="")) is None  # an empty key does not count
    assert calls(tmp_path, "gemini") == [] and calls(tmp_path, "aider") == []


def test_claude_key_counts(tmp_path):
    path = fake_bin(tmp_path, claude="out", **{"kiro-cli": "in"})
    assert detect_runner(env_with(path, ANTHROPIC_API_KEY="fake-example-key")) == "claude_cli"
    assert calls(tmp_path, "claude") == []  # key first: no process


def test_never_starts_a_login(tmp_path):
    names = {b: "out" for b, _, _, _ in RUNNERS}
    path = fake_bin(tmp_path, **names)
    assert detect_runner(env_with(path)) is None
    for name in names:
        for argv in calls(tmp_path, name):
            assert argv[:1] != ["login"] or argv == ["login", "status"]
            assert "--with-api-key" not in argv


# ---- N3, P03-T03: preflight writes the detected runner to project.yaml
import shutil  # noqa: E402
import subprocess  # noqa: E402

from autopilot.cli import main as cli_main  # noqa: E402
from autopilot.cli import preflight, runner_set  # noqa: E402
from autopilot.config import Config  # noqa: E402


def only_path(monkeypatch, tmp_path, path):
    """PATH is only `path`; no explicit claude binary and no ~/.local/bin/claude from this machine."""
    monkeypatch.setenv("PATH", path)
    for k in ("AUTOPILOT_CLAUDE_BIN", "AUTODEV_CLAUDE_BIN"):
        monkeypatch.delenv(k, raising=False)
    home = tmp_path / "home-example"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


def init_project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    assert cli_main(["init", "-C", str(root), "--stack", "generic"]) == 0
    return root, root / ".agent" / "project.yaml"


def test_template_leaves_backend_unset_and_defaults_stay_claude(tmp_path):
    root, pj = init_project(tmp_path)
    assert not runner_set(root)
    from autopilot.config import TEMPLATES
    assert "  # backend: claude_cli" in (TEMPLATES / "agent" / "project.yaml").read_text(encoding="utf-8")
    cfg = Config.load(root)
    assert cfg.get("agent.backend") == "claude_cli"
    assert not [e for e in cfg.validate() if "agent.backend" in e]
    from autopilot.backends import get_backend
    from autopilot.backends.claude_cli import ClaudeCLIBackend
    assert isinstance(get_backend(cfg), ClaudeCLIBackend)


def test_preflight_writes_kiro_and_keeps_comments(tmp_path, monkeypatch, capsys):
    root, pj = init_project(tmp_path)
    before = pj.read_text(encoding="utf-8")
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, **{"kiro-cli": "in"}))
    assert preflight(Config.load(root)) is True
    text = pj.read_text(encoding="utf-8")
    assert "runner: kiro-cli (found on PATH)" in capsys.readouterr().out
    assert "  backend: command\n  preset: kiro\n" in text
    assert text.count("#") == before.count("#") and "# Commands the orchestrator runs itself" in text
    cfg = Config.load(root)
    assert (cfg.get("agent.backend"), cfg.get("agent.preset")) == ("command", "kiro")
    assert runner_set(root) and not [e for e in cfg.validate() if "agent" in e]
    assert preflight(cfg) is True and pj.read_text(encoding="utf-8") == text  # second run: no change


@pytest.mark.parametrize("agent", ["agent:\n  backend: claude_cli\n", "agent:\n  backend: command\n  preset: codex\n",
                                   "agent:\n  preset: gemini   # no backend: left alone\n"])
def test_preflight_never_changes_a_set_runner(tmp_path, monkeypatch, agent):
    root = tmp_path / "proj"
    (root / ".agent").mkdir(parents=True)
    pj = root / ".agent" / "project.yaml"
    pj.write_bytes(f"# my settings\nname: demo\n{agent}".encode())
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, **{"kiro-cli": "in"}))
    preflight(Config.load(root))
    assert pj.read_bytes() == f"# my settings\nname: demo\n{agent}".encode()
    assert calls(tmp_path, "kiro-cli") == []  # not even detected


def test_no_runner_on_path_prints_the_install_command(tmp_path, monkeypatch, capsys):
    root, pj = init_project(tmp_path)
    before = pj.read_bytes()
    empty = tmp_path / "empty-bin-example"
    empty.mkdir()
    only_path(monkeypatch, tmp_path, str(empty))
    assert preflight(Config.load(root)) is False
    out = capsys.readouterr().out
    assert doctor.INSTALL["native"][1] in out and "no agent CLI found" in out
    assert "kiro-cli, cursor-agent, codex, gemini, aider" in out
    assert pj.read_bytes() == before


def test_remember_runner_without_agent_block_and_claude(tmp_path):
    from autopilot.cli import remember_runner
    pj = tmp_path / "project.yaml"
    pj.write_text("# top comment\nname: demo\ncommands:\n  test: []", encoding="utf-8")
    assert remember_runner(pj, "claude_cli")
    import yaml
    d = yaml.safe_load(pj.read_text(encoding="utf-8"))
    assert d == {"name": "demo", "commands": {"test": []}, "agent": {"backend": "claude_cli"}}
    assert pj.read_text(encoding="utf-8").startswith("# top comment\n")
    pj.write_text("name: demo\nagent: {permission_mode: dontAsk}\n", encoding="utf-8")  # flow style: never edited
    assert not remember_runner(pj, "kiro")
    assert pj.read_text(encoding="utf-8") == "name: demo\nagent: {permission_mode: dontAsk}\n"


KIRO = r"""import json, pathlib, sys
if sys.argv[1:2] == ["whoami"]:
    print("Logged in as fake-user@example.com"); sys.exit(0)
prompt = sys.stdin.read()
pathlib.Path("hello.txt").write_text("hello\n", encoding="utf-8")
rep = {"status": "done", "summary": "wrote hello.txt", "files_changed": ["hello.txt"], "tests_added": [],
       "docs_updated": [], "decisions": [], "followups": []}
print("done\n```json\n" + json.dumps(rep) + "\n```")
"""

SMOKE_YAML = """# smoke project (comments must stay)
name: smoke
commands:
  test: {test}
audit:
  every_n_phases: 0
replan:
  every_n_phases: 0
budget_usd:
  wait_for_next_day: false
needs_you:
  wait: false
agent:
  # backend: claude_cli   # unset: preflight detects
  session_timeout_sec: 300
"""


def kiro_bin(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "kiro.py").write_text(KIRO, encoding="utf-8")
    if sys.platform == "win32":
        (bindir / "kiro-cli.cmd").write_text(f'@"{sys.executable}" "%~dp0kiro.py" %*\n')
    else:
        exe = bindir / "kiro-cli"
        exe.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" \"{bindir / 'kiro.py'}\" \"$@\"\n")
        exe.chmod(0o755)
    git = shutil.which("git")
    assert git, "git is needed for the smoke test"
    try:
        if sys.platform == "win32":
            raise OSError("Git for Windows needs its own folder")
        os.symlink(git, bindir / os.path.basename(git))
        return str(bindir)
    except OSError:  # Windows, or no symlink right: the real git's folder goes last
        return str(bindir) + os.pathsep + os.path.dirname(git)


def test_smoke_fake_kiro_runs_one_task_end_to_end(tmp_path, monkeypatch, capsys):
    from autopilot.orchestrator import Orchestrator
    root, pj = init_project(tmp_path)  # init also git-ignores .agent/state*
    test = '"' + sys.executable + '" -c "import pathlib,sys; sys.exit(0 if pathlib.Path(\'hello.txt\').exists() else 1)"'
    pj.write_text(SMOKE_YAML.replace("{test}", json.dumps([test])), encoding="utf-8")
    plan = {"goal": "smoke", "phases": [{"id": "P01", "title": "One", "tasks": [
        {"id": "P01-T01", "title": "write hello.txt", "risk": "low", "acceptance_criteria": ["hello.txt exists"]}]}]}
    import yaml
    (root / ".agent" / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    only_path(monkeypatch, tmp_path, kiro_bin(tmp_path))
    assert preflight(Config.load(root)) is True
    assert "runner: kiro-cli (found on PATH)" in capsys.readouterr().out
    text = pj.read_text(encoding="utf-8")
    assert "agent.preset" not in text and "  preset: kiro\n" in text and "# smoke project (comments must stay)" in text
    from autopilot.backends import get_backend
    from autopilot.backends.command import CommandBackend
    assert isinstance(get_backend(Config.load(root)), CommandBackend)
    orch = Orchestrator(root, sleep=lambda s: None, max_sessions=1)
    orch.run()
    assert orch.state.task("P01-T01")["status"] == "done"
    assert (root / "hello.txt").exists()
