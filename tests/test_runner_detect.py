"""N3, P03-T02: detect_runner finds the first installed and logged-in agent CLI on PATH."""
import json
import os
import sys
import time
from pathlib import Path

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
    """No real key from this machine may count: every token variable of the runner table is removed."""
    for row in RUNNERS:
        for k in row.tokens:
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
    path = fake_bin(tmp_path, codex="hang", agent="in")
    start = time.monotonic()
    assert detect_runner(env_with(path)) == "cursor"
    assert time.monotonic() - start < 30
    assert calls(tmp_path, "agent") == [["status"]]


def test_cursor_is_found_under_its_new_name_and_its_old_one(tmp_path):
    """Q1: Cursor renamed the binary from cursor-agent to agent; both count, the new name first."""
    assert detect_runner(env_with(fake_bin(tmp_path, agent="in"))) == "cursor"
    old = tmp_path / "old"
    old.mkdir()
    path = fake_bin(old, **{"cursor-agent": "in"})
    assert detect_runner(env_with(path)) == "cursor"
    assert Path(doctor.runner("cursor").which(path)).stem == "cursor-agent"  # .cmd on Windows


def test_logged_out_wording_with_exit_0_is_not_logged_in(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "out0", "codex": "in"})
    assert detect_runner(env_with(path)) == "codex"
    assert calls(tmp_path, "codex") == [["login", "status"]]


def test_token_variable_counts_and_api_key_runners_are_no_rows(tmp_path):
    path = fake_bin(tmp_path, **{"kiro-cli": "out", "gemini": "out", "aider": "out"})
    assert detect_runner(env_with(path)) is None
    assert detect_runner(env_with(path, GEMINI_API_KEY="fake-example-key")) is None  # API key only: not a row (Q1)
    assert detect_runner(env_with(path, KIRO_API_KEY="fake-example-key")) == "kiro"
    assert detect_runner(env_with(path, KIRO_API_KEY="")) is None  # an empty token does not count
    assert calls(tmp_path, "gemini") == [] and calls(tmp_path, "aider") == []
    assert {r.key for r in RUNNERS} == {"claude_cli", "copilot", "codex", "cursor", "kiro"}


def test_claude_key_counts(tmp_path):
    path = fake_bin(tmp_path, claude="out", **{"kiro-cli": "in"})
    assert detect_runner(env_with(path, ANTHROPIC_API_KEY="fake-example-key")) == "claude_cli"
    assert calls(tmp_path, "claude") == []  # key first: no process


def test_never_starts_a_login(tmp_path):
    names = {r.binary: "out" for r in RUNNERS}
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


# ---- N10: login preflight per runner (subscription login only)
def test_preflight_stops_with_the_login_line_when_the_runner_is_logged_out(tmp_path, monkeypatch, capsys):
    root, pj = init_project(tmp_path)
    pj.write_text(pj.read_text(encoding="utf-8").replace("\nagent:\n", "\nagent:\n  backend: command\n  preset: codex\n", 1), encoding="utf-8")
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, codex="out"))
    assert preflight(Config.load(root)) is False
    out = capsys.readouterr().out
    assert "FAIL  runner login: codex is not logged in: run `codex login`" in out
    assert calls(tmp_path, "codex") == [["login", "status"]]  # the check only; never the login itself


def test_preflight_passes_a_logged_in_runner_and_names_api_key_runners(tmp_path, monkeypatch, capsys):
    from autopilot.doctor import WARN, check_runner_login
    root, pj = init_project(tmp_path)
    pj.write_text(pj.read_text(encoding="utf-8").replace("\nagent:\n", "\nagent:\n  backend: command\n  preset: codex\n", 1), encoding="utf-8")
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, codex="in"))
    monkeypatch.setattr("autopilot.cli.install_deps", lambda cfg: True)
    assert preflight(Config.load(root)) is True
    assert "runner login: codex logged in" in capsys.readouterr().out
    cfg = Config.load(root)
    cfg.data["agent"]["preset"] = "gemini"
    level, _, detail = check_runner_login(cfg)
    assert level == WARN and "needs an API key, not supported" in detail


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
    assert "no agent CLI found" in out and "Install Claude Code" not in out  # Q1: neutral
    for row in RUNNERS:  # five runners, each with its install command for this system
        assert row.name in out and row.install_cmd() in out
    assert out.index("claude") < out.index("copilot") and doctor.VSCODE_SENTENCE in out
    assert pj.read_bytes() == before


