"""W67: a stale STOP file is named, not obeyed. W68: a foreign commit on an autopilot/* branch is kept.
W69: a long project command reports its elapsed time."""
import json
import os
import time
from pathlib import Path

from autopilot import gate
from autopilot.cli import TEMPLATE_LINE, stale_stop_line
from autopilot.cli import main as cli_main
from autopilot.gitops import Git


def _no_login_check(monkeypatch):
    monkeypatch.setattr("autopilot.cli.preflight", lambda cfg: True)
    monkeypatch.setattr("autopilot.cli.cmd_preflight", lambda args: 0)


def _repo(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    g = Git(root)
    g.ensure_repo("main")
    return root, g


def test_a_stale_stop_file_refuses_run_and_start_clears_it(tmp_path, monkeypatch, capsys):
    _no_login_check(monkeypatch)
    root = tmp_path / "proj"
    root.mkdir()
    assert cli_main(["init", "-C", str(root), "--stack", "generic"]) == 0
    stop = root / ".agent" / "STOP"
    stop.write_text("stop requested\n", encoding="utf-8")
    old = time.time() - 12 * 3600
    os.utime(stop, (old, old))
    assert cli_main(["run", "-C", str(root)]) == 2
    out = capsys.readouterr().out
    assert stale_stop_line(stop) in out and "ap start clears it" in out and stop.exists()
    assert cli_main(["run", "--clear-stop", "-C", str(root)]) == 2  # the template plan is the next refusal
    assert TEMPLATE_LINE in capsys.readouterr().out and not stop.exists()


def test_a_foreign_commit_on_an_autopilot_branch_is_kept_under_a_new_name(tmp_path):
    root, g = _repo(tmp_path)
    g.start_branch("autopilot/fixer", "main")
    (root / "their-fix.txt").write_text("someone else's work\n", encoding="utf-8")
    g.commit_all("test: a fix by the other session")  # lands on autopilot/fixer, not on main
    sha = g.head()[:7]
    g.start_branch("autopilot/fixer", "main")  # the next attempt: today this reset the branch
    assert g.kept_branches == [("autopilot/fixer", f"autopilot/fixer.kept-{sha}")]
    assert g.ref(f"autopilot/fixer.kept-{sha}").startswith(sha) and g.head() == g.ref("main")
    assert not (root / "their-fix.txt").exists()  # the fresh branch starts at main


def test_delete_branch_renames_instead_when_it_holds_a_foreign_commit(tmp_path):
    root, g = _repo(tmp_path)
    g.start_branch("autopilot/P01-T01", "main")
    (root / "x.txt").write_text("x\n", encoding="utf-8")
    g.commit_all("foreign")
    g.checkout_main("main")
    g.delete_branch("autopilot/P01-T01")
    names = g.run("branch", "--list", "autopilot/*")
    assert "autopilot/P01-T01.kept-" in names and "autopilot/P01-T01\n" not in names + "\n"
    g.start_branch("autopilot/P02-T01", "main")  # a branch without foreign commits is deleted as before
    g.checkout_main("main")
    g.delete_branch("autopilot/P02-T01")
    assert "P02-T01" not in g.run("branch", "--list", "autopilot/*")


def test_a_long_command_ticks_and_records_its_duration(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gate, "TICK_EVERY", 0.3)
    monkeypatch.setattr(gate, "TICK", lambda cmd, elapsed, done=False: calls.append((cmd, round(elapsed, 1), done)))
    res = gate.run_commands(['python -c "import time; time.sleep(1.0)"'], tmp_path, 30)
    assert res[0].rc == 0
    ticks = [c for c in calls if not c[2]]
    assert len(ticks) >= 2 and all(c[1] > 0 for c in ticks)
    assert calls[-1][2] is True and calls[-1][1] >= 1.0


def test_the_journal_line_grows_an_elapsed_figure_and_an_estimate(tmp_path):
    from autopilot.orchestrator import Orchestrator
    from test_autopilot import FakeBackend, make_project, phases_basic
    root = make_project(tmp_path, phases_basic())
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch._journal(status="running", current="start check: tests on main (pnpm test)")
    orch._cmd_tick("pnpm test", 780)
    run = json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8"))
    assert run["current"] == "start check: tests on main (pnpm test) · 13m"
    orch._cmd_tick("pnpm test", 1380, True)  # the end records the duration
    orch._cmd_tick("pnpm test", 120)
    run = json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8"))
    assert run["current"] == "start check: tests on main (pnpm test) · 2m of about 23m"
    orch._journal(current="")
    orch._cmd_tick("pnpm lint", 60)
    assert json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8"))["current"] == "runs pnpm lint · 1m"
