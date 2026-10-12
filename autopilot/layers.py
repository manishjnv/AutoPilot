"""O4: import boundaries. `.agent/BRAIN.md` may hold a ```layers block (one `name: path/glob` per line, top to bottom);
a lower layer that imports a higher one is a violation. Only violations that are not in the day-one baseline fail."""
from __future__ import annotations

import ast
import fnmatch
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from .gate import CODE_EXT, TEST_GLOBS, _match

log = logging.getLogger("autopilot")
BLOCK_RX = re.compile(r"```layers[ \t]*\n(.*?)```", re.S)
JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
SKIP = {".git", ".agent", "node_modules", ".venv", "venv", "env", "dist", "build", "__pycache__", "docs"}


def read_layers(root) -> list[tuple[str, str]] | None:
    """The `layers` block of BRAIN.md as [(name, glob)] top to bottom; None when there is none."""
    try:
        text = (Path(root) / ".agent" / "BRAIN.md").read_text(encoding="utf-8")
    except OSError:
        return None
    m = BLOCK_RX.search(text)
    pairs = [(a.strip(), b.strip()) for a, _, b in (l.partition(":") for l in (m.group(1) if m else "").splitlines())]
    return [p for p in pairs if p[0] and p[1]] or None


def code_files(root) -> list[str]:
    """Code files of the repo (no tests, no vendor or build folders), as posix paths."""
    root = Path(root)
    out = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.suffix in CODE_EXT and not SKIP.intersection(rel.parts) and p.is_file() and not _match(rel.as_posix(), TEST_GLOBS):
            out.append(rel.as_posix())
    return sorted(out)


def _layer_of(rel: str, layers) -> int | None:
    for i, (_, glob) in enumerate(layers):
        if fnmatch.fnmatch(rel, glob) or rel.startswith(glob.rstrip("/") + "/"):
            return i
    return None


def _violation(layers, src: str, dst: str, label: str) -> str | None:
    a, b = _layer_of(src, layers), _layer_of(dst, layers)
    if a is not None and b is not None and a > b:  # a lower layer (bigger index) reaches up
        return f"{src} -> {label} (layer {layers[a][0]} imports layer {layers[b][0]})"
    return None


def _targets(root: Path, rel: str, node):
    """Yield (module, repo file) for each repo module an import statement names; other modules are not ours."""
    if isinstance(node, ast.Import):
        groups, anchor = [[a.name] for a in node.names], ""
    elif isinstance(node, ast.ImportFrom):
        parts = Path(rel).parent.parts
        anchor = "/".join(parts[:max(len(parts) - node.level + 1, 0)]) if node.level else ""
        mod = node.module or ""
        groups = [[f"{mod}.{a.name}" if mod else a.name, mod] for a in node.names]
    else:
        return
    for g in groups:
        for dotted in filter(None, g):  # `from a import y`: the module a.y, else the package a
            base = "/".join(filter(None, [anchor, dotted.replace(".", "/")]))  # ponytail: no src/ roots, add when asked
            hit = next((c for c in (base + ".py", base + "/__init__.py") if (root / c).is_file()), None)
            if hit:
                yield dotted, hit
                break


def _py_violations(root: Path, files, layers) -> list[str]:
    out = []
    for rel in files:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            out += [v for mod, dst in _targets(root, rel, node) if (v := _violation(layers, rel, dst, mod))]
    return out


def _js_violations(root: Path, files, layers) -> list[str]:
    exe = shutil.which("depcruise") or shutil.which("dependency-cruiser")
    if not exe:
        log.info("layers: dependency-cruiser is not on PATH, so JS/TS imports are not checked")
        return []
    try:
        res = subprocess.run([exe, "--output-type", "json", *files], cwd=root, capture_output=True, text=True, timeout=120)
        mods = json.loads(res.stdout).get("modules") or []
    except (OSError, subprocess.SubprocessError, ValueError):
        log.warning("layers: dependency-cruiser gave no usable output")
        return []
    return [v for m in mods for d in m.get("dependencies") or []
            if d.get("resolved") and (v := _violation(layers, m["source"], d["resolved"], d["resolved"]))]


def violations(root, files, layers) -> list[str]:
    """Every layer violation in `files` (Python by `ast`, JS/TS by dependency-cruiser when it is installed)."""
    root = Path(root)
    js = [f for f in files if f.endswith(JS_EXT)]
    return _py_violations(root, [f for f in files if f.endswith(".py")], layers) + (
        _js_violations(root, js, layers) if js else [])


def check_imports(root, changed_files, layers, baseline_path) -> list[str]:
    """Problems for the NEW violations in the changed files. A missing baseline is written from the rest of the repo."""
    if not layers:
        return []
    root, baseline_path = Path(root), Path(baseline_path)
    changed = [f for f in changed_files if (root / f).is_file() and not _match(f, TEST_GLOBS)]
    try:
        seen = set(json.loads(baseline_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set(violations(root, [f for f in code_files(root) if f not in changed], layers))  # day one, minus this diff
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(sorted(seen), indent=0) + "\n", encoding="utf-8")
    new = sorted({v for v in violations(root, changed, layers) if v not in seen})
    return [f"import boundary: {v}. Import from the same or a lower layer only." for v in new]


def layers_problems(cfg, git) -> list[str]:
    """Gate hook: the staged files against the BRAIN.md layers; no block = no check."""
    layers = read_layers(cfg.root)
    if not layers:
        return []
    return check_imports(cfg.root, git.staged_files(), layers, cfg.root / ".agent" / "layers_baseline.json")