def test_installed_but_logged_out_runner_names_only_its_login(tmp_path, monkeypatch, capsys):
    root, _ = init_project(tmp_path)
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, codex="out"))
    assert preflight(Config.load(root)) is False
    out = capsys.readouterr().out
    assert "codex is installed but not logged in: run `codex login`" in out and "no agent CLI found" not in out


def test_copilot_login_counts_a_token_then_gh_auth_status(tmp_path, monkeypatch, capsys):
    """Q2: copilot has no prompt-free status command: a token variable counts, else `gh auth status` exit 0."""
    root, pj = init_project(tmp_path)
    pj.write_text(pj.read_text(encoding="utf-8").replace("\nagent:\n", "\nagent:\n  backend: command\n  preset: copilot\n", 1), encoding="utf-8")
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, copilot="out", gh="out"))
    assert not [e for e in Config.load(root).validate() if "agent" in e]  # `ap validate` passes
    assert preflight(Config.load(root)) is False
    assert "FAIL  runner login: copilot is not logged in: run `copilot login`" in capsys.readouterr().out
    assert calls(tmp_path, "gh") == [["auth", "status"]] and calls(tmp_path, "copilot") == []
    monkeypatch.setattr("autopilot.cli.install_deps", lambda cfg: True)
    monkeypatch.setenv("GH_TOKEN", "fake-example-token")
    assert preflight(Config.load(root)) is True
    assert "copilot logged in" in capsys.readouterr().out and len(calls(tmp_path, "gh")) == 1  # the token: no process
    monkeypatch.delenv("GH_TOKEN")
    (tmp_path / "b").mkdir()
    only_path(monkeypatch, tmp_path / "b", fake_bin(tmp_path / "b", copilot="out", gh="in"))
    assert preflight(Config.load(root)) is True
    (tmp_path / "c").mkdir()
    only_path(monkeypatch, tmp_path / "c", fake_bin(tmp_path / "c", copilot="out"))  # no gh at all
    assert preflight(Config.load(root)) is False


def test_doctor_says_runner_none_when_no_runner_is_chosen(tmp_path, monkeypatch):
    """Q1: `ap doctor` on a machine that never chose Claude never asks for `claude login`."""
    from autopilot.doctor import WARN, checks
    root, _ = init_project(tmp_path)
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, codex="out"))
    rows = {name: (level, detail) for level, name, detail in checks(Config.load(root))}
    assert "claude login" not in rows and "claude CLI" not in rows
    assert rows["runner"][0] == WARN and rows["runner"][1].startswith("none chosen yet")
    assert "codex (logged out)" in rows["runner"][1]


