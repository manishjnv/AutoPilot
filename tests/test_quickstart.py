"""M5: `autopilot quickstart` (init → claude check → onboard → doctor) and the VPS installer script."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from autopilot.cli import folder_case, main as cli_main
from test_backend import stub_claude

CLAUDE_OK = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
             "elif sys.argv[1:2] == ['auth']: pass\n"
             "else: print(json.dumps({'type': 'result', 'result': 'onboarded', 'session_id': 's1'}))\n")


def test_broken_claude_stops_before_onboarding(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, "print('Bun 1.4.3')\n"))
    proj = tmp_path / "app"
    proj.mkdir()
    assert cli_main(["quickstart", "-C", str(proj)]) == 1
    out = capsys.readouterr().out
    assert "claude CLI" in out and "onboarding session" not in out and (proj / ".agent" / "project.yaml").exists()


def test_a_missing_login_stops_quickstart_and_run_before_the_first_session(tmp_path, monkeypatch, capsys):
    """H2: with no terminal the fix is printed, the exit code is not zero, and nothing is asked or started."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.delenv(name, raising=False)
    body = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
            "elif sys.argv[1:2] == ['auth']: sys.exit(1)\n"
            "else: open('SESSION_RAN', 'w').close()\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "PLAN.md").write_text("# Plan\nA todo app.\n")
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("a question was asked with no terminal"))
    for cmd in ("quickstart", "run"):
        assert cli_main([cmd, "-C", str(proj)]) == 1
        out = capsys.readouterr().out
        assert "FAIL  claude login" in out and "claude auth login" in out and "onboarding session" not in out
    assert not (proj / "SESSION_RAN").exists() and not (proj / ".agent" / "state.db").exists()


