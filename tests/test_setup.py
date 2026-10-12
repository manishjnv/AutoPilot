"""Q3: `ap setup` on fixture machines. Every runner is a fake script on a temporary PATH; every install command is
replaced; nothing logs in. Fixture machines: codex-logged-in, copilot-only, empty-PATH-with-gh, claude-footprint."""
import json
import os
import sys
from pathlib import Path

import pytest
from test_runner_detect import fake_bin, init_project, only_path

from autopilot.commands import setup as st
from autopilot.doctor import RUNNERS
from autopilot.proc import Proc

GIT = os.path.dirname(__import__("shutil").which("git"))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for row in RUNNERS:
        for k in row.tokens:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("AUTOPILOT_RUNNER", raising=False)


class Machine:
    """A fixture machine: a tmp PATH with fake CLIs, a tmp home, a recorded fake install step."""

    def __init__(self, tmp_path, monkeypatch, **modes):
        self.tmp, self.installed, self.said = tmp_path, [], []
        tmp_path.mkdir(exist_ok=True)
        if modes:
            self.path = fake_bin(tmp_path, **modes)
        else:
            (tmp_path / "empty").mkdir()
            self.path = str(tmp_path / "empty")
        only_path(monkeypatch, tmp_path, self.path + os.pathsep + GIT)
        self.home = Path(os.environ["HOME"])
        self.root, self.pj = init_project(tmp_path)

    def run(self, cmd, **kw):
        """The install step: records the command and puts the fake binary in ~/.local/bin (logged out)."""
        if isinstance(cmd, list) and cmd[:1] == ["bash"] or isinstance(cmd, str):
            text = cmd[-1] if isinstance(cmd, list) else cmd
            self.installed.append(text)
            row = next(r for r in RUNNERS if r.install_cmd("linux") == text or r.npm == text)
            d = self.home / ".local" / "bin"
            d.mkdir(parents=True, exist_ok=True)
            fake = Path(self.path) / "fake.py"
            if not fake.exists():
                fake.write_text(__import__("test_runner_detect").FAKE)
            log = self.tmp / (row.binary + ".log")
            if sys.platform == "win32":
                (d / f"{row.binary}.cmd").write_text(f'@"{sys.executable}" "{fake}" out "{log}" %*\n')
            else:
                exe = d / row.binary
                exe.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" \"{fake}\" out \"{log}\" \"$@\"\n")
                exe.chmod(0o755)
            return Proc(0, "installed\n", "")
        from autopilot.proc import run_proc
        return run_proc(cmd, **kw)

    def setup(self, ask=None, **kw):
        kw.setdefault("env", {**os.environ})
        kw.setdefault("platform", "linux")
        kw.setdefault("skip_probe", True)  # Q11: the probe has its own tests below
        return st.run_setup(self.root, run=self.run, say=self.said.append, ask=ask, home=self.home, **kw)

    @property
    def text(self):
        return "\n".join(self.said)

    def yaml(self):
        import yaml
        agent = (yaml.safe_load(self.pj.read_text(encoding="utf-8")) or {}).get("agent") or {}
        return {k: v for k, v in agent.items() if k in ("backend", "preset")}


def test_logged_in_codex_wins_with_no_question_and_no_install(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, codex="in")
    asked = []
    assert m.setup(ask=lambda q: asked.append(q) or "9") == 0
    assert asked == [] and m.installed == []
    assert m.yaml() == {"backend": "command", "preset": "codex"} and "codex (installed)" in m.text
    assert "login     codex: logged in" in m.text and "rights " in m.text
    assert (Path(os.environ["AUTOPILOT_HOME"]) / "runner").read_text().strip() == "codex"


def test_copilot_only_machine_reaches_preset_copilot_with_no_question(tmp_path, monkeypatch):
    """The session acceptance: a fake copilot, a fake `gh auth status` 0, no claude -> `agent.preset: copilot`."""
    m = Machine(tmp_path, monkeypatch, copilot="out", gh="in")
    assert m.setup(ask=lambda q: pytest.fail("asked")) == 0
    assert m.installed == [] and m.yaml() == {"backend": "command", "preset": "copilot"}
    assert "copilot (installed)" in m.text and "login     copilot: logged in" in m.text
    assert "# Commands the orchestrator runs itself" in m.pj.read_text(encoding="utf-8")  # comments stay


