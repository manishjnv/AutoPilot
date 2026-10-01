"""Wave 3: the run never waits for the owner (unstick ladder, NEEDS-YOU.md, red gates become work)."""
from pathlib import Path

from autopilot.backends import SessionResult
from autopilot.cli import main as cli_main
from autopilot.decisions import parse_answers
from autopilot.orchestrator import Orchestrator
from autopilot.plan import Plan
from test_autopilot import FakeBackend, git, make_project, phases_basic

NO_AUDIT = {"audit": {"completion_audit": False}}
OWNER = {"class": "owner", "question": "Which payment provider?", "checked": "Stripe and Razorpay docs",
         "why": "needs your business account", "suggestion": "Stripe"}


def orch_for(root, fake=None, sleep=lambda s: None, **kw):
    return Orchestrator(root, backend=fake or FakeBackend(), sleep=sleep, **kw)


def show(root, ref):
    import subprocess
    return subprocess.run(["git", "show", ref], cwd=root, capture_output=True, check=True).stdout.decode("utf-8")


def events(orch, kind):
    return [e["message"] for e in orch.state.events(300) if e["kind"] == kind]


def parked_run(tmp_path, **extra):
    root = make_project(tmp_path, phases_basic(), extra or None)
    fake = FakeBackend(behaviours={"P01-T01": ["blocked"]}, unsticks={"P01-T01": OWNER})
    orch = orch_for(root, fake)
    return root, fake, orch, orch.run()


def test_technical_unstick_gives_one_more_attempt_with_diagnosis(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1])
    fake = FakeBackend(behaviours={"P01-T01": ["nothing", "nothing", "ok"]},
                       unsticks={"P01-T01": {"class": "technical", "diagnosis": "DIAG-XYZ the import is wrong"}})
    orch = orch_for(root, fake)
    orch.run()
    prompts = [p for t, p in fake.prompts if t == "P01-T01"]
    assert len(prompts) == 3 and "DIAG-XYZ" in prompts[2] and not any("DIAG-XYZ" in p for p in prompts[:2])
    assert [c[0] for c in fake.calls].count("unstick") == 1
    assert orch.state.status_map()["P01-T01"] == "done"
    assert not orch.state.decisions()
    assert "autopilot/unstick" not in git(root, "branch", "--list")


def test_spec_unstick_records_decision_and_retries(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1])
    spec = {"class": "spec", "decision": "use SQLite", "options_considered": ["SQLite", "Postgres"]}
    fake = FakeBackend(behaviours={"P01-T01": ["nothing", "nothing", "ok"]}, unsticks={"P01-T01": spec})
    orch = orch_for(root, fake)
    orch.run()
    dec = (root / ".agent" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "[P01-T01] DECISION (auto): use SQLite (options considered: SQLite; Postgres)" in dec
    assert "use SQLite" in [p for t, p in fake.prompts if t == "P01-T01"][2]
    assert orch.state.status_map()["P01-T01"] == "done"


def test_extra_attempt_failing_parks_with_decision(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1])
    fake = FakeBackend(behaviours={"P01-T01": ["nothing"]})
    orch = orch_for(root, fake)
    assert orch.run().startswith("stalled: waiting on 1 decisions")
    d = orch.state.decision("D-001")
    assert d["kind"] == "task" and "still fails after a diagnosis" in d["question"] and "fix it" in d["checked"]
    assert [c[0] for c in fake.calls].count("unstick") == 1 and orch.state.task("P01-T01")["attempts"] == 3


def test_owner_decision_parks_task_and_run_continues(tmp_path):
    root, fake, orch, outcome = parked_run(tmp_path)
    assert outcome == "stalled: waiting on 1 decisions (see docs/NEEDS-YOU.md)"
    st = orch.state.status_map()
    assert st["P01-T01"] == "blocked" and st["P01-T02"] == "pending" and st["P02-T01"] == "done"
    d = orch.state.decision("D-001")
    assert d["status"] == "OPEN" and d["blocks"] == '["P01-T01", "P01-T02"]'
    text = show(root, "main:docs/NEEDS-YOU.md")
    assert "## D-001 · P01-T01 a · OPEN" in text and "Which payment provider?" in text
    assert "Blocked until answered: P01-T01, P01-T02" in text and "My suggestion: Stripe" in text
    assert "[autopilot] needs-you D-001" in git(root, "log", "--format=%s")
    assert any("D-001" in m for m in events(orch, "needs_you"))
    assert git(root, "status", "--porcelain").strip() == ""
    assert "Needs you (1 open)" in (root / ".agent" / "REPORT.md").read_text(encoding="utf-8")
    assert [c[0] for c in fake.calls].count("unstick") == 1

    assert cli_main(["answer", "-C", str(root), "D-001", "use X"]) == 0
    assert cli_main(["answer", "-C", str(root), "D-001", "again"]) == 1     # no longer open
    assert cli_main(["answer", "-C", str(root), "D-099", "x"]) == 1
    fake2 = FakeBackend()
    orch2 = orch_for(root, fake2)
    assert orch2.run() == "app complete"
    assert "[D-001] Which payment provider? → use X" in (root / ".agent" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "use X" in [p for t, p in fake2.prompts if t == "P01-T01"][0]
    assert all(v == "done" for v in orch2.state.status_map().values())
    assert orch2.state.decision("D-001")["status"] == "APPLIED"
    assert "D-001 · P01-T01 a · DONE" in (root / "docs" / "NEEDS-YOU.md").read_text(encoding="utf-8")


def test_answer_written_in_file_is_applied(tmp_path):
    root, _, _, _ = parked_run(tmp_path)
    path = root / "docs" / "NEEDS-YOU.md"
    path.write_text(path.read_text(encoding="utf-8").replace("- Your answer:", "- Your answer: use Y", 1), encoding="utf-8")
    assert parse_answers(path.read_text(encoding="utf-8")) == {"D-001": "use Y"}
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "owner answer")
    fake2 = FakeBackend()
    orch2 = orch_for(root, fake2)
    assert orch2.run() == "app complete"
    assert "use Y" in [p for t, p in fake2.prompts if t == "P01-T01"][0]
    assert "→ use Y" in (root / ".agent" / "DECISIONS.md").read_text(encoding="utf-8")


