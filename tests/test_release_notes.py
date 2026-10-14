import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bump  # noqa: E402

GOOD = "# C\n\n## [Unreleased]\n\n**In plain words:** you get a fix.\n\n- You can stop a run at once.\n\n## [0.1.0] - 2026-01-01\n"


def test_missing_lead_fails_and_names_the_rule(capsys):
    try:
        bump.check_notes(GOOD.replace("**In plain words:** you get a fix.\n\n", ""))
        raise AssertionError("no exit")
    except SystemExit as e:
        assert "release notes rule" in str(e) and "In plain words" in str(e)


def test_lead_and_short_bullets_pass():
    bump.check_notes(GOOD)


def test_long_bullet_fails_and_is_named():
    long = "- " + " ".join(["word"] * 30) + ".\n"
    assert len(bump.long_sentences(long)) == 1
    try:
        bump.check_notes(GOOD.replace("- You can stop a run at once.\n", long))
        raise AssertionError("no exit")
    except SystemExit as e:
        assert "over 25 words" in str(e)


def test_only_the_unreleased_block_is_checked():
    old = GOOD + "- " + " ".join(["w"] * 40) + ".\n"
    bump.check_notes(old)


def test_rule_is_in_prompt_workflow_and_vale():
    assert "at most 25 words" in (ROOT / "autopilot/prompts/task.md").read_text(encoding="utf-8")
    assert "CHANGELOG.md" in (ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    vale = (ROOT / ".vale.ini").read_text(encoding="utf-8")
    assert "[CHANGELOG.md]" in vale and "Autopilot.SentenceLength = error" in vale
