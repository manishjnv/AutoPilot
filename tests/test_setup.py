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
            exe = d / row.binary
            exe.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" \"{fake}\" out \"{self.tmp / (row.binary + '.log')}\" \"$@\"\n")
            exe.chmod(0o755)
            return Proc(0, "installed\n", "")
        from autopilot.proc import run_proc
        return run_proc(cmd, **kw)

    def setup(self, ask=None, **kw):
        kw.setdefault("env", {**os.environ})
        kw.setdefault("platform", "linux")
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
