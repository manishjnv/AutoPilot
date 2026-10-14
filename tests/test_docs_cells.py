"""W57: a table cell in a public page has 40 words or fewer; the detail goes in a block under the table."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["README.md", "FEATURES.md", "GUIDE.md", "HOWTO.md", "REFERENCE.md", "ARCHITECTURE.md", "SECURITY.md",
         "COMPARE.md"]
MAX_CELL = 40


def words(cell):
    """A code span counts as one word; a link counts by its text."""
    cell = re.sub(r"`[^`]*`", "CODE", cell)
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    return len(cell.split())


def cells(text):
    fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        if fence or not line.startswith("|"):
            continue
        body = line.strip().strip("|").replace(chr(92) + "|", "\0")  # an escaped pipe stays in the cell
        for cell in body.split("|"):
            if not re.fullmatch(r"\s*:?-{3,}:?\s*", cell):
                yield n, cell.replace("\0", "|").strip()


def long_cells(text):
    return [(n, words(c)) for n, c in cells(text) if words(c) > MAX_CELL]


@pytest.mark.parametrize("name", PAGES)
def test_no_table_cell_over_40_words(name):
    path = ROOT / name
    if not path.exists():
        pytest.skip("page not present")
    bad = long_cells(path.read_text(encoding="utf-8"))
    assert not bad, f"{name}: cells over {MAX_CELL} words (line, words): {bad[:10]}"


def test_a_41_word_cell_fails():
    row = "| a | " + " ".join(["word"] * 41) + " |"
    assert long_cells(row) and not long_cells("| a | " + " ".join(["word"] * 40) + " |")
