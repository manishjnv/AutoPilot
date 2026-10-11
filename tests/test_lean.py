"""O10: the lean profile: fewer sessions per task, changed-module tests, a token report that sums to the state total."""
import yaml

from autopilot.config import Config
from autopilot.context import ContextBuilder
from autopilot.gate import changed_tests, verify_commands
from autopilot.orchestrator import Orchestrator
from autopilot.plan import Plan
from autopilot.report import tokens_by_step, tokens_report
from autopilot.state import State
from test_autopilot import FakeBackend, make_project

PLAN = [{"id": "P01", "title": "One", "tasks": [
    {"id": "P01-T01", "title": "a", "risk": "low"}, {"id": "P01-T02", "title": "b", "risk": "low"}]}]


def run(tmp_path, profile, behaviours):
    fake = FakeBackend(behaviours=behaviours)
    root = make_project(tmp_path, PLAN, {"profile": profile, "decide": {"enabled": False}})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.run()
    return fake, orch


def count(fake, kind):
    return sum(1 for c in fake.calls if c[0] == kind)


def test_lean_one_build_per_task_no_audit(tmp_path):
    fake, orch = run(tmp_path, "lean", {})
    assert count(fake, "P01-T01") == 1 and count(fake, "P01-T02") == 1
    assert count(fake, "audit") == 0
    assert "one smoke test per acceptance criterion" in fake.prompts[0][1]


def test_lean_one_retry_then_parked_without_a_third_session(tmp_path):
    fake, orch = run(tmp_path, "lean", {"P01-T01": ["break", "break", "ok"]})
    assert count(fake, "P01-T01") == 2 and count(fake, "unstick") == 0
    assert orch.state.task("P01-T01")["status"] == "blocked"


def test_full_keeps_the_old_counts(tmp_path):
    fake, orch = run(tmp_path, "full", {"P01-T01": ["break", "break", "ok"]})
    assert count(fake, "P01-T01") == 3 and count(fake, "unstick") == 1
    assert count(fake, "audit") == 1
    assert "Add or extend automated tests" in fake.prompts[0][1]


def test_template_leaves_the_retry_count_to_the_profile(tmp_path):  # session 27: the template said 3 and beat lean
    root = make_project(tmp_path, PLAN, {"profile": "lean"})
    assert Config.load(root).get("retries.max_attempts_per_task") == 2
    assert "max_attempts_per_task" not in (yaml.safe_load((root / ".agent/project.yaml").read_text()).get("retries") or {})


def test_project_retry_setting_wins_under_lean(tmp_path):
    root = make_project(tmp_path, PLAN, {"profile": "lean", "retries": {"max_attempts_per_task": 4}})
    assert Config.load(root).get("retries.max_attempts_per_task") == 4


def test_lean_prompt_caps_and_no_variations(tmp_path):
    root = make_project(tmp_path, PLAN, {"profile": "lean"})
    plan = Plan.load(root / ".agent" / "plan.yaml")
    ctx = ContextBuilder(Config.load(root), plan, None)
    (root / ".agent" / "BRAIN.md").write_text("b" * 9000)
    assert len(ctx.brain()) < 6100 
    feats = [{"id": "F1", "title": "t", "journey": "j"}]
    assert "Do not try variations" in ctx.verify_prompt(plan.phases[0], feats)


def test_changed_module_test_selection(tmp_path):
    root = make_project(tmp_path, PLAN, {"profile": "lean", "commands": {"test": ["python -m pytest -q"]}})
    (root / "tests").mkdir()
    (root / "tests" / "test_foo.py").write_text("")
    cfg = Config.load(root)
    assert changed_tests(cfg, "python -m pytest -q", ["autopilot/foo.py"]) == "python -m pytest -q tests/test_foo.py"
    assert changed_tests(cfg, "pytest", ["tests/test_x.py", "autopilot/nomap.py"]) == "pytest tests/test_x.py"
    assert changed_tests(cfg, "pytest", ["README.md"]) == "pytest"
    assert changed_tests(cfg, "npx vitest run", ["src/a.ts"]) == "npx vitest related src/a.ts --run"
    assert changed_tests(cfg, "go test ./...", ["pkg/a.go"]) == "go test ./pkg/..."
    assert verify_commands(cfg, files=["autopilot/foo.py"])[-1].endswith("tests/test_foo.py")
    assert verify_commands(cfg, files=["autopilot/foo.py"], phase=True)[-1] == "python -m pytest -q"
    assert verify_commands(cfg)[-1] == "python -m pytest -q"


def test_token_report_sums_to_the_state_total(tmp_path):
    root = make_project(tmp_path, PLAN, {})
    st = State(root / ".agent" / "state.db")
    for kind, attempt, n in (("task", 1, 100), ("task", 2, 40), ("review", 1, 30), ("audit", 1, 20)):
        sid = st.start_session(kind, "P01-T01", "P01", attempt, "sonnet")
        st.end_session(sid, cost=0.5, ok=True, usage={"sonnet": {"input": n, "output": n, "cache_read": 1, "cache_write": 2}})
    rows = dict((k, t) for k, t, _ in tokens_by_step(st))
    assert set(rows) == {"build", "retry", "review", "audit"}
    total = st.db.execute("SELECT SUM(tokens_in + tokens_out + tokens_cache_read + tokens_cache_write) FROM sessions").fetchone()[0]
    assert sum(rows.values()) == total == 100 * 2 + 40 * 2 + 30 * 2 + 20 * 2 + 12
    assert "| retry |" in tokens_report(st)
