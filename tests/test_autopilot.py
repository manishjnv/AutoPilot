"""End-to-end tests with a scripted fake agent backend (no API calls)."""
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from autopilot.backends import SessionResult, parse_report
from autopilot.cli import main as cli_main
from autopilot.gate import scan_secrets
from autopilot.orchestrator import Orchestrator
from autopilot.plan import Plan, PlanError

TEST_CMD = "python -c \"import pathlib,sys; sys.exit(1 if pathlib.Path('BROKEN').exists() else 0)\""


RCA = {"symptom": "s", "root_cause": "r", "fix": "f.py:1 — changed", "prevention": "a test"}


class FakeBackend:
    """Behaves like an agent: writes files for tasks, returns JSON reports."""

    def __init__(self, behaviours=None, audits=None, unsticks=None):
        self.behaviours = behaviours or {}   # task_id -> list of actions per attempt
        self.audits = list(audits or [])     # queued audit reports
        self.unsticks = unsticks or {}       # task_id -> unstick report (default: technical diagnosis)
        self.calls = []
        self.prompts = []                    # (task_id, prompt) of every task session
        self.failing_features = set()        # feature ids the functional check reports as failing

    def run(self, req):
        cwd = Path(req.cwd)
        u = re.search(r"^# Assignment: unstick task (\S+)", req.prompt, re.M)
        if u:
            self.calls.append(("unstick", req.model))
            rep = self.unsticks.get(u.group(1), {"class": "technical", "diagnosis": "fix it"})
            return SessionResult(ok=True, cost=0.1, report=rep)
        if req.prompt.startswith("# Assignment: review task"):
            self.calls.append(("review", req.model))
            return SessionResult(ok=True, cost=0.1, report={"verdict": "pass", "summary": "ok", "findings": []})
        m = re.search(r"implement task (\S+)", req.prompt)
        if m:
            tid = m.group(1)
            self.prompts.append((tid, req.prompt))
            n = sum(1 for c in self.calls if c[0] == tid)
            self.calls.append((tid, req.model))
            actions = self.behaviours.get(tid, ["ok"])
            action = actions[min(n, len(actions) - 1)]
            if action == "nothing":
                return SessionResult(ok=True, text="did nothing", cost=0.1, report={"status": "done"})
            if action == "break":
                (cwd / "BROKEN").write_text("x")
            if action == "blocked":
                return SessionResult(ok=True, cost=0.1, report={"status": "blocked", "blocker": "needs API key"})
            if action == "ratelimit":
                return SessionResult(ok=False, error="429 rate limit", rate_limited=True)
            (cwd / "src").mkdir(exist_ok=True)
            (cwd / "src" / f"{tid}.txt").write_text(f"impl {tid}\n")
            (cwd / "src" / "__pycache__").mkdir(exist_ok=True)
            (cwd / "src" / "__pycache__" / "junk.pyc").write_text("junk")
            return SessionResult(ok=True, cost=0.25, report={
                "status": "done", "summary": f"built {tid}", "decisions": [f"{tid} uses txt files"],
                "followups": [], "files_changed": [f"src/{tid}.txt"],
                **({"rca": RCA} if tid.startswith("FIX") else {})})
        if "implementation audit" in req.prompt:
            self.calls.append(("audit", req.model))
            (cwd / "AUDITOR_SCRIBBLE.txt").write_text("should be discarded")
            rep = self.audits.pop(0) if self.audits else {"complete": True, "completion_pct": 100, "gaps": []}
            return SessionResult(ok=True, cost=0.5, report=rep)
        if req.prompt.startswith("# Assignment: functional check of phase"):
            self.calls.append(("verify", req.model))
            ids = re.findall(r"^- `(\S+)`", req.prompt, re.M)
            return SessionResult(ok=True, cost=0.1, report={"features": [
                {"id": i, "passes": i not in self.failing_features, "evidence": f"ran {i}"} for i in ids]})
        r = re.search(r'^# Assignment: research "(.+)" for task', req.prompt, re.M)
        if r:
            self.calls.append(("research", req.model))
            return SessionResult(ok=True, cost=0.1, report={
                "topic": r.group(1), "summary": f"notes on {r.group(1)}", "findings": ["f1 (Doc)"],
                "recommendation": "use the official SDK", "sources": [{"title": "Doc", "url": "https://example.com/doc"}]})
        d = re.search(r"^# Assignment: decide the approach for task (\S+)", req.prompt, re.M)
        if d:
            self.calls.append(("decide", req.model))
            return SessionResult(ok=True, cost=0.2, report={
                "title": f"Approach for {d.group(1)}", "context": "c", "criteria": ["simple"],
                "options": [{"name": "A", "score": 8}, {"name": "B", "score": 5}], "decision": "A", "rationale": "simpler"})
        if "repair the main branch" in req.prompt:
            self.calls.append(("fixer", req.model))
            b = cwd / "BROKEN"
            if b.exists():
                b.unlink()
            (cwd / "FIXED.txt").write_text("fixed")
            return SessionResult(ok=True, cost=0.3, report={"status": "done", "summary": "removed BROKEN"})
        if "replan remaining work" in req.prompt:
            self.calls.append(("replan", req.model))
            return SessionResult(ok=True, cost=0.2, report={"summary": "no changes"})
        raise AssertionError("unexpected prompt: " + req.prompt[:200])


