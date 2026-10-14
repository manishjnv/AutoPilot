"""W27: the text of the files a task names in files_in_scope, for the task prompt."""
from __future__ import annotations

import re
from pathlib import Path

HEAD_LINES = 80
HEADING = "## Files in scope (current content)"
DEF_RX = re.compile(r"^\s*(?:async\s+def|def|class)\s+\w+")
GLOB_CHARS = "*?["


def _outline(lines: list[str]) -> str:
    return "\n".join(f"{i}: {l.strip()}" for i, l in enumerate(lines, 1) if DEF_RX.match(l))


def _piece(rel: str, text: str, room: int) -> str:
    """One file: in full when it fits in `room`, else its first lines and its def/class lines with line numbers."""
    fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", text)), default=0))
    full = f"### {rel}\n{fence}\n{text.rstrip()}\n{fence}"
    if len(full) <= room:
        return full
    lines = text.splitlines()
    head = "\n".join(lines[:HEAD_LINES])
    out = (f"### {rel} (too large: first {min(HEAD_LINES, len(lines))} of {len(lines)} lines, then the def/class lines)\n"
           f"{fence}\n{head}\n{fence}\n")
    outline = _outline(lines)
    out += f"Definitions:\n{outline or '(none)'}"
    return out if len(out) <= room else out[:max(room, 0)]


def scoped_files_block(root: Path, files, cap: int, skip=()) -> str:
    """The `## Files in scope (current content)` block: each exactly named file, in list order, at most `cap` chars.
    Globs are not expanded; a missing file is `(new file)`; paths in `skip` (the docs of gate.scope_always) are left out."""
    root = Path(root).resolve()
    parts, used = [], len(HEADING) + 2
    for rel in files or []:
        rel = str(rel).strip()
        if not rel or any(c in rel for c in GLOB_CHARS) or rel in skip:
            continue
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            piece = f"### {rel}\n(new file)"
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            piece = _piece(rel, text, cap - used - 2)
        if used + len(piece) + 2 > cap:
            break
        parts.append(piece)
        used += len(piece) + 2
    return HEADING + "\n\n" + "\n\n".join(parts) if parts else ""
