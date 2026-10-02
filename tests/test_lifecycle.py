"""Wave 4: usage-limit pacing, RCA log for corrective work, run journal and session start/end."""
import json
import time
from pathlib import Path

import yaml

from autopilot.backends import SessionResult
from autopilot.cli import main as cli_main
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, git, make_project, phases_basic

NO_AUDIT = {"audit": {"completion_audit": False}}
FULL = {"symptom": "s", "root_cause": "r", "fix": "a.py:1 — x", "prevention": "test_a"}


def fix_phase(desc="broken thing"):
    return [{"id": "FIX001", "title": "Corrective", "priority": True, "tasks": [
        {"id": "FIX001-T01", "title": "fix it", "risk": "low", "description": desc, "acceptance_criteria": ["x"]}]}]


class FixBackend(FakeBackend):
    """Per attempt of FIX001-T01: the rca to report (None = omit) and whether to add a test file."""

    def __init__(self, attempts):
        super().__init__()
        self.attempts = attempts

    def run(self, req):
        res = super().run(req)
        if "implement task FIX001-T01" in req.prompt:
            n = len([1 for t, _ in self.prompts if t == "FIX001-T01"])
            rca, test = self.attempts[min(n - 1, len(self.attempts) - 1)]
            res.report = {k: v for k, v in res.report.items() if k != "rca"}
            if rca is not None:
                res.report["rca"] = rca
            if test:
                (Path(req.cwd) / "tests").mkdir(exist_ok=True)
                (Path(req.cwd) / "tests" / "test_regress.py").write_text("def test_x():\n    assert True\n")
        return res


class Planner(FakeBackend):
    """Its replan session adds one task to plan.yaml."""

    def run(self, req):
        if "replan remaining work" not in req.prompt:
            return super().run(req)
        self.calls.append(("replan", req.model))
        p = Path(req.cwd) / ".agent" / "plan.yaml"
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        d["phases"][-1]["tasks"].append({"id": "P02-T09", "title": "dark mode", "risk": "low", "acceptance_criteria": ["x"]})
        p.write_text(yaml.safe_dump(d), encoding="utf-8")
        return SessionResult(ok=True, cost=0.2, report={"summary": "added dark mode", "added": ["P02-T09"]})


def change_project(tmp_path, monkeypatch, fake):
    root = make_project(tmp_path, phases_basic())
    monkeypatch.setattr("autopilot.orchestrator.get_backend", lambda cfg: fake)
    return root, root / ".agent" / "plan.yaml"


def test_change_needs_yes_without_a_terminal(tmp_path, monkeypatch, capsys):
    fake = Planner()
    root, plan = change_project(tmp_path, monkeypatch, fake)
    assert cli_main(["change", "-C", str(root), "add dark mode"]) == 1
    out = capsys.readouterr().out
    assert "one replan session" in out and "--yes" in out and not fake.calls
    assert "P02-T09" not in plan.read_text(encoding="utf-8")


def test_change_yes_adds_task_and_names_it(tmp_path, monkeypatch, capsys):
    fake = Planner()
    root, plan = change_project(tmp_path, monkeypatch, fake)
    assert cli_main(["change", "-C", str(root), "--yes", "add dark mode"]) == 0
    assert "added: P02-T09 dark mode" in capsys.readouterr().out
    assert "P02-T09" in plan.read_text(encoding="utf-8") and git(root, "status", "--porcelain").strip() == ""
    assert [c[0] for c in fake.calls] == ["replan"]