def make_project(tmp_path: Path, phases: list[dict], extra_cfg: dict | None = None) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    assert cli_main(["init", "-C", str(root), "--stack", "generic"]) == 0
    cfg = {"name": "demo", "commands": {"test": [TEST_CMD]}, "audit": {"every_n_phases": 0},
           "replan": {"every_n_phases": 0}, "budget_usd": {"wait_for_next_day": False},
           "needs_you": {"wait": False}}
    if extra_cfg:
        for k, v in extra_cfg.items():
            cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) else v
    (root / ".agent" / "project.yaml").write_text(yaml.safe_dump(cfg))
    (root / ".agent" / "plan.yaml").write_text(yaml.safe_dump({"goal": "demo app", "phases": phases}))
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    return root


def phases_basic():
    return [
        {"id": "P01", "title": "One", "tasks": [
            {"id": "P01-T01", "title": "a", "risk": "low", "acceptance_criteria": ["x"]},
            {"id": "P01-T02", "title": "b", "risk": "medium", "depends_on": ["P01-T01"]}]},
        {"id": "P02", "title": "Two", "tasks": [
            {"id": "P02-T01", "title": "c", "risk": "high"}]},
    ]


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout


# ---------------------------------------------------------------- plan
def test_plan_cycle_and_unknown_dep():
    with pytest.raises(PlanError):
        Plan.from_dict({"phases": [{"id": "P1", "tasks": [
            {"id": "A", "title": "a", "depends_on": ["B"]}, {"id": "B", "title": "b", "depends_on": ["A"]}]}]})
    with pytest.raises(PlanError):
        Plan.from_dict({"phases": [{"id": "P1", "tasks": [{"id": "A", "title": "a", "depends_on": ["Z"]}]}]})


def test_soft_vs_strict_phase_dependency():
    plan = Plan.from_dict({"phases": phases_basic()})
    status = {"P01-T01": "done", "P01-T02": "blocked", "P02-T01": "pending"}
    assert plan.next_ready(status, "soft").id == "P02-T01"
    assert plan.next_ready(status, "strict") is None


def test_parse_report_and_secrets():
    text = 'blah\n```json\n{"status": "done", "summary": "ok"}\n```'
    assert parse_report(text)["summary"] == "ok"
    assert scan_secrets(['key = "AKIAABCDEFGHIJKLMNOP"'])
    assert not scan_secrets(["x = os.environ['API_KEY']"])


