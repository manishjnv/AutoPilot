"""W41: escalate on hard work: tests and scope_always docs do not count as size, a mechanical failure keeps the model."""
import subprocess
from pathlib import Path

from autopilot.backends import SessionResult
from autopilot.context import ContextBuilder
from autopilot.gate import CmdResult, GateResult
from autopilot.orchestrator import Orchestrator, mechanical
from autopilot.plan import Plan
from test_autopilot import make_project
from test_routing import NO_AUDIT, NO_DECIDE, Recorder, models_used

TASK = [{"id": "P01", "title": "One", "tasks": [
    {"id": "P01-T01", "title": "t", "risk": "medium", "files_in_scope": ["src/big.py", "src/P01-T01.txt"]}]}]
GROWTH = {**NO_AUDIT, **NO_DECIDE, "gate": {"file_growth": True}}


def orch_in(tmp_path, cfg=None):
    root = make_project(tmp_path, TASK, {**NO_DECIDE, **(cfg or {})})
    for args in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "base"]):
        subprocess.run(["git", *args], cwd=root, check=True)  # the init files are committed: only the test's work is staged
    return Orchestrator(root, backend=Recorder(), sleep=lambda s: None)


def write(root, files):
    for rel, n in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n" * n)


def test_tests_and_scope_always_docs_do_not_count(tmp_path):
    orch = orch_in(tmp_path)
    write(orch.root, {"a.py": 40, "b.py": 40, "c.py": 40, "tests/test_a.py": 30, "tests/test_b.py": 30,
                      "test_c.py": 30, "REFERENCE.md": 20, "CHANGELOG.md": 20})  # 8 files + 2 docs, 120 code lines
    assert len(orch.git.change_size()[0]) == 8
    assert orch.counted_change() == (["a.py", "b.py", "c.py"], 120)
    assert orch.escalation(SessionResult(ok=True)) == ""


def test_six_code_files_still_escalate(tmp_path):
    orch = orch_in(tmp_path)
    write(orch.root, {f"m{i}.py": 3 for i in range(6)})
    assert orch.escalation(SessionResult(ok=True)) == "large change (6 files, 18 lines)"


def test_mechanical_gate_failure_gives_no_escalation(tmp_path):
    orch = orch_in(tmp_path)
    write(orch.root, {f"m{i}.py": 3 for i in range(6)})
    growth = GateResult(False, problems=["file grew past the budget: a.py 390 -> 401 lines (limit 400). Split, do not grow."])
    assert orch.escalation(SessionResult(ok=True), growth) == ""
    mixed = GateResult(False, problems=growth.problems + ["no change"])
    assert orch.escalation(SessionResult(ok=True), mixed).startswith("large change")
    red_test = GateResult(False, results=[CmdResult("pytest", 1, "boom", 0.1)])
    assert not mechanical(orch.cfg, red_test)


class Grows(Recorder):
    """Attempt 1 grows an in-scope file past 400 lines; attempt 2 does the normal work."""

    def run(self, req):
        if "implement task P01-T01" in req.prompt and not any("implement task P01-T01" in r.prompt for r in self.reqs):
            self.reqs.append(req)
            write(req.cwd, {"src/big.py": 401})
            return SessionResult(ok=True, report={"status": "done", "summary": "grew"})
        return super().run(req)


def test_growth_only_failure_retries_on_the_same_model_and_names_the_problem(tmp_path):
    root = make_project(tmp_path, TASK, GROWTH)
    fake = Grows()
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert models_used(fake) == ["sonnet", "sonnet"]
    retry = [r for r in fake.reqs if "implement task P01-T01" in r.prompt][1].prompt
    assert "Mechanical gate failure" in retry and "file grew past the budget: src/big.py" in retry


def test_prompt_names_the_lines_left_near_the_growth_budget(tmp_path):
    orch = orch_in(tmp_path, {"gate": {"file_growth": True}})
    write(orch.root, {"src/big.py": 384, "src/small.py": 10})
    plan = Plan.load(orch.ad / "plan.yaml")
    prompt = ContextBuilder(orch.cfg, plan, orch.state).task_prompt(plan.all_tasks()[0], 1, None)
    assert "src/big.py: 16 lines left of 400" in prompt and "small.py: " not in prompt.split("Lines left")[-1]
