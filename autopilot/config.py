"""Project contract loading. Defaults come from the shipped template, so there's one source of truth."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from . import AGENT_DIR

TEMPLATES = Path(__file__).parent / "templates"
RISKS = ["low", "medium", "high", "critical"]


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def defaults() -> dict:
    return load_yaml(TEMPLATES / "agent" / "project.yaml")


class Config:
    """Wraps the merged project.yaml with dotted-path access."""

    def __init__(self, root: Path, data: dict):
        self.root = Path(root).resolve()
        self.data = data

    @classmethod
    def load(cls, root: Path | str) -> "Config":
        root = Path(root).resolve()
        path = root / AGENT_DIR / "project.yaml"
        user = load_yaml(path) if path.exists() else {}
        return cls(root, deep_merge(defaults(), user))

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return default if cur is None else cur

    def commands(self, *groups: str) -> list[str]:
        out: list[str] = []
        for g in groups:
            val = self.get(f"commands.{g}", []) or []
            out.extend([val] if isinstance(val, str) else list(val))
        return [c for c in out if c and str(c).strip()]

    @property
    def agent_dir(self) -> Path:
        return self.root / AGENT_DIR

    @property
    def main_branch(self) -> str:
        return self.get("main_branch", "main")

    def validate(self) -> list[str]:
        errs = []
        ladder = self.get("models.ladder", {})
        for r in RISKS:
            if not ladder.get(r):
                errs.append(f"models.ladder.{r} is empty")
        backend = self.get("agent.backend")
        if backend not in ("claude_cli", "command"):
            errs.append(f"agent.backend must be claude_cli or command, got {backend!r}")
        if backend == "command" and not self.get("agent.command"):
            errs.append("agent.command is required when agent.backend=command")
        for env in ("staging", "prod"):
            if self.get(f"deploy.{env}.enabled") and not self.get(f"deploy.{env}.cmd"):
                errs.append(f"deploy.{env}.enabled but deploy.{env}.cmd is empty")
        if self.get("deploy.prod.max_auto_risk") not in RISKS:
            errs.append("deploy.prod.max_auto_risk must be one of " + ", ".join(RISKS))
        if not self.commands("build", "lint", "typecheck", "test"):
            errs.append("no verify commands (build/lint/typecheck/test) — the gate would pass anything")
        return errs + self._git_errors()

    def _git_errors(self) -> list[str]:
        mode = self.get("git.mode", "direct")
        if mode not in ("direct", "pr"):
            return [f"git.mode must be direct or pr, got {mode!r}"]
        if mode == "pr" and not self.get("git.push"):  # else local bookkeeping commits make main diverge from GitHub
            return ["git.mode: pr needs git.push: true (Autopilot's own plan and docs commits go straight to main)"]
        return []

    def blocking_errors(self) -> list[str]:
        """The subset of validate() that must stop a run."""
        errs = [f"deploy.{e}.enabled but deploy.{e}.cmd is empty" for e in ("staging", "prod")
                if self.get(f"deploy.{e}.enabled") and not self.get(f"deploy.{e}.cmd")]
        if not self.get("gate.allow_no_checks") and not self.commands("build", "lint", "typecheck", "test"):
            errs.append("no verify commands (build/lint/typecheck/test) — the gate would pass anything")
        return errs + self._git_errors()
