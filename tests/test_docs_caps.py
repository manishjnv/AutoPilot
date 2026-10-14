"""W57: each public page stays under its word cap, and every ## section of REFERENCE.md says who needs it."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# README.md has its own cap (1200) in test_opening.py. REFERENCE.md has no cap; it has the reader line instead.
CAPS = {"FEATURES.md": 4000, "HOWTO.md": 7000, "ARCHITECTURE.md": 3500, "SECURITY.md": 1200, "GUIDE.md": 1000,
        "COMPARE.md": 1500}


@pytest.mark.parametrize("name,cap", sorted(CAPS.items()))
def test_page_stays_under_its_word_cap(name, cap):
    n = len((ROOT / name).read_text(encoding="utf-8").split())
    assert n <= cap, f"{name}: {n} words, cap {cap}; move detail to a sub-page or cut it"


def test_every_reference_section_starts_with_who_needs_it():
    lines = (ROOT / "REFERENCE.md").read_text(encoding="utf-8").splitlines()
    missing = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            after = [ln for ln in lines[i + 1 : i + 4] if ln.strip()]
            if not after or not after[0].startswith("**Who needs this:**"):
                missing.append(line)
    assert not missing, f"REFERENCE.md sections without a 'Who needs this' line: {missing}"


def test_reference_sections_are_found():
    text = (ROOT / "REFERENCE.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^## ", text, re.M)) >= 10