def test_with_a_terminal_the_login_is_offered_and_the_start_continues(tmp_path, monkeypatch, capsys):
    """H2 + N5.4: with a terminal, `claude auth login` runs by itself, the check runs again, and quickstart goes on."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.delenv(name, raising=False)
    flag = tmp_path / "logged-in"
    body = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
            f"elif sys.argv[1:3] == ['auth', 'login']: open({str(flag)!r}, 'w').close()\n"
            f"elif sys.argv[1:2] == ['auth']: sys.exit(0 if os.path.exists({str(flag)!r}) else 1)\n"
            "else: print(json.dumps({'type': 'result', 'result': 'onboarded', 'session_id': 's1'}))\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    (proj / "PLAN.md").write_text("# Plan\nA todo app.\n")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    for name in ("SSH_CONNECTION", "SSH_TTY", "WSL_DISTRO_NAME", "WSL_INTEROP", "SNAP", "SNAP_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")  # Q13: a desktop machine; the headless form has its own tests (test_login.py)
    monkeypatch.setattr("os.path.exists", lambda p, _real=__import__("os").path.exists: False if p in ("/.dockerenv", "/run/.containerenv") else _real(p))
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(AssertionError("no question (N5.4)")))
    assert cli_main(["quickstart", "-C", str(proj)]) == 0 and flag.exists()  # N5.4: the login runs, nothing typed
    out = capsys.readouterr().out
    assert "opens in your browser" in out and "onboarding session" in out


def test_detach_starts_the_same_command_as_its_own_process(tmp_path, monkeypatch, capsys):
    """I4/H6: `--detach` returns at once; the child is the same command without the flag, in a new session or
    process group, so it outlives the terminal or chat that started it."""
    seen = {}

    class Child:
        pid = 4242

        def __init__(self, cmd, **kw):
            seen.update(cmd=cmd, **kw)
    monkeypatch.setattr(subprocess, "Popen", Child)
    proj = tmp_path / "app"
    assert cli_main(["quickstart", "-C", str(proj), "--idea", "a todo app", "--run", "--detach"]) == 0
    assert seen["cmd"][1:] == ["-m", "autopilot", "quickstart", "-C", str(proj), "--idea", "a todo app", "--run"]
    assert seen.get("start_new_session") or seen.get("creationflags", 0) & subprocess.CREATE_NEW_PROCESS_GROUP
    assert seen["stdin"] == subprocess.DEVNULL and (proj / ".agent" / "logs" / "detached.log").exists()
    assert "4242" in capsys.readouterr().out


def test_missing_plan_doc(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    assert cli_main(["quickstart", "-C", str(proj), "--plan-doc", str(tmp_path / "nope.md")]) == 1
    assert "plan document not found" in capsys.readouterr().out


def test_happy_path_ends_with_doctor(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")  # python preset: real verify commands
    (tmp_path / "PLAN.md").write_text("# Plan\nA todo app.\n")
    rc = cli_main(["quickstart", "-C", str(proj), "--plan-doc", str(tmp_path / "PLAN.md")])
    out = capsys.readouterr().out
    assert "onboarding session" in out and "--- doctor" in out
    assert rc == 0 and "ready for `autopilot run`" in out and "What you can do next" in out


def test_no_plan_and_no_idea_asks_for_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    assert cli_main(["quickstart", "-C", str(proj)]) == 1  # pytest's stdin is not a terminal: nobody to ask
    assert "--idea" in capsys.readouterr().out


def test_an_idea_becomes_plan_md_then_onboarding(tmp_path, monkeypatch, capsys):
    body = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
            "elif sys.argv[1:2] == ['auth']: pass\n"
            "else:\n"
            "    import pathlib\n"
            "    if not pathlib.Path('PLAN.md').exists():\n"
            "        pathlib.Path('PLAN.md').write_text('# Plan: todo CLI\\n' + 'Part 1 and Part 2 ' * 60)\n"
            "    print(json.dumps({'type': 'result', 'result': 'ok', 'session_id': 's1'}))\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    rc = cli_main(["quickstart", "-C", str(proj), "--idea", "a todo list CLI with due dates"])
    out = capsys.readouterr().out
    assert "writing PLAN.md from your idea" in out and (proj / "PLAN.md").exists()
    assert "onboarding session" in out and rc == 0


def test_an_existing_plan_md_is_used(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, CLAUDE_OK))
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    (proj / "PLAN.md").write_text("# Plan\nA todo app.\n")
    assert cli_main(["quickstart", "-C", str(proj)]) == 0
    out = capsys.readouterr().out
    assert "using PLAN.md" in out and "writing PLAN.md" not in out


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs a POSIX bash")
def test_install_script_parses_and_checks_its_arguments():
    script = Path(__file__).resolve().parents[1] / "deploy" / "install.sh"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    p = subprocess.run(["bash", str(script), "Bad Name", "x"], capture_output=True, text=True)
    assert p.returncode == 2 and "usage" in p.stderr


ROOT_INSTALL = Path(__file__).resolve().parents[1] / "install.sh"


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs a POSIX bash")
def test_root_install_script_dry_run_changes_nothing(tmp_path):
    assert subprocess.run(["bash", "-n", str(ROOT_INSTALL)]).returncode == 0
    home, empty = tmp_path / "home", tmp_path / "empty"
    home.mkdir(), empty.mkdir()
    env = {"HOME": str(home), "PATH": str(empty)}
    p = subprocess.run([shutil.which("bash"), str(ROOT_INSTALL), "--dry-run"], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    for n in range(1, 6):
        assert f"==> Step {n} of 5:" in p.stdout
    assert p.stdout.count("would install") == 3 and "uv tool install" in p.stdout  # Q5: uv, Python, Autopilot; the runner is `ap setup`
    assert "This script installs:" in p.stdout and "Rights it takes:" in p.stdout  # N8: the one consent list
    assert "Rights it takes: none" in p.stdout and "sudo tee" not in p.stdout  # N5.4: the script takes no rights
    assert "would run: ap setup --dry-run" in p.stdout and "Claude Code" not in p.stdout  # Q5: no runner is named
    assert list(home.iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs a POSIX bash")
def test_root_install_script_rejects_a_bad_ref(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": str(tmp_path), "AUTOPILOT_REF": "x; rm -rf ~"}
    p = subprocess.run([shutil.which("bash"), str(ROOT_INSTALL), "--dry-run"], capture_output=True, text=True, env=env)
    assert p.returncode == 2


# ---- N5: Python when missing, `ap` on PATH, one final line ----
FINAL_LINE = "Open a project folder and type `ap`."
ROOT_INSTALL_PS1 = ROOT_INSTALL.with_name("install.ps1")


def test_install_scripts_install_python_only_when_missing_and_check_ap():
    for script in (ROOT_INSTALL, ROOT_INSTALL_PS1):
        text = script.read_text(encoding="utf-8")
        assert "uv python install" in text and "3, 10" in text, script.name
        assert "ap is on PATH" in text, script.name
        last = [x for x in text.rstrip().splitlines() if x.strip() not in ("", "}", 'main "$@"')][-1]
        assert last.endswith(FINAL_LINE + "'"), script.name
    sh = ROOT_INSTALL.read_text(encoding="utf-8")
    assert sh.index("if pyok;") < sh.index('run 3 Python "$pycmd"')
    assert "have ap" in sh and "Command: $pycmd" in sh


def test_root_install_dry_run_ends_with_the_one_final_line(tmp_path):
    if sys.platform == "win32" or not shutil.which("bash"):
        return  # the text checks above cover the scripts; the dry run needs a POSIX bash (WSL runs it)
    home, empty = tmp_path / "home", tmp_path / "empty"
    home.mkdir(), empty.mkdir()
    p = subprocess.run([shutil.which("bash"), str(ROOT_INSTALL), "--dry-run"], capture_output=True, text=True,
                       env={"HOME": str(home), "PATH": str(empty)})
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines()[-1] == FINAL_LINE
    assert "Command: uv python install 3.12" in p.stdout and "would check: ap is on PATH" in p.stdout


# ---- H5: the guided start (plain `autopilot` in a terminal, no project here) ----
PLAN_STUB = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
             "elif sys.argv[1:2] == ['auth']: sys.exit(AUTH)\n"
             "else:\n"
             "    import pathlib\n"
             "    if not pathlib.Path('PLAN.md').exists():\n"
             "        pathlib.Path('PLAN.md').write_text('# Plan: todo CLI\\n' + 'Part 1 and Part 2 ' * 60)\n"
             "    p = pathlib.Path('.agent/project.yaml')  # the onboarding session: a new folder has no verify command\n"
             "    p.write_text(p.read_text().replace('  test: []', \"  test: ['true']\"))\n"
             "    print(json.dumps({'type': 'result', 'result': 'ok', 'session_id': 's1'}))\n")


def guided(tmp_path, monkeypatch, answers, auth=0, tty=True):
    """A work folder with no project, a home folder elsewhere, a stub claude and scripted answers."""
    work, home = tmp_path / "work", tmp_path / "home"
    work.mkdir()
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, PLAN_STUB.replace("AUTH", str(auth))))
    monkeypatch.chdir(work)
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty)
    monkeypatch.setattr("sys.stdout.isatty", lambda: tty)
    it = iter(answers)

    def fake(*a):
        try:
            a = next(it)
        except StopIteration:
            raise AssertionError("more questions than answers") from None
        if isinstance(a, BaseException):
            raise a
        return a
    monkeypatch.setattr("builtins.input", fake)
    return work, home


def test_no_terminal_prints_the_banner_and_asks_nothing(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, [], tty=False)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("a question was asked with no terminal"))
    assert cli_main([]) == 0
    out = capsys.readouterr().out
    assert "builds your software project while you are away" in out and "What you can do next" in out
    assert list(work.iterdir()) == []


def test_a_terminal_in_a_project_folder_asks_nothing(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, [])
    (work / ".agent").mkdir()
    (work / ".agent" / "project.yaml").write_text("name: x\n")
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("a question was asked in a project folder"))
    assert cli_main([]) == 0
    assert "What you can do next" in capsys.readouterr().out


def test_an_empty_idea_prints_the_banner(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, [""])
    assert cli_main([]) == 0
    assert "What you can do next" in capsys.readouterr().out and list(work.iterdir()) == []


def test_guided_start_not_now(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, ["a todo list CLI with due dates", "", "", "2"])
    monkeypatch.setattr("autopilot.cli.cmd_run", lambda a: pytest.fail("the run started"))
    assert cli_main(["--ask"]) == 0  # N5.5: a plain plan starts by itself; --ask keeps the question
    out = capsys.readouterr().out
    proj = work / "a-todo-list-cli-with-due-dates"
    assert (proj / ".agent" / "project.yaml").exists() and (proj / "PLAN.md").exists()
    assert "The plan:" in out and "tasks" in out
    assert "The build runs for hours. It uses your Claude plan." in out and "It works without asking you." in out
    assert f"autopilot run -C {proj.resolve()}" in out


def test_guided_start_now_runs_that_folder(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, ["a todo list CLI", "", "", "1"])
    calls = []
    monkeypatch.setattr("autopilot.cli.cmd_run", lambda a: calls.append(a.path) or 0)
    assert cli_main([]) == 0
    assert calls == [str((work / "a-todo-list-cli").resolve())]


# ---- N4: plain `ap` in a folder with code and no .agent/ ----
ADOPT_STUB = ("if sys.argv[1:2] == ['--version']: print('2.1.286 (Claude Code)')\n"
              "elif sys.argv[1:2] == ['auth']: sys.exit(0)\n"
              "else:\n"
              "    import pathlib, yaml\n"
              "    p = pathlib.Path('.agent/project.yaml')\n"
              "    p.write_text(p.read_text().replace('  test: []', \"  test: ['true']\"))\n"
              "    t = [{'id': f'P01-T0{i}', 'title': f's{i}', 'status': 'done', 'acceptance_criteria': ['ok']} for i in (1, 2)]\n"
              "    t.append({'id': 'P01-T03', 'title': 'export csv', 'acceptance_criteria': ['csv']})\n"
              "    pathlib.Path('.agent/plan.yaml').write_text(yaml.safe_dump({'version': 1, 'goal': 'g', 'phases': "
              "[{'id': 'P01', 'title': 'All', 'goal': 'g', 'tasks': t}]}))\n"
              "    print(json.dumps({'type': 'result', 'result': 'ok', 'session_id': 's1'}))\n")


def adopt_folder(tmp_path, monkeypatch, answers, tty=True):
    work, home = guided(tmp_path, monkeypatch, answers, tty=tty)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, ADOPT_STUB))
    (work / "app.py").write_text("print('hi')\n")
    (work / "PLAN.md").write_text("# Plan\n- [x] one\n- [x] two\n- [ ] export csv\n")
    return work


def test_code_without_agent_dir_is_adopted_and_not_now_does_not_start(tmp_path, monkeypatch, capsys):
    work = adopt_folder(tmp_path, monkeypatch, ["2"])
    monkeypatch.setattr("autopilot.cli.cmd_run", lambda a: pytest.fail("the run started"))
    assert cli_main([]) == 0
    out = capsys.readouterr().out
    assert (work / ".agent" / "project.yaml").exists() and (work / ".agent" / "plan.yaml").exists()
    assert "done" in out and "P01-T03" in out and "  1  start now" in out
    assert f"autopilot run -C {work.resolve()}" in out


def test_code_without_agent_dir_start_now_runs_that_folder(tmp_path, monkeypatch, capsys):
    work = adopt_folder(tmp_path, monkeypatch, ["1"])
    calls = []
    monkeypatch.setattr("autopilot.cli.cmd_run", lambda a: calls.append(a.path) or 0)
    assert cli_main([]) == 0
    assert calls == [str(work.resolve())]


def test_empty_and_dotfile_folders_show_the_idea_prompt(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, [""])
    (work / ".git").mkdir()
    assert cli_main([]) == 0
    assert "What you can do next" in capsys.readouterr().out and not (work / ".agent").exists()


def test_agent_folder_runs_no_onboarding(tmp_path, monkeypatch, capsys):
    work = adopt_folder(tmp_path, monkeypatch, [])
    (work / ".agent").mkdir()
    (work / ".agent" / "project.yaml").write_text("name: x\n")
    monkeypatch.setattr("autopilot.cli.cmd_onboard", lambda a: pytest.fail("onboarding ran"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("a question was asked"))
    assert cli_main([]) == 0
    assert "What you can do next" in capsys.readouterr().out


@pytest.mark.parametrize("case", ["empty", "code", "agent"])
def test_no_terminal_never_asks_in_any_case(tmp_path, monkeypatch, capsys, case):
    work = adopt_folder(tmp_path, monkeypatch, [], tty=False)
    if case == "empty":
        for f in list(work.iterdir()):
            f.unlink()
    if case == "agent":
        (work / ".agent").mkdir()
        (work / ".agent" / "project.yaml").write_text("name: x\n")
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("a question was asked with no terminal"))
    monkeypatch.setattr("autopilot.cli.cmd_onboard", lambda a: pytest.fail("onboarding ran"))
    assert cli_main([]) == 0
    assert "What you can do next" in capsys.readouterr().out
    assert (work / ".agent").exists() == (case == "agent")


def test_folder_safety(tmp_path, monkeypatch, capsys):
    work, home = guided(tmp_path, monkeypatch, [])
    full = tmp_path / "full"  # N4: a file in the work folder would make it an adopt case
    full.mkdir()
    for n in range(12):
        (full / f"f{n}.txt").write_text("x")
    answers = ["an app", "", str(home), str(Path(work.anchor)), str(full), "2", "", "2"]
    monkeypatch.setattr("builtins.input", lambda *a: answers.pop(0))
    monkeypatch.setattr("autopilot.cli.cmd_run", lambda a: pytest.fail("the run started"))
    assert cli_main(["--ask"]) == 0  # N5.5: --ask keeps the start question
    out = capsys.readouterr().out
    assert out.count("not this one") == 2 and "(12 entries)" in out and "f0.txt" in out and "f9.txt" not in out
    assert (work / "an-app" / ".agent" / "project.yaml").exists() and answers == []


def test_ctrl_c_at_the_folder_question_leaves_nothing(tmp_path, monkeypatch, capsys):
    work, _ = guided(tmp_path, monkeypatch, ["an app", "", KeyboardInterrupt()])
    assert cli_main([]) == 130
    assert "Traceback" not in capsys.readouterr().err and list(work.iterdir()) == []


def test_a_missing_login_stops_before_anything_is_created(tmp_path, monkeypatch, capsys):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.delenv(name, raising=False)
    work, _ = guided(tmp_path, monkeypatch, ["an app", "", "", "2"], auth=1)
    assert cli_main([]) == 1
    assert not (work / "an-app").exists()


# ---- P05-T02: README install lines, honest limits, links ----
README = ROOT_INSTALL.with_name("README.md")
from autopilot.doctor import RUNNERS as _ROWS  # noqa: E402
RUNNERS = ("Claude Code", *(r.binary for r in _ROWS if r.key != "claude_cli"))  # Q1: from the one table


def test_readme_has_one_install_line_per_system():
    text = README.read_text(encoding="utf-8")
    win = "irm https://raw.githubusercontent.com/manishjnv/AutoPilot/main/install.ps1 | iex"
    nix = "curl -fsSL https://raw.githubusercontent.com/manishjnv/AutoPilot/main/install.sh | bash"
    assert text.count(win) == 1 and text.count(nix) == 1
    assert "install.ps1 | iex" not in text.replace(win, "") and "install.sh | " not in text.replace(nix, "")
    assert text.index(win) < text.index(nix) < text.index(FINAL_LINE)
    assert "Open a project folder and type `ap`." in text


def test_howto_limits_name_the_gaps_and_the_runners():  # session 28: the section moved from the README to HOWTO
    text = (README.parent / "HOWTO.md").read_text(encoding="utf-8")
    section = text[text.index("## Limits and supported agent CLIs"):text.index("## Use a different agent CLI")]
    for name in ("Replit", "Kiro", "Cursor", *RUNNERS):
        assert name in section, name


def test_readme_relative_links_point_to_existing_files():
    import re
    text = README.read_text(encoding="utf-8")
    targets = {m for m in re.findall(r"\]\(([^)\s]+)\)", text) if "://" not in m and not m.startswith("mailto:")}
    assert targets
    missing = [t for t in sorted(targets) if not (README.parent / t.split("#", 1)[0]).exists()]
    assert missing == []


def test_piped_install_sh_dry_run_runs_the_script(tmp_path):
    """P05-T02: the README line `curl ... | bash` runs the script; here the script arrives on stdin, as in the pipe."""
    if sys.platform == "win32" or not shutil.which("bash"):
        return  # the text checks cover the README; the piped run needs a POSIX bash (WSL runs it)
    home, empty = tmp_path / "home", tmp_path / "empty"
    home.mkdir(), empty.mkdir()
    env = {"HOME": str(home), "PATH": str(empty), "AUTOPILOT_DRY_RUN": "1"}
    p = subprocess.run([shutil.which("bash")], input=ROOT_INSTALL.read_bytes(), capture_output=True, env=env)
    out = p.stdout.decode()
    assert p.returncode == 0, p.stderr.decode()
    assert "==> Step 1 of 5:" in out and out.splitlines()[-1] == FINAL_LINE
    assert list(home.iterdir()) == []


def test_a_fresh_clone_has_no_agent_state_and_validate_finds_no_plan(tmp_path, monkeypatch, capsys):
    """The repo's own .agent/ is not tracked: a clone is a code folder, never an existing project."""
    work, _ = guided(tmp_path, monkeypatch, [])
    (work / "README.md").write_text("# Autopilot\n")
    (work / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (work / "autopilot").mkdir()
    (work / "autopilot" / "__init__.py").write_text("")
    assert folder_case(work) == "code"  # the adopt flow, not a continue of an old run
    assert cli_main(["validate", "-C", str(work)]) == 1
    assert "plan.yaml not found" in capsys.readouterr().out