# ---------------------------------------------------------------- end to end
def test_full_run_retry_escalation_docs(tmp_path):
    root = make_project(tmp_path, phases_basic())
    fake = FakeBackend(behaviours={"P01-T02": ["nothing", "break", "ok"]})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    outcome = orch.run()
    assert outcome == "app complete"
    st = orch.state.status_map()
    assert all(v == "done" for v in st.values()), st
    # escalation ladder for medium: sonnet, sonnet, opus
    models = [m for t, m in fake.calls if t == "P01-T02"]
    assert models == ["sonnet", "sonnet", "opus"]
    # docs written by orchestrator
    ad = root / ".agent"
    assert (ad / "history" / "P01" / "P01-T01.md").exists()
    assert (ad / "history" / "P01" / "PHASE.md").exists()
    assert "P01-T01 uses txt files" in (ad / "DECISIONS.md").read_text()
    assert "P02-T01" in (ad / "HANDOFF.md").read_text()
    assert (root / "CHANGELOG.md").exists()
    assert not (root / "BROKEN").exists()
    assert not (root / "AUDITOR_SCRIBBLE.txt").exists()      # auditor is read-only
    assert git(root, "status", "--porcelain").strip() == ""
    assert "__pycache__" not in git(root, "ls-files")                 # junk never committed
    assert "[autopilot] merge P02-T01" in git(root, "log", "--oneline")
    assert git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_blocked_task_is_parked_not_blocking(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"audit": {"completion_audit": False}})
    fake = FakeBackend(behaviours={"P01-T01": ["blocked"]})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    st = orch.state.status_map()
    assert st["P01-T01"] == "blocked"
    assert st["P01-T02"] == "pending"      # explicit dependency on a blocked task waits
    assert st["P02-T01"] == "done"         # later phase still proceeds (soft)
    assert orch.state.phase("P01")["status"] is None or orch.state.phase("P01")["status"] == "open"


def test_completion_audit_self_corrects(tmp_path):
    root = make_project(tmp_path, phases_basic())
    gaps = [{"title": "Wire module a into b", "kind": "integration", "risk": "medium",
             "description": "a is not called", "acceptance_criteria": ["b calls a"]}]
    fake = FakeBackend(audits=[{"complete": False, "completion_pct": 80, "gaps": gaps},
                               {"complete": True, "completion_pct": 100, "gaps": []}])
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "app complete"
    plan = Plan.load(root / ".agent" / "plan.yaml")
    assert "FIX001" in plan.phase_by_id and plan.phase_by_id["FIX001"].priority
    assert orch.state.status_map()["FIX001-T01"] == "done"
    assert len(list((root / ".agent" / "audits").glob("*-completion.md"))) == 2


def test_rate_limit_not_counted_and_fixer_repairs_main(tmp_path):
    root = make_project(tmp_path, phases_basic())
    first = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None, max_sessions=1)
    first.run()                                         # P01-T01 done -> no longer greenfield
    (root / "BROKEN").write_text("breakage introduced outside autopilot")
    fake = FakeBackend(behaviours={"P01-T02": ["ratelimit", "ok"]})
    sleeps = []
    orch = Orchestrator(root, backend=fake, sleep=sleeps.append)
    assert orch.run() == "app complete"
    assert ("fixer", "sonnet") in fake.calls  # U5: the fixer ladder starts on sonnet
    assert orch.state.task("P01-T02")["attempts"] == 1
    assert sleeps and sleeps[0] == 60


def test_greenfield_skips_fixer(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"commands": {"test": ["python -c \"import os,sys; sys.exit(0 if os.path.isdir('src') else 1)\""]}})
    fake = FakeBackend()
    assert Orchestrator(root, backend=fake, sleep=lambda s: None).run() == "app complete"
    assert not any(c[0] == "fixer" for c in fake.calls)


def test_stop_file_and_session_limit(tmp_path):
    root = make_project(tmp_path, phases_basic())
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None, max_sessions=1)
    assert "session limit" in orch.run()
    assert orch.state.status_map()["P01-T01"] == "done"
    (root / ".agent" / "STOP").write_text("x")
    orch2 = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert "STOP" in orch2.run()


