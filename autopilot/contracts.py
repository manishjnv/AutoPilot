"""W36: feature contracts. A committed page in `features/` names the rules of a matured feature, the files that hold
it and the tests that guard it; a task whose files_in_scope touches one of those files gets the page in its prompt."""
from __future__ import annotations
import fnmatch
import re
from pathlib import Path

FOLDER = "features"
SECTIONS = ("What it does", "Rules", "Files", "Tests that guard it", "Changes")
HEADING = "## Feature contracts (keep them, or say why in the report)"
CAP = 8000
_CODE = re.compile(r"`([^`]+)`")


def sections(text: str) -> dict[str, str]:
    """The body of each `## ` section of a page, keyed by its heading text."""
    out: dict[str, str] = {}
    name = None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = ""
        elif name is not None:
            out[name] += line + "\n"
    return out


def named(text: str, section: str) -> list[str]:
    """The first `code` item of each bullet line of one section (a file path or a test node id)."""
    return [m.group(1) for line in sections(text).get(section, "").splitlines()
            if line.lstrip().startswith("- ") and (m := _CODE.search(line))]


def _norm(p: str) -> str:
    p = str(p).replace("\\", "/").strip()
    return p[2:] if p.startswith("./") else p


def _touches(page_files: list[str], files) -> bool:
    scope = [_norm(f) for f in files or []]
    return any(f == p or fnmatch.fnmatch(p, f) for p in map(_norm, page_files) for f in scope)


def contracts_for(root, files) -> list[str]:
    """The text of each page in <root>/features/ whose `## Files` list matches any of `files` (a scope entry may be a
    glob), in file name order. Pure: reads only."""
    folder = Path(root) / FOLDER
    if not folder.is_dir():
        return []
    pages = []
    for page in sorted(folder.glob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        if _touches(named(text, "Files"), files):
            pages.append(text.strip())
    return pages


def contracts_block(root, files, cap: int = CAP) -> str:
    """The prompt block of the matching contracts, capped at `cap` characters; '' when no page matches."""
    pages = contracts_for(root, files)
    if not pages:
        return ""
    body = "\n\n".join(pages)
    if len(body) > cap:
        body = body[:cap].rstrip() + "\n...(cut: read the rest in features/)"
    return f"{HEADING}\n\n{body}"
