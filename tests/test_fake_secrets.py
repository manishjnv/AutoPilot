"""W44: a fake secret in a test is built from pieces; the docs redaction names file, line and pattern."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import autopilot
from autopilot.config import Config
from autopilot.docs import redact_secrets
from autopilot.gate import FAKE_SECRET_RULE, task_gate
from autopilot.gitops import Git
from test_gate import put, repo, sh  # noqa: F401  (repo is a fixture)

KEY = "sk-" + "a" * 24  # built from pieces, like the rule says
PROMPTS = Path(autopilot.__file__).parent / "prompts"


@pytest.mark.parametrize("name", ["system.md", "task.md"])
def test_prompts_hold_the_rule(name):
    assert "built from pieces" in (PROMPTS / name).read_text(encoding="utf-8")


def test_plan_writer_names_the_rule():
    assert "secret detection" in (PROMPTS / "plan_writer.md").read_text(encoding="utf-8")


def gate_problems(repo, rel):
    put(repo, rel, f'KEY = "{KEY}"\n')
    sh(repo, "add", "-A")
    cfg = Config.load(repo)
    cfg.data["commands"]["test"] = [f'"{sys.executable}" -c "pass"']
    task = SimpleNamespace(allow_no_changes=False, allow_test_changes=True, files_in_scope=[], verify=[])
    return task_gate(cfg, Git(repo), task).problems


def test_retry_text_for_a_test_file_holds_the_rule(repo):
    assert any("possible" in p and FAKE_SECRET_RULE in p for p in gate_problems(repo, "tests/x.py"))


def test_retry_text_for_a_source_file_does_not(repo):
    probs = gate_problems(repo, "src/x.py")
    assert any(p.startswith("possible") for p in probs)
    assert not any(FAKE_SECRET_RULE in p for p in probs)


def test_redaction_names_line_and_pattern_not_value():
    hits = []
    out = redact_secrets(f"intro\n\nthe key is {KEY} here\n", hits)
    assert hits == [(3, "OpenAI/Anthropic API key")]
    assert KEY not in out
