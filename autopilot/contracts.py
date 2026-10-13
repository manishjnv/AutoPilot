"""W36: feature contracts. A committed page in `features/` names the rules of a matured feature, the files that hold
it and the tests that guard it; a task whose files_in_scope touches one of those files gets the page in its prompt."""
from __future__ import annotations
import fnmatch
import re
from collections import Counter
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


# ---- W36b: the gate guards the tests a committed contract names
_DATED = re.compile(r"^- \d{4}-\d{2}-\d{2}: .*$", re.M)
_FENCE = re.compile(r"^\s*(```|~~~)")
_TOP = re.compile(r"^(#{1,2})\s+(.+?)\s*#*\s*$")


def _cid(x) -> str:
    x = _norm(x)
    x = x[len(FOLDER) + 1:] if x.startswith(FOLDER + "/") else x
    return x[:-3] if x.endswith(".md") else x


def _exempt(report) -> set[str]:
    """Contract ids the report marks `changed` with a non-empty `why`."""
    items = report.get("contracts") if isinstance(report, dict) else None
    return {_cid(e.get("id", "")) for e in items or [] if isinstance(e, dict) and e.get("status") == "changed"
            and str(e.get("why") or "").strip()}


def contract_problems(cfg, git, report=None) -> list[str]:
    """Problems of the staged diff against the contracts committed at HEAD (never the working tree, so a diff cannot
    loosen its own contract): a named test removed, a fewer-tests count in a named file or a deleted page, unless the
    report marks that contract `changed` with a `why`; an edited page without a new dated line under `## Changes`."""
    from .gate import TEST_DEF_RX  # gate imports this module
    pages = [p for p in git.run("ls-tree", "--name-only", "HEAD", f"{FOLDER}/", check=False).splitlines()
             if p.endswith(".md")]
    if not pages:
        return []
    status = {}  # --no-renames: a rename is D old + A new, so the old path is still checked
    for line in git.run("-c", "core.quotepath=false", "diff", "--cached", "--name-status", "--no-renames",
                        check=False).splitlines():
        st, _, path = line.partition("\t")
        if path:
            status[path] = st[:1]
    exempt, out = _exempt(report), []

    def blob(rev, path):  # rev "" = the staged blob; a deleted path gives ""
        return git.run("cat-file", "blob", f"{rev}:{path}", check=False)

    for page in pages:
        cid, head = _cid(page), blob("HEAD", page)
        guarded = [f"contract {cid}: page deleted"] if status.get(page) == "D" else []
        if status.get(page) == "M":
            new = set(_DATED.findall(sections(blob("", page)).get("Changes", "")))
            if not new - set(_DATED.findall(sections(head).get("Changes", ""))):
                out.append(f"contract {cid}: page changed without a new dated line under ## Changes")
        counted = set()
        for node in named(head, "Tests that guard it"):
            path, _, name = node.partition("::")
            path = _norm(path)
            if path not in status:
                continue
            before, after = blob("HEAD", path), blob("", path)
            rx = re.compile(rf"^\s*(?:async\s+)?def {re.escape(name)}\b", re.M) if name else None
            if rx and rx.search(before) and not rx.search(after):
                guarded.append(f"contract {cid}: test {name} removed")
            if path not in counted:
                counted.add(path)
                a, b = len(TEST_DEF_RX.findall(before)), len(TEST_DEF_RX.findall(after))
                if b < a:
                    guarded.append(f"contract {cid}: test count dropped in {path}: {a} -> {b}")
        if cid not in exempt:
            out += guarded
    return out


def _top_headings(text: str) -> list[tuple[str, str]]:
    """(key, line) of each `#` and `##` heading outside code fences; key = level + casefolded text."""
    out, fence = [], None
    for line in text.splitlines():
        if (m := _FENCE.match(line)):
            fence = m.group(1) if fence is None else (None if m.group(1) == fence else fence)
        elif fence is None and (h := _TOP.match(line)):
            out.append((h.group(1) + " " + " ".join(h.group(2).split()).casefold(), line.strip()))
    return out


def added_duplicates(before: str, after: str) -> list[str]:
    """Each top-level heading that `after` has twice or more and more often than `before` (a second `## Safety`).
    Repeated `###` sub-headings and duplicates already in `before` never count."""
    old = Counter(k for k, _ in _top_headings(before))
    new = Counter(k for k, _ in _top_headings(after))
    seen, out = set(), []
    for key, line in _top_headings(after):
        if key not in seen and new[key] >= 2 and new[key] > old[key]:
            seen.add(key)
            out.append(line)
    return out
