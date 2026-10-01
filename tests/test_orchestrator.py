"""Orchestrator hardening: git isolation, run-start snapshot, small fixes (fake backend, no API calls)."""
import subprocess
from pathlib import Path

import pytest
import yaml

from autopilot.backends import SessionResult
from autopilot.cli import main as cli_main
from autopilot.gitops import GitError
from autopilot.orchestrator import Orchestrator, Stop
from autopilot.plan import Plan
from autopilot.proc import exclusive_lock
from test_autopilot import FakeBackend, git, make_project, phases_basic

NO_AUDIT = {"audit": {"completion_audit": False}}
KEY = "AKIAABCDEFGHIJKLMNOP"


def orch_for(root, fake=None, **kw):
    return Orchestrator(root, backend=fake or FakeBackend(), sleep=lambda s: None, **kw)


def commit_all(root, msg="init"):
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def events(orch, kind):
    return [e["message"] for e in orch.state.events(200) if e["kind"] == kind]


def test_main_guard_restores_main_and_fails_attempt(tmp_path):
    root = make_project(tmp_path, phases_basic())

    class Rogue(FakeBackend):
        done = False

        def run(self, req):
            if not self.done and "implement task P01-T01" in req.prompt:
                Rogue.done = True
                cwd = Path(req.cwd)
                git(cwd, "checkout", "-q", "main")
                (cwd / "rogue.txt").write_text("x")
                git(cwd, "add", "-A")
                git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "rogue commit")
                return SessionResult(ok=True, cost=0.1, report={"status": "done", "summary": "sneaky"})
            return super().run(req)

    orch = orch_for(root, Rogue())
    assert orch.run() == "app complete"
    assert "rogue" not in git(root, "log", "--format=%s")
    assert "rogue.txt" not in git(root, "ls-files")
    assert events(orch, "main_guard")
    assert orch.state.task("P01-T01")["attempts"] == 2          # the rogue attempt counted as failed
    assert orch.state.status_map()["P01-T01"] == "done"


def test_audit_runs_on_throwaway_branch(tmp_path):
    root = make_project(tmp_path, phases_basic())

    class Committer(FakeBackend):
        def run(self, req):
            res = super().run(req)
            if "implementation audit" in req.prompt:
                cwd = Path(req.cwd)
                (cwd / "sneaky.txt").write_text("x")
                git(cwd, "add", "-A")
                git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "sneaky audit commit")
            return res

    assert orch_for(root, Committer()).run() == "app complete"
    assert "sneaky" not in git(root, "log", "--format=%s")
    assert "sneaky.txt" not in git(root, "ls-files")
    assert "autopilot/audit" not in git(root, "branch", "--list")


def test_push_sends_only_autopilot_tags(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    root = make_project(tmp_path, phases_basic()[:1], {
        "git": {"push": True, "remote": "origin"}, "audit": {"completion_audit": False},
        "deploy": {"staging": {"enabled": True, "cmd": "python -c \"pass\"", "health_url": ""}}})
    git(root, "remote", "add", "origin", str(remote))
    orch = orch_for(root)
    assert orch.run() == "plan complete"
    git(root, "tag", "v1")
    git(root, "tag", "autopilot-prod-forged")       # e.g. created by an agent session: must never be pushed
    orch.git.tag("autopilot-staging-P01")
    orch.git.push("origin", "main")
    tags = git(root, "ls-remote", "--tags", "origin")
    assert "refs/tags/autopilot-staging-P01" in tags
    assert "refs/tags/v1" not in tags and "autopilot-prod-forged" not in tags
    assert git(remote, "rev-parse", "main").strip() == git(root, "rev-parse", "main").strip()


def test_planted_hooks_and_filters_never_run(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], NO_AUDIT)

    class Planter(FakeBackend):
        def run(self, req):
            cwd = Path(req.cwd)
            hook = "#!/bin/sh\necho hooked > HOOKED.txt\n"
            for d in (cwd / "evil-hooks", cwd / ".git" / "hooks"):
                d.mkdir(exist_ok=True)
                for name in ("pre-commit", "post-commit", "post-merge", "post-checkout"):
                    (d / name).write_text(hook, newline="\n")
                    (d / name).chmod(0o755)
            git(cwd, "config", "core.hooksPath", "evil-hooks")
            git(cwd, "config", "filter.evil.clean", "python -c \"print('INJECTED')\"")
            (cwd / ".gitattributes").write_text("*.txt filter=evil\n")
            return super().run(req)

    assert orch_for(root, Planter()).run() == "plan complete"
    assert not (root / "HOOKED.txt").exists() and "HOOKED" not in git(root, "ls-files")
    assert git(root, "show", "main:src/P01-T01.txt").strip() == "impl P01-T01"   # no filter rewrote the blob
    assert git(root, "config", "--get", "filter.evil.clean").strip() == ""
    assert git(root, "config", "--get", "core.hooksPath").strip() == ""


def test_dirty_tree_with_secret_is_stashed(tmp_path):
    root = make_project(tmp_path, phases_basic())
    commit_all(root)
    (root / "leak.txt").write_text(f'key = "{KEY}"\n')
    orch = orch_for(root, max_sessions=1)
    orch.run()
    assert git(root, "stash", "list").strip()
    assert "leak.txt" not in git(root, "ls-files")
    assert KEY not in git(root, "log", "-p", "main")
    msgs = events(orch, "stashed")
    assert msgs and "1" in msgs[0] and "git stash pop" in msgs[0]
    assert not any(KEY in e["message"] or "AKIA" in e["message"] for e in orch.state.events(200))