def test_installed_but_logged_out_runner_is_kept_and_its_login_printed(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, codex="out")
    assert m.setup(ask=lambda q: pytest.fail("asked")) == 0
    assert m.installed == [] and m.yaml()["preset"] == "codex"
    assert "login     codex: not logged in. Run `codex login`" in m.text and "a ChatGPT plan" in m.text


def test_empty_path_with_gh_login_defaults_to_copilot_and_yes_installs_it(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    asked = []
    rc = m.setup(yes=True, ask=lambda q: asked.append(q) or None)
    assert rc == 0 and asked == []
    assert m.installed == ["curl -fsSL https://gh.io/copilot-install | bash"]  # the row's linux command, fake run
    assert "will install  copilot: curl -fsSL https://gh.io/copilot-install | bash" in m.text
    assert m.yaml() == {"backend": "command", "preset": "copilot"}
    assert "login     copilot: logged in" in m.text  # gh auth status 0 counts for copilot


def test_empty_path_with_gh_login_asks_with_copilot_as_the_default(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    asked = []
    assert m.setup(ask=lambda q: asked.append(q) or "") == 0  # Enter = the default
    assert len(asked) == 1 and st.QUESTION in m.text
    lines = [l for l in m.said if "(default)" in l]
    assert len(lines) == 1 and "copilot" in lines[0]
    assert m.yaml()["preset"] == "copilot"


def test_claude_footprint_only_asks_and_claude_is_only_the_default(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch)
    (m.home / ".claude").mkdir()
    asked = []
    assert m.setup(ask=lambda q: asked.append(q) or "2") == 0  # the person picks 2 = copilot
    assert len(asked) == 1
    assert any("claude" in l and "(default)" in l for l in m.said)
    assert "a footprint of claude; it installs nothing by itself" in m.text
    assert m.installed == ["curl -fsSL https://gh.io/copilot-install | bash"] and m.yaml()["preset"] == "copilot"
    assert "login     copilot: not logged in. Run `copilot login`" in m.text  # no gh, no token: logged out


def test_no_terminal_and_no_flag_exits_3_with_the_rerun_line(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    assert m.setup(ask=lambda q: None) == 3
    assert "ap setup --runner copilot" in m.text and m.installed == [] and "agent" not in m.pj.read_text()[-80:]
    assert m.yaml().get("preset") is None


def test_runner_flag_and_env_answer_in_advance_and_an_unknown_name_is_usage(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch)
    assert m.setup(wanted="nope", ask=lambda q: pytest.fail("asked")) == 2
    assert "unknown runner `nope`" in m.text
    m2 = Machine(tmp_path / "two", monkeypatch)
    assert m2.setup(wanted="kiro", ask=lambda q: pytest.fail("asked")) == 0
    assert m2.installed == ["curl -fsSL https://cli.kiro.dev/install | bash"] and m2.yaml()["preset"] == "kiro"
    m3 = Machine(tmp_path / "three", monkeypatch)
    assert m3.setup(env={**os.environ, "AUTOPILOT_RUNNER": "codex"}, ask=lambda q: pytest.fail("asked")) == 0
    assert m3.yaml()["preset"] == "codex"


def test_kiro_on_windows_prints_the_download_link_and_asks_for_a_rerun(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch)
    assert m.setup(wanted="kiro", platform="win32") == 3
    assert m.installed == [] and "https://kiro.dev/downloads/" in m.text and "run `ap setup` again" in m.text


def test_dry_run_prints_the_plan_and_writes_nothing(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    before = m.pj.read_bytes()
    assert m.setup(dry_run=True, ask=lambda q: pytest.fail("asked")) == 0
    assert "dry run: nothing installed, nothing written" in m.text and "found     gh login" in m.text
    assert m.installed == [] and m.pj.read_bytes() == before
    assert not (Path(os.environ["AUTOPILOT_HOME"]) / "runner").exists()


def test_skip_login_names_the_login_command_for_later(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, codex="out")
    assert m.setup(skip_login=True) == 0
    assert "login     codex: not logged in (skipped). Run `codex login`" in m.text


def test_a_failed_install_shows_three_plain_lines_and_the_raw_text_goes_to_the_log(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    raw = "curl: (35) schannel: next InitializeSecurityContext failed: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)"

    def failing(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["bash"]:
            return Proc(35, "", raw + "\nTraceback junk line\n")
        return __import__("autopilot.proc", fromlist=["run_proc"]).run_proc(cmd, **kw)
    rc = st.run_setup(m.root, run=failing, say=m.said.append, yes=True, home=m.home, env={**os.environ}, platform="linux")
    assert rc == 1
    assert "CRYPT_E_NO_REVOCATION_CHECK" not in m.text and "Traceback" not in m.text  # never on screen
    assert any(l.startswith("FAILED  install copilot") for l in m.said)
    log = Path(os.environ["AUTOPILOT_HOME"]) / "install.log"
    assert log.exists() and "CRYPT_E_NO_REVOCATION_CHECK" in log.read_text(encoding="utf-8")
    assert str(log) in m.text and m.yaml().get("preset") is None


def test_token_values_never_reach_the_log_or_the_screen(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, copilot="out")
    monkeypatch.setenv("GH_TOKEN", "ghp_fakefakefake0000")

    def failing(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["bash"]:
            return Proc(1, "", "token ghp_fakefakefake0000 rejected")
        return __import__("autopilot.proc", fromlist=["run_proc"]).run_proc(cmd, **kw)
    st.run_setup(m.root, run=failing, say=m.said.append, home=m.home, wanted="codex", env={**os.environ}, platform="linux")
    log = (Path(os.environ["AUTOPILOT_HOME"]) / "install.log").read_text(encoding="utf-8")
    assert "ghp_fakefakefake0000" not in log and "***REDACTED[GH_TOKEN]***" in log
    assert "ghp_fakefakefake0000" not in m.text and "token variable GH_TOKEN (set; the value is never read)" in m.text


def test_cli_setup_dry_run_runs_outside_a_project(tmp_path, monkeypatch, capsys):
    from autopilot.cli import main
    only_path(monkeypatch, tmp_path, str(tmp_path) + os.pathsep + GIT)
    monkeypatch.chdir(tmp_path)
    assert main(["setup", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "runner    none found: one question follows" in out and "dry run" in out


def test_plan_lines_read_from_the_table_only():
    s = st.Scan(runners=[(r, "", False) for r in RUNNERS], tools={"git": "git version 2"})
    lines = st.plan_lines(s, None, "linux")
    assert "found     git version 2" in lines and "runner    none found: one question follows" in lines
    assert sum(l.startswith("skipped   ") and ": not installed, not chosen" in l for l in lines) == len(RUNNERS)
    assert json.dumps(lines)  # plain strings only


def test_install_workflow_has_four_jobs_including_git_bash():
    """Q8: Linux, macOS, Windows PowerShell and Git Bash; every real install names the runner; the fixtures stay fake here."""
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github" / "workflows" / "install.yml").read_text(encoding="utf-8"))
    assert set(wf["jobs"]) == {"linux", "macos", "windows", "gitbash"}
    gb = wf["jobs"]["gitbash"]
    assert gb["runs-on"].startswith("windows") and gb["defaults"]["run"]["shell"] == "bash"
    steps = " ".join(str(s.get("run", "")) for s in gb["steps"])
    assert "--dry-run" in steps and "--skip-login" in steps and "install.cmd -DryRun" in steps
    for job in wf["jobs"].values():
        for step in job["steps"]:
            run = str(step.get("run", ""))
            if "Real install" == step.get("name"):
                assert "--runner claude" in run or "-Runner claude" in run

# Q11: the probe. A fake `codex` answers the one prompt; the login counts through a token variable (no status call).
def _probe_machine(tmp_path, monkeypatch, body: str):
    m = Machine(tmp_path, monkeypatch)
    script = Path(m.path) / "probe_fake.py"
    script.write_text("import sys, time, os\n" + body, encoding="utf-8")
    if sys.platform == "win32":
        (Path(m.path) / "codex.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe = Path(m.path) / "codex"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        exe.chmod(0o755)
    return m


def _probe_setup(m, **kw):
    return m.setup(wanted="codex", skip_probe=False, env={**os.environ, "CODEX_API_KEY": "fake-not-a-key"}, **kw)


def test_probe_that_answers_ready_writes_verified_to_the_profile_and_the_project(tmp_path, monkeypatch):
    import datetime
    m = _probe_machine(tmp_path, monkeypatch, "print('ready')\n")
    assert _probe_setup(m) == 0
    today = datetime.date.today().isoformat()
    assert f"verified  codex: answered ready ({today})" in m.text
    prof = json.loads((Path(os.environ["AUTOPILOT_HOME"]) / "machine.json").read_text(encoding="utf-8"))
    assert prof["verified"] == today
    import yaml
    assert yaml.safe_load(m.pj.read_text(encoding="utf-8"))["agent"]["verified"] == today
    assert "# Commands the orchestrator runs itself" in m.pj.read_text(encoding="utf-8")  # comments stay


def test_probe_runs_in_an_empty_folder_with_the_prompt(tmp_path, monkeypatch):
    m = _probe_machine(tmp_path, monkeypatch, "print('ready' if os.listdir('.') == [] and 'Reply with the single word ready.' in sys.argv else 'no')\n")
    assert _probe_setup(m) == 0 and "verified  codex" in m.text


def test_probe_with_a_no_plan_answer_prints_the_catalogue_sentence(tmp_path, monkeypatch):
    m = _probe_machine(tmp_path, monkeypatch, "print('Error: your account does not have access to GitHub Copilot'); sys.exit(1)\n")
    assert _probe_setup(m) == 1
    assert "FAILED  probe codex" in m.text and "has no Copilot plan" in m.text and "Run by hand:" in m.text
    assert "verified" not in m.pj.read_text(encoding="utf-8")
    assert not (Path(os.environ["AUTOPILOT_HOME"]) / "machine.json").exists()


def test_probe_with_a_wrong_model_and_a_blocked_host_and_a_logged_out_answer(tmp_path, monkeypatch):
    for n, (said, want) in enumerate([("model_not_found: the model xyz does not exist", "model name is not available"),
                                      ("Error: connect ECONNREFUSED 10.0.0.1:443", "blocked on this network"),
                                      ('{"error":{"type":"authentication_error"}}', "is not logged in")]):
        m = _probe_machine(tmp_path / str(n), monkeypatch, f"print({said!r}); sys.exit(1)\n")
        assert _probe_setup(m) == 1 and want in m.text, m.text


def test_probe_that_answers_something_else_says_so(tmp_path, monkeypatch):
    m = _probe_machine(tmp_path, monkeypatch, "print('hello there')\n")
    assert _probe_setup(m) == 1 and "not with the word ready" in m.text


def test_probe_timeout_prints_the_slow_sentence(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "PROBE_TIMEOUT", 1)
    m = _probe_machine(tmp_path, monkeypatch, "time.sleep(30)\nprint('ready')\n")
    assert _probe_setup(m) == 1
    assert "did not answer within 60 seconds" in m.text and "ap doctor --runner" in m.text


def test_probe_is_skipped_without_a_login_and_with_the_flag(tmp_path, monkeypatch):
    m = _probe_machine(tmp_path, monkeypatch, "if sys.argv[1:2] == ['login']:\n    print('Not logged in'); sys.exit(1)\nprint('ready')\n")
    assert m.setup(wanted="codex", skip_probe=False) == 0 and "probe     skipped: log in first" in m.text
    m2 = _probe_machine(tmp_path / "two", monkeypatch, "print('ready')\n")
    assert m2.setup(wanted="codex", env={**os.environ, "CODEX_API_KEY": "x"}) == 0 and "sending one prompt" not in m2.text and "verified " not in m2.text


def test_every_runner_row_has_a_probe_with_the_prompt_slot():
    for r in RUNNERS:
        assert r.probe and any("{prompt}" in a for a in r.probe), r.key


def test_doctor_runner_flag_probes_the_runner(tmp_path, monkeypatch, capsys):
    from autopilot.cli import main
    m = _probe_machine(tmp_path, monkeypatch, "print('ready')\n")
    (Path(os.environ["AUTOPILOT_HOME"])).mkdir(parents=True, exist_ok=True)
    (Path(os.environ["AUTOPILOT_HOME"]) / "runner").write_text("codex\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_API_KEY", "fake-not-a-key")
    monkeypatch.chdir(m.root)
    assert main(["doctor", "--runner"]) == 0
    assert "answered ready" in capsys.readouterr().out
