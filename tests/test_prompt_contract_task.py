from pathlib import Path

P = Path(__file__).resolve().parent.parent / "autopilot" / "prompts"


def test_contract_task_rule_in_planner_prompts():
    for name in ("onboard.md", "plan_writer.md", "replanner.md"):
        assert "ontract task" in (P / name).read_text(encoding="utf-8"), name