def test_dirty_tree_without_secret_is_committed(tmp_path):
    root = make_project(tmp_path, phases_basic())
    commit_all(root)
    (root / "notes.txt").write_text("harmless\n")
    orch_for(root, max_sessions=1).run()
    assert not git(root, "stash", "list").strip()
    assert "notes.txt" in git(root, "ls-files")
    assert "snapshot of uncommitted changes" in git(root, "log", "--format=%s")


def test_replan_cannot_edit_done_task_definition(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    orch_for(root).run()

    class Editor(FakeBackend):
        def run(self, req):
            p = Path(req.cwd) / ".agent" / "plan.yaml"
            data = yaml.safe_load(p.read_text())
            data["phases"][0]["tasks"][0]["title"] = "rewritten history"
            p.write_text(yaml.safe_dump(data))
            return SessionResult(ok=True, report={"summary": "edited"})

    orch2 = orch_for(root, Editor())
    orch2.reload_plan()
    assert orch2.replan("test") is False
    assert Plan.load(root / ".agent" / "plan.yaml").task_by_id["P01-T01"].title == "a"
    assert events(orch2, "replan_rejected")


def test_reopened_phase_closes_again(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    orch = orch_for(root)
    orch.run()
    assert orch.state.phase("P01")["status"] == "done"
    git(root, "rm", "-q", "src/P01-T02.txt")                   # so the fake agent has something to redo
    commit_all(root, "drop T02 output")
    orch.state.set_task("P01-T02", status="pending", attempts=0)
    orch2 = orch_for(root)
    orch2.run()
    assert orch2.state.status_map()["P01-T02"] == "done"
    assert orch2.state.phase("P01")["status"] == "done"
    assert git(root, "log", "--format=%s").count("close phase P01") == 2


def test_completion_rounds_reset_when_plan_grows(tmp_path):
    root = make_project(tmp_path, phases_basic())
    orch = orch_for(root)
    orch.git.ensure_repo("main")
    orch.reload_plan()
    orch.state.set_meta("completion_rounds", 2)
    p = root / ".agent" / "plan.yaml"
    data = yaml.safe_load(p.read_text())
    data["phases"][1]["tasks"].append({"id": "P02-T02", "title": "new"})
    p.write_text(yaml.safe_dump(data))
    orch.reload_plan()
    assert orch.state.get_meta("completion_rounds") == 0


def test_merge_failure_does_not_crash(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    orch = orch_for(root)
    real, calls = orch.git.merge, []

    def flaky(*a):
        if not calls:
            calls.append(1)
            raise GitError("boom")
        return real(*a)

    orch.git.merge = flaky
    assert orch.run() == "plan complete"
    assert orch.state.task("P01-T01")["attempts"] == 2
    assert all(v == "done" for v in orch.state.status_map().values())
    assert git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_fix_counter_derived_from_plan(tmp_path):
    root = make_project(tmp_path, phases_basic())
    gaps = [{"title": "wire a", "risk": "medium", "description": "d"}]
    fake = FakeBackend(audits=[{"complete": False, "completion_pct": 80, "gaps": gaps},
                               {"complete": True, "completion_pct": 100, "gaps": []}])
    assert orch_for(root, fake).run() == "app complete"
    orch2 = orch_for(root)
    orch2.reload_plan()
    orch2.state.set_meta("fix_counter", 0)            # state.db lost, plan committed
    assert orch2.add_corrective_phase([{"title": "t"}], "x") == "FIX002"


def test_blocking_config_error_is_fatal(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"commands": {"test": []}})
    fake = FakeBackend()
    out = orch_for(root, fake).run()
    assert out.startswith("fatal: config: ") and "no verify commands" in out
    assert fake.calls == []
    assert cli_main(["validate", "-C", str(root)]) == 1


def test_approve_while_run_active_is_queued(tmp_path):
    marker = tmp_path / "prod.log"
    cmd = "python -c \"import os; open('" + marker.as_posix() + "','a').write(os.environ['AUTOPILOT_PHASE']+'\\n')\""
    root = make_project(tmp_path, phases_basic(), {"deploy": {"prod": {"enabled": True, "cmd": cmd, "auto": False}}})
    orch = orch_for(root)
    assert orch.run() == "app complete"
    assert orch.state.phase("P01")["prod_status"] == "awaiting_approval"
    assert not marker.exists()
    with exclusive_lock(root / ".agent" / "run.lock"):
        assert cli_main(["approve", "P01", "-C", str(root)]) == 0
    assert (root / ".agent" / "approvals" / "P01").exists()
    assert not marker.exists()
    orch2 = orch_for(root)
    orch2.run()
    assert marker.read_text().split() == ["P01"]
    assert orch2.state.phase("P01")["prod_status"] == "deployed"
    assert not (root / ".agent" / "approvals" / "P01").exists()


def test_session_budget_floor_removed(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"budget_usd": {"total": 1}})
    orch = orch_for(root)
    sid = orch.state.start_session("task", None, None, 1, "sonnet")
    orch.state.end_session(sid, cost=0.5, ok=True)
    assert orch.session_budget() == pytest.approx(0.5)
    sid = orch.state.start_session("task", None, None, 1, "sonnet")
    orch.state.end_session(sid, cost=0.495, ok=True)
    with pytest.raises(Stop):
        orch.session_budget()


def test_task_cost_is_recorded(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    orch = orch_for(root, FakeBackend(behaviours={"P01-T02": ["nothing", "ok"]}))
    orch.run()
    for t in orch.state.tasks():
        assert t["cost"] == pytest.approx(orch.state.cost(task_id=t["id"])) and t["cost"] > 0
    assert orch.state.task("P01-T02")["cost"] == pytest.approx(0.35)
