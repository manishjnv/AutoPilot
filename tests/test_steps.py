"""Q12: resumable setup. A fake install that dies at the runner step: the second run prints `done` for uv, Python and the
package and resumes at the runner; --reset runs all; the install method is read back by `ap upgrade`. Fakes only."""
import json
import os
from argparse import Namespace
from pathlib import Path

import pytest
from test_setup import Machine
from test_upgrade import FakeRun

from autopilot import install_errors as ie
from autopilot import steps
from autopilot.proc import Proc
from autopilot.upgrade import cmd_upgrade, detect_install


def state():
    return json.loads((Path(os.environ["AUTOPILOT_HOME"]) / "setup.json").read_text(encoding="utf-8"))


def test_every_step_writes_name_status_date_detail_when_it_ends():
    steps.record("runner", "done", "codex installed (npm)")
    steps.record("uv", "done", "uv 0.9.0")
    rows = state()
    assert [r["name"] for r in rows] == ["uv", "runner"]  # kept in the order of the steps
    assert set(rows[0]) == {"name", "status", "date", "detail"} and rows[1]["detail"] == "codex installed (npm)"
    steps.record("runner", "failed", "no route")
    assert steps.load()["runner"]["status"] == "failed" and len(state()) == 2  # one row per step


def test_a_run_that_dies_at_the_runner_step_resumes_there_and_skips_the_rest(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    dead = lambda cmd, **kw: Proc(35, "", "curl: (35) schannel: CRYPT_E_NO_REVOCATION_CHECK") if cmd[:1] == ["bash"] else m.run(cmd, **kw)
    from autopilot.commands import setup as st
    rc = st.run_setup(m.root, run=dead, say=m.said.append, yes=True, home=m.home, env={**os.environ}, platform="linux", skip_probe=True)
    assert rc == 1 and steps.load()["runner"]["status"] == "failed" and steps.load()["autopilot"]["status"] == "done"
    m.said.clear()
    assert m.setup(yes=True) == 0  # the second run, the install now works
    text = m.text
    assert "done      autopilot:" in text and "done      python:" in text
    assert text.index("done      autopilot:") < text.index("install   copilot:")  # the finished steps come first
    assert m.installed == ["curl -fsSL https://gh.io/copilot-install | bash"]  # only the runner installed
    assert steps.load()["runner"]["status"] == "done"


def test_a_found_program_is_a_done_step_and_nothing_installs(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, codex="in")
    assert m.setup() == 0 and m.installed == []
    rows = steps.load()
    assert rows["runner"]["status"] == "done" and rows["login"]["status"] == "done" and rows["config"]["status"] == "done"
    m.said.clear()
    assert m.setup() == 0
    assert "done      autopilot:" in m.text and m.installed == []


def test_reset_clears_the_file_and_runs_every_step_again(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    assert m.setup(yes=True) == 0 and len(m.installed) == 1
    assert (Path(os.environ["AUTOPILOT_HOME"]) / "setup.json").exists()
    assert steps.reset() is True and steps.reset() is False and steps.load() == {}
    steps.record("uv", "done")
    m.said.clear()
    assert m.setup(yes=True, reset=True) == 0
    assert "reset     the finished steps are forgotten" in m.text
    assert steps.load()["autopilot"]["status"] == "done"

@pytest.mark.parametrize("cmd,method", [
    ("winget install GitHub.Copilot", "winget"), ("brew install --cask copilot-cli", "brew"),
    ("npm i -g @openai/codex", "npm"), ("python3 -m pip install --user uv", "pip"), ("pip install x", "pip"),
    ("uv tool install dev-autopilot", "uv"), ("curl -fsSL https://claude.ai/install.sh | bash", "native"),
    ("irm https://claude.ai/install.ps1 | iex", "native"),
])
def test_the_install_method_is_named_from_the_command(cmd, method):
    assert steps.method_of(cmd) == method


def test_the_install_method_is_recorded_and_ap_upgrade_reads_it_back(tmp_path, monkeypatch):
    m = Machine(tmp_path, monkeypatch, gh="in")
    assert m.setup(yes=True) == 0
    assert steps.recorded_method("copilot") == "native"
    prof = json.loads((Path(os.environ["AUTOPILOT_HOME"]) / "machine.json").read_text(encoding="utf-8"))
    assert prof["install"] == {"copilot": "native"}
    steps.remember_method("autopilot", "pip")
    site = tmp_path / "site" / "autopilot"
    site.mkdir(parents=True)
    f = str(site / "__init__.py")
    # uv is on PATH and lists the tool, but the record says pip: the record decides
    assert detect_install(file=f, which=lambda n: "/bin/uv", run=FakeRun({"uv tool list": "dev-autopilot v0.3.0"})) == "pip"
    steps.remember_method("autopilot", "uv")
    assert detect_install(file=f, which=lambda n: "/bin/uv", run=FakeRun()) == "uv"
    assert detect_install(file=f, which=lambda n: None, run=FakeRun()) == "pip"  # a recorded uv that is gone falls back


def test_upgrade_uses_the_command_of_the_recorded_method(monkeypatch):
    from test_upgrade import GH_JSON, fake_open
    monkeypatch.setattr("autopilot.upgrade.__version__", "0.3.0")
    steps.remember_method("autopilot", "pip")
    run = FakeRun({"gh release view": GH_JSON})
    assert cmd_upgrade(Namespace(check=False, ref=None), run=run, urlopen=fake_open()) == 0
    assert run.calls[-1][1:4] == ["-m", "pip", "install"]


def test_a_dropped_connection_is_retried_once_after_five_seconds_before_the_error_line(tmp_path):
    seen, slept, said = [], [], []

    def run(cmd, **kw):
        seen.append(cmd)
        return Proc(56, "", "curl: (56) Recv failure: Connection reset by peer") if len(seen) == 1 else Proc(0, "ok", "")
    rc = ie.capture("install x", ["bash", "-c", "x"], run=run, say=said.append, retry=True, sleep=slept.append, home=tmp_path)
    assert rc == 0 and len(seen) == 2 and slept == [5]
    assert said == ["The connection dropped. One more try in 5 seconds."] and not any("FAILED" in s for s in said)
    seen.clear(), slept.clear(), said.clear()
    always = lambda cmd, **kw: seen.append(cmd) or Proc(56, "", "curl: (56) Recv failure")
    assert ie.capture("install x", ["bash", "-c", "x"], run=always, say=said.append, retry=True, sleep=slept.append, home=tmp_path) == 56
    assert len(seen) == 2 and slept == [5] and any(s.startswith("FAILED") for s in said)  # one retry, then the error line
    seen.clear(), slept.clear()
    full = lambda cmd, **kw: seen.append(cmd) or Proc(1, "", "No space left on device")
    ie.capture("install x", ["bash", "-c", "x"], run=full, say=said.append, retry=True, sleep=slept.append, home=tmp_path)
    assert len(seen) == 1 and slept == []  # another kind of error is never retried


def test_a_silent_installer_prints_the_heartbeat_line(tmp_path):
    import time
    said = []

    def slow(cmd, **kw):
        time.sleep(0.25)
        return Proc(0, "", "")
    assert ie.capture("install y", ["bash", "-c", "y"], run=slow, say=said.append, heartbeat=0.05, home=tmp_path) == 0
    assert said == ["downloading, up to 2 minutes"]

def test_uninstall_steps_undoes_each_done_step_in_reverse_with_the_command_of_the_recorded_method(tmp_path, monkeypatch, capsys):
    from autopilot.cli import cmd_uninstall
    steps.record("runner", "done", "codex installed (npm)")
    steps.record("config", "done", "codex written")
    steps.remember_method("codex", "npm")
    (Path(os.environ["AUTOPILOT_HOME"]) / "runner").write_text("codex\n")
    plan = steps.undo_plan(platform="linux")
    assert [n for n, _ in plan] == ["config", "runner"]  # last step first
    assert plan[1][1] == "npm uninstall -g @openai/codex"
    assert cmd_uninstall(Namespace(steps=True, dry_run=True, all=False, rights=False)) == 0
    out = capsys.readouterr().out
    assert "would config:" in out and "would runner: npm uninstall -g @openai/codex" in out
    assert steps.load() and (Path(os.environ["AUTOPILOT_HOME"]) / "runner").exists()  # a dry run changes nothing
    ran = []
    monkeypatch.setattr(ie, "run_proc", lambda *a, **k: ran.append(a[0]) or Proc(0, "", ""))
    monkeypatch.setattr("autopilot.install_errors.capture", lambda step, cmd, **k: ran.append(cmd) or 0)
    assert cmd_uninstall(Namespace(steps=True, dry_run=False, all=False, rights=False)) == 0
    assert ran == ["npm uninstall -g @openai/codex"]
    assert steps.load() == {} and not (Path(os.environ["AUTOPILOT_HOME"]) / "runner").exists()


def test_a_runner_that_was_found_is_kept_by_the_undo(tmp_path):
    steps.record("runner", "done", "codex found at /usr/bin/codex")
    assert "found, not installed by Autopilot" in steps.undo_plan(platform="linux")[0][1]
    assert steps.undo_plan() != [] and steps.reset() and steps.undo_plan() == []