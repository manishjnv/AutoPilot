"""W30: audit, verify and docs sessions get the last gate output (no second test run) and stop at audit.timeout_sec."""
from autopilot.backends.claude_cli import partial_text
from autopilot.backends import SessionResult
from autopilot.gate import GateResult
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project
from test_reliability import ONE_TASK

SENTENCE = "The last gate output is below. Do not run the test suite."
FEATURES = [{"id": "P01", "title": "One", "features": [{"id": "P01-F01", "title": "Check", "journey": "run it"}],
             "tasks": [{"id": "P01-T01", "title": "a", "risk": "low"}]}]


class R:  # a CmdResult stand-in
    def __init__(self, output):
        self.cmd, self.rc, self.output = "pytest", 0, output


def orch(tmp_path, extra=None, phases=ONE_TASK, fake=None):
    root = make_project(tmp_path, phases, extra)
    o = Orchestrator(root, backend=fake or FakeBackend(), sleep=lambda s: None)
    o.reload_plan()
    return o


def prompts(o):
    ph = o.plan.phases[0]
    return [o.ctx.auditor_prompt("completion", 5, o.gate_output()),
            o.ctx.verify_prompt(ph, FEATURES[0]["features"], o.gate_output()),
            o.ctx.docs_prompt(ph, o.state, o.gate_output())]


def test_prompts_hold_the_gate_output_after_a_gate(tmp_path):
    o = orch(tmp_path)
    o.last_main_gate = GateResult(ok=True, results=[R("collected\n" + "x" * 9000 + "\n12 passed in 3s\n")])
    for p in prompts(o):
        assert SENTENCE in p and "12 passed in 3s" in p and "{{gate_output}}" not in p
    assert len(o.gate_output()) <= 6000


def test_prompts_say_no_gate_before_any_gate(tmp_path):
    o = orch(tmp_path)
    for p in prompts(o):
        assert SENTENCE in p and "(no gate run yet)" in p


def test_phase_close_sets_the_gate(tmp_path):
    o = orch(tmp_path, {"audit": {"completion_audit": False}})
    assert o.last_main_gate is None and o.run() == "plan complete"
    assert o.last_main_gate is not None and "$ " in o.gate_output()


class TimingOut(FakeBackend):
    def run(self, req):
        if "implementation audit" in req.prompt:
            self.timeout = req.timeout_sec
            return SessionResult(ok=False, error="timed out", timed_out=True, text="found a gap in x" + "!" * 3000)
        return super().run(req)


def test_timed_out_audit_keeps_partial_report(tmp_path):
    fake = TimingOut()
    o = orch(tmp_path, fake=fake)
    assert o.run().startswith("plan complete")
    assert fake.timeout == 1200
    assert any(e["message"] == "audit: partial after 1200 s" for e in o.state.events(100))
    d = o.state.open_decision(task_id=None, kind="audit", phase_id=None)
    assert "stopped after 1200 s; its notes so far: found a gap in x" in d["question"]
    assert len(d["question"]) < 2200


def test_partial_text_reads_assistant_text():
    raw = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"},{"type":"tool_use"}]}}\nnot json\n'
    assert partial_text(raw) == "hi"
