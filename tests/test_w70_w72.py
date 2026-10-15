"""W70: one session per checkout (the hook and the ap commands refuse while a run holds the lock).
W71: an environment error on the main check asks once, never three code attempts.
W72: the stop reason on every surface."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

from autopilot.cli import main as cli_main
from autopilot.orchestrator import Orchestrator
from autopilot.plain import ending
from autopilot.proc import exclusive_lock
from test_autopilot import FakeBackend, make_project, phases_basic

GUARD = Path(__file__).resolve().parent.parent / "plugin" / "scripts" / "guard.py"


def _guard(payload: dict) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), capture_output=True, text=True,
                       timeout=60)
    return p.returncode, p.stderr


def test_the_hook_refuses_edits_and_git_moves_only_while_a_run_holds_the_checkout(tmp_path):
    root = tmp_path / "proj"
    (root / ".agent").mkdir(parents=True)
    (root / ".agent" / "run.json").write_text(json.dumps({"started_at": "2026-10-15T16:05:53"}), encoding="utf-8")
    lock = root / ".agent" / "run.lock"
    lock.touch()
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(root / "src" / "x.py")}, "cwd": str(root)}
    assert _guard(edit) == (0, "")  # no run: allowed
    with exclusive_lock(lock):  # a run holds the lock
        rc, err = _guard(edit)
        assert rc == 2 and "since 16:05" in err and "ap stop" in err
        rc, _ = _guard({"tool_name": "Write", "tool_input": {"file_path": str(root / ".agent" / "plan.yaml")},
                        "cwd": str(root / "src")})
        assert rc == 0  # .agent/ stays open (ap answer, ap change write there)
        rc, _ = _guard({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(root)})
        assert rc == 2
        rc, _ = _guard({"tool_name": "Bash", "tool_input": {"command": "pnpm test && git status"}, "cwd": str(root)})
        assert rc == 0
        rc, _ = _guard({"tool_name": "Read", "tool_input": {"file_path": str(root / "src" / "x.py")}, "cwd": str(root)})
        assert rc == 0
    assert _guard(edit) == (0, "")  # the run ended: allowed again


def test_the_hook_is_wired_as_a_pre_tool_use_hook():
    hooks = json.loads((GUARD.parent.parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    pre = hooks["hooks"]["PreToolUse"]
    assert pre[0]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit|Bash"
    assert "guard.py" in pre[0]["hooks"][0]["command"]


def test_ap_commands_that_edit_the_tree_refuse_while_a_run_is_active(tmp_path, monkeypatch, capsys):
    root = make_project(tmp_path, phases_basic())
    monkeypatch.setattr("autopilot.cli.run_active", lambda r: True)
    for cmd in ("onboard", "quickstart", "init"):
        assert cli_main([cmd, "-C", str(root)]) == 2
    assert capsys.readouterr().out.count("type `ap stop` first") == 3


ENV_RED = ("python -c \"import pathlib,sys; up=pathlib.Path('up').exists(); "
           "print('ok' if up else 'error: connect ECONNREFUSED 127.0.0.1:5432'); sys.exit(0 if up else 1)\"")
SETUP_UP = "python -c \"open('up', 'w').close()\""


def _env_project(tmp_path):
    """One task done with the service up; then the service is down again (the `up` file is gone)."""
    cfg = {"commands": {"test": [ENV_RED], "setup": [SETUP_UP]}, "unstick": {"enabled": False},
           "decide": {"enabled": False}, "retries": {"max_fixer_attempts": 3}, "audit": {"completion_audit": False}}
    root = make_project(tmp_path, phases_basic(), cfg)
    Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None, max_sessions=1).run()
    (root / "up").unlink(missing_ok=True)
    return root


def _fixer_sessions(orch) -> int:
    return orch.state.db.execute("SELECT COUNT(*) FROM sessions WHERE kind='fixer'").fetchone()[0]


def test_an_environment_error_on_main_runs_setup_and_needs_no_fixer(tmp_path):
    root = _env_project(tmp_path)
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"  # the audit is off in this project
    assert _fixer_sessions(orch) == 0


def test_an_environment_error_that_setup_cannot_fix_asks_once_and_stops(tmp_path):
    root = _env_project(tmp_path)
    cfg_path = root / ".agent" / "project.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["commands"]["setup"] = []  # nothing brings the service up
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    out = orch.run()
    assert out.startswith("stalled: ") and "environment" in out
    assert _fixer_sessions(orch) == 0
    open_ = orch.state.decisions("OPEN")
    assert len(open_) == 1 and open_[0]["kind"] == "env" and "ECONNREFUSED" in open_[0]["question"]
    assert "ECONNREFUSED" in (root / "docs" / "NEEDS-YOU.md").read_text(encoding="utf-8")


def test_the_stop_reason_names_the_source_and_the_time(tmp_path):
    root = make_project(tmp_path, phases_basic())
    assert cli_main(["stop", "-C", str(root)]) in (0, None)
    text = (root / ".agent" / "STOP").read_text(encoding="utf-8").splitlines()
    assert text[0] == "stop requested" and text[1].startswith("from ap stop at ")
    out = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run()
    assert out.startswith("stopped by .agent/STOP file (stop requested, from ap stop at ")
    assert ending(out).startswith("The build stopped. You asked for the stop (stop requested, from ap stop at ")
    assert ending("stopped by .agent/STOP file") == "The build stopped. You asked for the stop."
