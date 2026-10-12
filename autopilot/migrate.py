"""Q20.4: the `.agent/` folder of a project written by an older Autopilot is brought up to date by `ap upgrade`.
Before anything changes, the files are copied to `.agent/backup-<version>/` (the version that wrote them; `legacy` when the
folder has no `.agent/schema` marker). Every step is small, text-only and repeatable; a step that fails is skipped with one
line and the project is left as it was. An older project never fails on a new version: nothing here raises."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import AGENT_DIR, __version__

MARKER = "schema"                      # `.agent/schema`: the version of the Autopilot that last migrated this folder
GITIGNORE_LINE = ".agent/backup-*/"
KEEP_OUT = ("state.db", "state.db-*", "logs", "run.lock", "STOP", "run.json", "approvals", "worktrees", "backup-*")


def written_by(root: Path) -> str:
    try:
        return (Path(root) / AGENT_DIR / MARKER).read_text(encoding="utf-8").strip() or "legacy"
    except OSError:
        return "legacy"


def _step_baseline(root: Path) -> str:
    """O2: file sizes on day one, so only new growth fails the gate. A project from before O2 has none."""
    if (root / AGENT_DIR / "quality_baseline.json").exists():
        return ""
    from .gate import write_baseline
    return f"added {AGENT_DIR}/quality_baseline.json ({write_baseline(root)} files, the sizes of today)"


def _step_gitignore(root: Path) -> str:
    """The backup folders are copies, not work: they stay out of git."""
    gi = root / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if GITIGNORE_LINE in text:
        return ""
    gi.write_text(text + ("" if not text or text.endswith("\n") else "\n") + GITIGNORE_LINE + "\n", encoding="utf-8")
    return f"added {GITIGNORE_LINE} to .gitignore"


STEPS = (("quality baseline", _step_baseline), ("gitignore", _step_gitignore))


def pending(root: Path) -> bool:
    return written_by(root) != __version__ or any(
        (not (root / AGENT_DIR / "quality_baseline.json").exists(),
         GITIGNORE_LINE not in ((root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").exists() else "")))


def backup(root: Path, old: str) -> Path | None:
    """Copy the small files of `.agent/` to `.agent/backup-<old>/`. An existing backup of that version is kept, never
    overwritten (the first copy is the one that holds the old shape)."""
    ad = Path(root) / AGENT_DIR
    dst = ad / f"backup-{old}"
    if dst.exists():
        return dst
    try:
        shutil.copytree(ad, dst, ignore=shutil.ignore_patterns(*KEEP_OUT))
    except OSError:
        return None
    return dst


def migrate(root: Path, *, check: bool = False) -> list[str]:
    """The lines of what changed (or, with `check`, what would change). [] when the folder is current. Never raises."""
    root = Path(root)
    if not (root / AGENT_DIR / "project.yaml").exists() or not pending(root):
        return []
    old = written_by(root)
    if check:
        return [f"{root.name}: {AGENT_DIR}/ was written by {old}; `ap upgrade` brings it up to date (backup first)"]
    out: list[str] = []
    try:
        bk = backup(root, old)
        if bk is None:
            return [f"{root.name}: could not copy {AGENT_DIR}/ to a backup, so nothing was changed"]
        for name, step in STEPS:
            try:
                line = step(root)
            except Exception as exc:  # noqa: BLE001 - an old project never fails on a new version
                out.append(f"{root.name}: skipped {name} ({type(exc).__name__}); the backup is in {bk.name}")
                continue
            if line:
                out.append(f"{root.name}: {line}")
        (root / AGENT_DIR / MARKER).write_text(__version__ + "\n", encoding="utf-8")
        head = f"{root.name}: {AGENT_DIR}/ moved from {old} to {__version__}; backup in {AGENT_DIR}/{bk.name}/"
        return [head, *out] if out else [head + "; nothing else had to change"]
    except Exception as exc:  # noqa: BLE001
        return [f"{root.name}: the migration stopped ({type(exc).__name__}); {AGENT_DIR}/ is as it was"]


def projects(cwd: Path | None = None) -> list[Path]:
    """The project of this folder and the recent ones, once each."""
    from .cli import recent_projects
    found = list(recent_projects())
    here = Path(cwd or Path.cwd()).resolve()
    if (here / AGENT_DIR / "project.yaml").exists() and here not in found:
        found.insert(0, here)
    return found


def migrate_all(*, check: bool = False, cwd: Path | None = None) -> list[str]:
    out: list[str] = []
    try:
        for p in projects(cwd):
            out += migrate(p, check=check)
    except Exception:  # noqa: BLE001
        return out
    return out