def test_wait_mode_polls_until_answered(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"needs_you": {"wait": True, "poll_minutes": 1}})
    fake = FakeBackend(behaviours={"P01-T01": ["blocked", "ok"]}, unsticks={"P01-T01": OWNER})
    sleeps, box = [], []

    def answer(secs):
        sleeps.append(secs)
        if len(sleeps) == 1:
            assert box[0].state.answer_decision("D-001", "use X")

    box.append(orch_for(root, fake, sleep=answer))
    assert box[0].run() == "app complete"
    assert sleeps == [60.0]
    assert len([m for m in events(box[0], "needs_you") if "decisions need you" in m]) == 1
    assert all(v == "done" for v in box[0].state.status_map().values())


def test_unstick_disabled_still_writes_needs_you_entry(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], {"unstick": {"enabled": False}})
    fake = FakeBackend(behaviours={"P01-T01": ["nothing"]})
    orch = orch_for(root, fake)
    assert orch.run().startswith("stalled: waiting on 1 decisions")
    assert "unstick" not in [c[0] for c in fake.calls]
    assert orch.state.status_map()["P01-T01"] == "blocked"
    assert "D-001 · P01-T01 a · OPEN" in show(root, "main:docs/NEEDS-YOU.md")


def test_red_phase_gate_gets_a_corrective_phase_then_closes(tmp_path):
    check = "python -c \"import os,sys; sys.exit(0 if os.path.exists('src/FIX001-T01.txt') else 1)\""
    root = make_project(tmp_path, phases_basic()[:1], {**NO_AUDIT, "commands": {"phase_verify": [check]}})
    orch = orch_for(root)
    assert orch.run() == "plan complete"
    plan = Plan.load(root / ".agent" / "plan.yaml")
    assert "FIX001" in plan.phase_by_id and plan.task_by_id["FIX001-T01"].verify == [check]
    assert orch.state.phase("P01")["status"] == "done" and orch.state.phase("FIX001")["status"] == "done"
    assert not orch.state.decisions()


def test_phase_gate_that_stays_red_asks_owner_and_others_continue(tmp_path):
    never = "python -c \"import sys; sys.exit(1)\""
    root = make_project(tmp_path, phases_basic(), {**NO_AUDIT, "commands": {"phase_verify": [never]}})
    orch = orch_for(root)
    assert orch.run().startswith("stalled: waiting on")
    d = orch.state.open_decision(kind="phase", phase_id="P01")
    assert d and "P01 checks keep failing" in d["title"]
    assert orch.state.phase("P01")["status"] == "failed"
    assert orch.state.status_map()["P02-T01"] == "done"                     # other phases continue
    orch.state.answer_decision(d["id"], "skip those checks")
    orch2 = orch_for(root)
    orch2.reload_plan()
    orch2.apply_answers()
    assert orch2.state.phase("P01")["status"] == "open"


def test_red_main_at_start_runs_corrective_phase_first(tmp_path):
    root = make_project(tmp_path, phases_basic())
    orch_for(root, max_sessions=1).run()                                     # P01-T01 done: no longer greenfield
    (root / "BROKEN").write_text("breakage introduced outside autopilot")

    class GivesUp(FakeBackend):
        def run(self, req):
            if "repair the main branch" in req.prompt:
                self.calls.append(("fixer", req.model))
                return SessionResult(ok=True, cost=0.1, report={"status": "done", "summary": "could not"})
            if "implement task FIX001-T01" in req.prompt:
                self.calls.append(("FIX001-T01", req.model))
                (Path(req.cwd) / "BROKEN").unlink()
                return SessionResult(ok=True, cost=0.1, report={"status": "done", "summary": "removed BROKEN"})
            return super().run(req)

    fake = GivesUp()
    orch = orch_for(root, fake)
    assert orch.run() == "app complete"
    ids = [c[0] for c in fake.calls]
    assert ids.count("fixer") == 3
    assert ids.index("FIX001-T01") < ids.index("P01-T02") and ids.index("FIX001-T01") < ids.index("P02-T01")
    assert not orch.main_red and all(v == "done" for v in orch.state.status_map().values())
    assert not (root / "BROKEN").exists()