def test_setup_choice_is_used_when_nothing_is_logged_in(tmp_path, monkeypatch, capsys):
    """Q3 hook: the runner `ap setup` chose on this PC is written when it is installed and no CLI is logged in."""
    root, _ = init_project(tmp_path)
    only_path(monkeypatch, tmp_path, fake_bin(tmp_path, codex="out"))
    home = Path(os.environ["AUTOPILOT_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "runner").write_text("codex\n", encoding="utf-8")
    from autopilot.cli import pick_runner
    assert pick_runner(root) is True
    assert "runner: codex (found on PATH)" in capsys.readouterr().out
    assert Config.load(root).get("agent.preset") == "codex"


def test_every_copy_of_a_runner_fact_matches_the_table():
    """Q1 rule: the template comment, REFERENCE and the HOWTO guide repeat runner facts; each copy follows the table."""
    from autopilot.backends.command import PRESETS
    from autopilot.config import TEMPLATES
    root = Path(__file__).resolve().parent.parent
    tpl = (TEMPLATES / "agent" / "project.yaml").read_text(encoding="utf-8")
    line = next(l for l in tpl.splitlines() if "# preset:" in l)
    assert set(line.split("command:")[1].split("(")[0].replace("|", " ").split()) == set(PRESETS)
    fb = next(l for l in tpl.splitlines() if "# fallback:" in l)
    keys = {r.key for r in RUNNERS}
    assert all(n in keys for n in fb.split("[")[1].split("]")[0].replace(",", " ").split())
    ref = (root / "REFERENCE.md").read_text(encoding="utf-8")
    table = ref[ref.index("| Runner | Program |"):ref.index("Copilot in VS Code")]
    for row in RUNNERS:
        assert f"| `{row.name}` | `{row.binary}`" in table and f"`{row.login}`" in table, row.key
        for tok in row.tokens[:1]:
            assert tok in table, row.key
    assert doctor.VSCODE_SENTENCE in ref
    for key, tpl_line in PRESETS.items():
        assert f"| `{key}` | `{tpl_line.split()[0]}" in ref, key
    howto = (root / "HOWTO.md").read_text(encoding="utf-8")
    guide = " ".join(howto[howto.index("## Limits and supported agent CLIs"):howto.index("## Share Autopilot")].split())
    for row in RUNNERS:
        assert f"`{row.binary}`" in guide or row.name == "claude", row.key
    assert doctor.VSCODE_SENTENCE in guide
    assert "cursor-agent" not in tpl and "cursor-agent" not in guide


def test_fallback_names_must_be_presets(tmp_path):
    root, pj = init_project(tmp_path)
    pj.write_text(pj.read_text(encoding="utf-8").replace("\nagent:\n", "\nagent:\n  fallback: [codex, nope]\n", 1), encoding="utf-8")
    errs = Config.load(root).validate()
    assert any("agent.fallback names must be presets" in e and "nope" in e for e in errs)


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


def test_smoke_fake_copilot_runs_one_task_end_to_end(tmp_path, monkeypatch, capsys):
    """Q2: a fake copilot (reads the file named in -p) plus a fake `gh auth status` 0 runs one task through the gate."""
    from autopilot.orchestrator import Orchestrator
    from test_presets import COPILOT
    root, pj = init_project(tmp_path)
    test = '"' + sys.executable + '" -c "import pathlib,sys; sys.exit(0 if pathlib.Path(\'hello.txt\').exists() else 1)"'
    pj.write_text(SMOKE_YAML.replace("{test}", json.dumps([test])), encoding="utf-8")
    plan = {"goal": "smoke", "phases": [{"id": "P01", "title": "One", "tasks": [
        {"id": "P01-T01", "title": "write hello.txt", "risk": "low", "acceptance_criteria": ["hello.txt exists"]}]}]}
    import yaml
    (root / ".agent" / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    path = fake_bin(tmp_path, gh="in")
    bindir = Path(path)
    (bindir / "copilot.py").write_text(COPILOT, encoding="utf-8")
    if sys.platform == "win32":
        (bindir / "copilot.cmd").write_text(f'@"{sys.executable}" "%~dp0copilot.py" %*\n')
    else:
        (bindir / "copilot").write_text(f"#!/bin/sh\nexec \"{sys.executable}\" \"{bindir / 'copilot.py'}\" \"$@\"\n")
        (bindir / "copilot").chmod(0o755)
    git = shutil.which("git")
    only_path(monkeypatch, tmp_path, path + os.pathsep + os.path.dirname(git))
    assert preflight(Config.load(root)) is True
    assert "runner: copilot (found on PATH)" in capsys.readouterr().out
    assert "  preset: copilot\n" in pj.read_text(encoding="utf-8")
    orch = Orchestrator(root, sleep=lambda s: None, max_sessions=1)
    orch.run()
    assert orch.state.task("P01-T01")["status"] == "done"
    assert (root / "hello.txt").exists()


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
