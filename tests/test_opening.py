"""J15: every document opens in plain words; no technical word in the first three lines."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPENING = ("Autopilot builds your software project while you are away. You write what you want in plain words "
           "and start it once. You get working software, tested, with a record of every step.")
TECH = re.compile(r"\b(Claude|CLI|plan\.yaml|gate|worktree|subscription|token|API|git)\b")
DOCS = ["README.md", "GUIDE.md", "HOWTO.md", "REFERENCE.md", "ARCHITECTURE.md", "SECURITY.md", "CHANGELOG.md",
        "docs/NEEDS-YOU.md"]


def head(name, n=3):
    text = (ROOT / name).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()][:n]


@pytest.mark.parametrize("name", DOCS)
def test_doc_opens_in_plain_words(name):
    if name == "docs/NEEDS-YOU.md" and not (ROOT / name).exists():  # docs/ is local only
        pytest.skip("local file")
    first = head(name)
    assert OPENING in "\n".join(first), name
    hit = TECH.search("\n".join(first))
    assert hit is None, f"{name}: technical word {hit.group()!r} in the first three lines"


def test_descriptions_are_the_opening():
    assert OPENING in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    plugin = json.loads((ROOT / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert plugin["description"] == OPENING


@pytest.mark.parametrize("name,printer", [("install.ps1", "Write-Host"), ("install.sh", "echo")])
def test_install_scripts_print_the_opening_first(name, printer):
    text = (ROOT / name).read_text(encoding="utf-8")
    first = text.index(OPENING)  # the opening is the first line the script prints on a normal run
    assert text[first - 12:first].count(printer[:4]) == 1, name
    assert first < text.index("This script installs"), name


def test_help_and_page_title_open_in_plain_words():
    from autopilot import cli, dash_web
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert OPENING.split(".")[0] in cli.DESCRIPTION
    assert OPENING.split(".")[0] in dash_web.PAGE_TITLE
    assert TECH.search(cli.DESCRIPTION.split(".")[0]) is None


POSITION = ("Python decides when a task is done, not the model. Every step is recorded. Works on Windows. "
            "Runs any coding agent CLI.")


def test_readme_states_the_position_and_the_safety_block():  # W1: position line, Safety block, word cap
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert POSITION in text
    assert len(text.split()) <= 1200, len(text.split())
    body = text.split("## Safety\n", 1)[1].split("\n## ", 1)[0]
    items = [line for line in body.splitlines() if line.startswith("- ")]
    assert len(items) >= 7, items