def test_replan_cannot_remove_done_tasks(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch.run()

    class Vandal(FakeBackend):
        def run(self, req):
            p = Path(req.cwd) / ".agent" / "plan.yaml"
            p.write_text(yaml.safe_dump({"goal": "x", "phases": [{"id": "P09", "title": "new", "tasks": [
                {"id": "P09-T01", "title": "n"}]}]}))
            return SessionResult(ok=True, report={"summary": "rewrote everything"})

    orch2 = Orchestrator(root, backend=Vandal(), sleep=lambda s: None)
    orch2.reload_plan()
    assert orch2.replan("test") is False
    assert "P01-T01" in Plan.load(root / ".agent" / "plan.yaml").task_by_id


def test_budget_stop(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 0.3}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert "total budget" in orch.run()


def test_staging_deploy_failure_creates_corrective_phase(tmp_path):
    marker = tmp_path / "deploys.log"
    root = make_project(tmp_path, phases_basic()[:1], {
        "deploy": {"staging": {"enabled": True,
                               "cmd": "python -c \"import os,sys; open('" + marker.as_posix() + "','a').write(os.environ['AUTOPILOT_PHASE']+'\\n'); "
                                      "sys.exit(0 if os.path.exists('src/FIX001-T01.txt') else 1)\"",
                               "health_url": ""}},
        "audit": {"completion_audit": False}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch.run()
    plan = Plan.load(root / ".agent" / "plan.yaml")
    assert "FIX001" in plan.phase_by_id                        # deploy failure -> corrective task
    assert orch.state.status_map()["FIX001-T01"] == "done"
    assert marker.read_text().split() == ["P01", "FIX001"]     # corrective phase redeployed successfully
    assert orch.state.phase("FIX001")["staging_ref"]


def test_claude_cli_backend_parses_output(tmp_path, monkeypatch):
    from autopilot.backends import SessionRequest
    from autopilot.backends.claude_cli import ClaudeCLIBackend
    from autopilot.config import Config

    (tmp_path / "stub.py").write_text("import json,sys\nsys.stdin.read()\n"
                                      "print(json.dumps({'type':'result','is_error':False,'session_id':'s1','total_cost_usd':0.42,"
                                      "'result':'done\\n```json\\n{\"status\":\"done\",\"summary\":\"ok\"}\\n```','args':sys.argv}))\n")
    if sys.platform == "win32":
        stub = tmp_path / "claude.cmd"
        stub.write_text(f'@"{sys.executable}" "%~dp0stub.py" %*\n')
    else:
        stub = tmp_path / "claude"
        stub.write_text(f"#!{sys.executable}\n" + (tmp_path / "stub.py").read_text())
        stub.chmod(0o755)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", str(stub))
    be = ClaudeCLIBackend(Config.load(tmp_path))
    cmd = be.build_cmd(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path), budget_usd=3, read_only=True))
    assert "--max-budget-usd" in cmd and "Write" in cmd and "bypassPermissions" in cmd
    res = be.run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert res.ok and res.cost == 0.42 and res.report["summary"] == "ok" and res.session_id == "s1"


def test_leftover_old_prefix_branch_is_discarded(tmp_path):
    root = make_project(tmp_path, phases_basic())
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    git(root, "checkout", "-q", "-b", "autodev/P01-T01")
    (root / "PARTIAL.txt").write_text("half done")
    Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run()
    assert "autodev/P01-T01" not in git(root, "branch", "--list")
    assert not (root / "PARTIAL.txt").exists()
    assert git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_claude_bin_falls_back_to_old_env(tmp_path, monkeypatch):
    from autopilot.backends.claude_cli import ClaudeCLIBackend
    from autopilot.config import Config

    monkeypatch.delenv("AUTOPILOT_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("AUTODEV_CLAUDE_BIN", "/old/claude")
    assert ClaudeCLIBackend(Config.load(tmp_path)).binary == "/old/claude"
