"""O6: a short helper index (module -> public names) so a session reuses code instead of re-reading or duplicating it."""
from __future__ import annotations

import ast
import os
import re
from collections import Counter
from pathlib import Path

CAP = 3000
_SKIP = {".git", ".agent", "docs", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
         "tests", "test", "__tests__", "fixtures", "fixture"}
_JS = {".js", ".jsx", ".ts", ".tsx", ".mjs"}
_JS_EXPORT = re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|class|const|let|var)\s+([A-Za-z]\w*)", re.M)
_JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s+)['"]([^'"]+)['"]""")


def _files(root: Path):
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in _SKIP]
        for n in names:
            p = Path(d, n)
            if p.suffix == ".py" and not n.startswith("test_") and not n.endswith("_test.py") and n != "conftest.py":
                yield p
            elif p.suffix in _JS and ".test." not in n and ".spec." not in n:
                yield p


def _parse(p: Path):
    """-> (public names, imported module stems)"""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], []
    if p.suffix != ".py":
        return (list(dict.fromkeys(_JS_EXPORT.findall(text))),
                [Path(m).stem for m in _JS_IMPORT.findall(text) if m.startswith(".")])
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], []
    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
             and not n.name.startswith("_")]
    imps = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imps += [a.name.split(".")[-1] for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            # `from pkg import mod` imports mod; `from .mod import x` imports mod
            imps += [a.name for a in n.names] if not n.module else [n.module.split(".")[-1]]
    return names, imps


def helper_index(root, cap: int = CAP) -> str:
    """One line per module, most-imported first, cut at `cap` chars. Empty string when nothing is public."""
    root = Path(root)
    mods, uses = [], Counter()
    for p in _files(root):
        names, imps = _parse(p)
        uses.update(imps)
        if names:
            mods.append((p.relative_to(root).as_posix(), p.stem, names))
    mods.sort(key=lambda m: (-uses[m[1]], m[0]))
    out, size = [], 0
    for rel, _, names in mods:
        line = f"{rel}: {', '.join(names)}"
        if size + len(line) + 1 > cap:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)