def test_change_undo_restores_plan_and_backlog(tmp_path, monkeypatch, capsys):
    root, plan = change_project(tmp_path, monkeypatch, Planner())
    before = plan.read_bytes()
    answers = iter(["1", "2"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli_main(["change", "-C", str(root), "add dark mode"]) == 0
    assert "undone" in capsys.readouterr().out
    assert plan.read_bytes() == before and git(root, "status", "--porcelain").strip() == ""
    backlog = root / "docs" / "BACKLOG.md"
    assert not backlog.exists() or "dark mode" not in backlog.read_text(encoding="utf-8")
    assert Orchestrator(root, backend=Planner()).state.task("P02-T09")["status"] == "skipped"


def run_fix(tmp_path, attempts, desc="broken thing"):
    root = make_project(tmp_path, fix_phase(desc), NO_AUDIT)
    fake = FixBackend(attempts)
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    return root, fake, orch


def test_backoff_with_reset_sleeps_until_window_and_keeps_streak(tmp_path):
    root = make_project(tmp_path, phases_basic())
    sleeps = []
    orch = Orchestrator(root, backend=FakeBackend(), sleep=sleeps.append)
    orch.backoff(SessionResult(ok=False, rate_limited=True, reset_at=time.time() + 3600))
    assert len(sleeps) == 1 and 3715 <= sleeps[0] <= 3725 and orch.rate_limit_streak == 0
    orch.backoff(SessionResult(ok=False, rate_limited=True, reset_at=time.time() + 10))
    assert 125 <= sleeps[1] <= 135                                              # 10s + the 120s pad
    orch.backoff(SessionResult(ok=False, rate_limited=True, reset_at=time.time() - 500))
    assert sleeps[2] == 60                                                      # never under a minute
    orch.backoff(SessionResult(ok=False, rate_limited=True, reset_at=time.time() + 99 * 86400))
    assert sleeps[3] == 8 * 86400 and orch.rate_limit_streak == 0
    assert any("usage limit reached — sleeping until" in e["message"] for e in orch.state.events(10))
    orch.backoff(SessionResult(ok=False, rate_limited=True))
    assert sleeps[4] == 60 and orch.rate_limit_streak == 1                      # unexplained limits keep the ladder


def test_fix_task_without_rca_is_retried_with_the_reason(tmp_path):
    root, fake, orch = run_fix(tmp_path, [(None, True), (FULL, True)])
    prompts = [p for t, p in fake.prompts if t == "FIX001-T01"]
    assert len(prompts) == 2 and "RCA incomplete: missing symptom, root_cause, fix, prevention" in prompts[1]
    assert "RCA incomplete" not in prompts[0] and "This is a corrective task" in prompts[0]
    assert orch.state.status_map()["FIX001-T01"] == "done"


def test_partial_rca_names_the_missing_fields(tmp_path):
    root, fake, orch = run_fix(tmp_path, [({**FULL, "prevention": " "}, True), (FULL, True)])
    assert "RCA incomplete: missing prevention." in fake.prompts[1][1]


def test_bug_fix_without_a_test_file_is_retried(tmp_path):
    root, fake, orch = run_fix(tmp_path, [(FULL, False), (FULL, True)], desc="[bug] crashes on empty input")
    prompts = [p for t, p in fake.prompts if t == "FIX001-T01"]
    assert len(prompts) == 2 and "a bug fix must add or update a regression test" in prompts[1]
    assert orch.state.status_map()["FIX001-T01"] == "done"


def test_non_bug_fix_does_not_need_a_test_file(tmp_path):
    root, fake, orch = run_fix(tmp_path, [(FULL, False)], desc="[integration] wire a into b")
    assert len(fake.prompts) == 1 and orch.state.status_map()["FIX001-T01"] == "done"


def test_fix_with_rca_and_test_commits_an_rca_entry_with_the_fix(tmp_path):
    root, fake, orch = run_fix(tmp_path, [(FULL, True)], desc="[bug] crashes")
    rca = (root / "docs" / "RCA.md").read_text(encoding="utf-8")
    assert rca.startswith("# RCA log") and "· FIX001-T01 fix it" in rca
    for line in ("- Symptom: s", "- Root cause: r", "- Fix: a.py:1 — x", "- Prevention: test_a"):
        assert line in rca
    assert git(root, "status", "--porcelain").strip() == ""
    assert "[autopilot] FIX001-T01" in git(root, "log", "--format=%s", "--", "docs/RCA.md")
    hist = (root / ".agent" / "history" / "FIX001" / "FIX001-T01.md").read_text(encoding="utf-8")
    assert "## How to verify" in hist and "## Rollback" in hist and "git revert -m 1 <sha>" in hist
    assert "[autopilot] merge FIX001-T01" in hist


def test_ordinary_tasks_write_no_rca(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], NO_AUDIT)
    Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run()
    assert not (root / "docs" / "RCA.md").exists()


def test_fixer_writes_a_lenient_rca_entry(tmp_path):
    root = make_project(tmp_path, phases_basic())
    Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None, max_sessions=1).run()
    (root / "BROKEN").write_text("breakage")
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "app complete"
    rca = (root / "docs" / "RCA.md").read_text(encoding="utf-8")
    assert "· fixer repair main branch" in rca and "- Symptom: (not reported)" in rca
    assert "[autopilot] fix: repair main branch" in git(root, "log", "--format=%s", "--", "docs/RCA.md")


def test_task_prompt_has_recent_commits_with_a_real_subject(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    fake = FakeBackend()
    Orchestrator(root, backend=fake, sleep=lambda s: None).run()
    prompt = dict(fake.prompts)["P01-T02"]
    assert "## Recent commits" in prompt and "[autopilot] merge P01-T01" in prompt
    assert "{{" not in prompt


def test_run_journal_and_this_run_report(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    seen = []

    class Spy(FakeBackend):
        def run(self, req):
            seen.append(json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8")))
            return super().run(req)

    orch = Orchestrator(root, backend=Spy(), sleep=lambda s: None)
    outcome = orch.run()
    assert seen[0]["status"] == "running" and seen[0]["current"] == "task P01-T01 attempt 1"
    assert seen[0]["pid"] > 0 and seen[0]["first_session"] == 1
    run = json.loads((root / ".agent" / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "finished" and run["outcome"] == outcome == "plan complete"
    assert run["sessions"] == 4 and run["run_id"] and run["started_at"] and run["updated_at"]
    report = (root / ".agent" / "REPORT.md").read_text(encoding="utf-8")
    assert "## This run" in report and "- Outcome: plan complete" in report and "- Tasks done this run: 3" in report
    assert "- Sessions this run: 4" in report and "- Next action: none: plan complete" in report
    assert ".agent/run.json" in (root / ".gitignore").read_text(encoding="utf-8")
    assert git(root, "status", "--porcelain").strip() == ""


def test_journal_write_failure_never_breaks_the_run(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], NO_AUDIT)
    (root / ".agent" / "run.json.tmp").mkdir()               # a directory in the way: every write fails
    assert Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run() == "plan complete"


def test_report_next_action_names_the_oldest_open_decision(tmp_path):
    root = make_project(tmp_path, phases_basic(), NO_AUDIT)
    fake = FakeBackend(behaviours={"P01-T01": ["blocked"], "P02-T01": ["blocked"]},
                       unsticks={"P01-T01": {"class": "owner", "question": "q1"},
                                 "P02-T01": {"class": "owner", "question": "q2"}})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    report = (root / ".agent" / "REPORT.md").read_text(encoding="utf-8")
    assert "- Next action: answer D-001 in docs/NEEDS-YOU.md" in report and "- Open decisions: 2" in report
