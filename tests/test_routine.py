"""W10: the Routine prompt names a real `ap run --no-prod`, and every `ap` command in it exists in the parser."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "examples" / "routine" / "prompt.md"
HOWTO = ROOT / "HOWTO.md"
AP_CMD = re.compile(r"(?<![\w.-])ap ([a-z][a-z-]*)")


def ap_commands(text):
    return sorted(set(AP_CMD.findall(text)))


def test_prompt_file_exists():
    assert PROMPT.is_file()


def test_prompt_runs_no_prod():
    assert "ap run --no-prod" in PROMPT.read_text(encoding="utf-8")


def test_prompt_ap_commands_exist_in_parser():
    names = ap_commands(PROMPT.read_text(encoding="utf-8"))
    assert "run" in names and "status" in names
    for name in names:
        # argparse exits 0 for a known subcommand's --help, 2 for an unknown one
        r = subprocess.run([sys.executable, "-m", "autopilot", name, "--help"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"`ap {name}` is not a subcommand: {r.stderr}"


def test_run_help_lists_no_prod():
    r = subprocess.run([sys.executable, "-m", "autopilot", "run", "--help"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    assert "--no-prod" in r.stdout


def test_howto_section_says_not_run_live_with_date():
    text = HOWTO.read_text(encoding="utf-8")
    start = text.index("## Run with the laptop off (Claude Code Routines)")
    section = text[start:text.index("\n## ", start + 1)]
    assert "not been run live" in section and "2026-10-13" in section


def test_howto_section_has_numbered_steps():
    text = HOWTO.read_text(encoding="utf-8")
    start = text.index("## Run with the laptop off (Claude Code Routines)")
    section = text[start:text.index("\n## ", start + 1)]
    steps = re.findall(r"^(\d+)\. ", section, re.M)
    assert steps == [str(i) for i in range(1, len(steps) + 1)] and len(steps) >= 5
    assert "examples/routine/prompt.md" in section
    assert "budget_usd" in section and "scheduling.max_sessions_per_run" in section
