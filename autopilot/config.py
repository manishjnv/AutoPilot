"""Project contract loading. Defaults come from the shipped template, so there's one source of truth."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError

from . import AGENT_DIR

TEMPLATES = Path(__file__).parent / "templates"
RISKS = ["low", "medium", "high", "critical"]
REVIEW_SCOPES = ("critical", "all")  # W4: review.scope values
SANDBOX_MODES = ("off", "allowlist", "docker")  # W11: sandbox.mode values
SCOPE_ALWAYS = ["REFERENCE.md", "CHANGELOG.md", "HOWTO.md", "README.md"]  # W19: docs the scope check always allows
TEST_MODES = ("changed", "full")  # W22: gate.tests values
NATIVE_WINDOWS = os.name == "nt"
# CLI flags that could replace or widen the sandbox settings Autopilot passes (P5 egress allowlist)
SANDBOX_UNSAFE_ARGS = ("--settings", "--setting-sources", "--mcp-config", "--dangerously-skip-permissions",
                       "--allowedTools", "--allowed-tools")


def sandbox_mode(cfg) -> str:
    """W11: the one mode rule. An explicit sandbox.mode wins; a missing key follows sandbox.enabled."""
    mode = cfg.get("sandbox.mode")
    if mode is None or mode == "":
        return "allowlist" if cfg.get("sandbox.enabled") else "off"
    return str(mode)


def allowlist_on(cfg) -> bool:
    """W11: true when Claude Code's egress allowlist applies (docker plus sandbox.enabled = both)."""
    return bool(cfg.get("sandbox.enabled")) or sandbox_mode(cfg) == "allowlist"


def scope_always(cfg) -> list[str]:
    """W19: files any task may change. A missing key gives the default list."""
    value = cfg.get("gate.scope_always")
    return list(SCOPE_ALWAYS) if value is None else list(value)


def tests_mode(cfg) -> str:
    """W22: the one tests rule. A missing key means changed (the changed modules' tests per task)."""
    mode = cfg.get("gate.tests")
    return "changed" if mode is None or mode == "" else str(mode)


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _dupes(node, where: str = "the top level") -> None:
    """W38: YAML keeps the last of two equal keys; a project file must not, so a repeat in one mapping is an error."""
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _dupes(item, where)
    if not isinstance(node, yaml.MappingNode):
        return
    seen: dict = {}
    for key, value in node.value:
        if isinstance(key, yaml.ScalarNode) and key.tag != "tag:yaml.org,2002:merge":
            line = key.start_mark.line + 1
            if (key.tag, key.value) in seen:
                raise ConstructorError(None, None, f"duplicate key '{key.value}' in {where}: "
                                                   f"lines {seen[key.tag, key.value]} and {line}")
            seen[key.tag, key.value] = line
            _dupes(value, f"{key.value}" if where == "the top level" else f"{where}.{key.value}")


class _NoDupes(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):  # W47: the libyaml loader parses 10x faster; same nodes, same errors
    def construct_document(self, node):
        _dupes(node)
        return super().construct_document(node)


def load_yaml(path: Path) -> dict:
    """Read a YAML file; a duplicate key raises yaml's ConstructorError (a yaml.YAMLError) naming the key and lines."""
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_NoDupes) or {}  # noqa: S506 — _NoDupes is a SafeLoader


def defaults() -> dict:
    d = load_yaml(TEMPLATES / "agent" / "project.yaml")
    d.setdefault("agent", {}).setdefault("backend", "claude_cli")  # N3: the template leaves it unset (preflight detects)
    d["profile"] = "full"  # O10: an old project.yaml without the key stays full; the template gives new projects lean
    # (clean measure 2026-10-12: -39.5 percent tokens per task, 11 of 11 done; the owner accepted it as the 40 percent rule)
    d.setdefault("gate", {})["new_file_reasons"] = False  # N7: on in the template (new projects) only; a missing key = off
    d["gate"]["file_growth"] = False  # O2: same rule: the template turns it on, an old project.yaml keeps it off
    d.setdefault("usage", {})["switch"] = "suggest"  # auto in the template (new projects) only; a missing key = suggest
    d.setdefault("review", {})["scope"] = "critical"  # W4: the template turns it on for new projects; a missing key = critical
    return d


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
        cfg = cls(root, deep_merge(defaults(), user))
        if cfg.lean and "max_attempts_per_task" not in (user.get("retries") or {}):
            cfg.data["retries"]["max_attempts_per_task"] = 2  # O10: one retry under lean, unless the project sets it
        return cfg

    @property
    def lean(self) -> bool:
        return self.get("profile", "full") == "lean"

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

    def parallel_size(self) -> int:
        """N12: `scheduling.parallel`; unset = 3 with a test command in direct git mode, else 1."""
        v = self.get("scheduling.parallel")
        if v is None:
            return 3 if self.commands("test") and self.get("git.mode", "direct") == "direct" else 1
        return max(1, int(v or 1))

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
        for key in ("models.review", "review.effort"):  # W61 rule 5: one name, or a map by risk tier
            v = self.get(key)
            if isinstance(v, dict) and not set(v) <= set(RISKS):
                errs.append(f"{key} map keys must be risk tiers ({', '.join(RISKS)}), got {sorted(v)}")
        for role, v in (self.get("models") or {}).items():  # W61 rule 3: a free CLI preset only for the side roles
            if isinstance(v, str) and ":" in v and role not in ("docs", "research", "triage", "unstick", "helper"):
                errs.append(f"models.{role}: a CLI preset (`{v}`) is allowed only for docs, research, triage, unstick and helper")
        backend = self.get("agent.backend")
        if backend not in ("claude_cli", "command", "openai_compat"):
            errs.append(f"agent.backend must be claude_cli, command or openai_compat, got {backend!r}")
        base = self.get("agent.base_url")  # P12-T01 (W13)
        if backend == "openai_compat" and base and not str(base).startswith(("http://", "https://")):
            errs.append("agent.base_url must start with http:// or https://")
        if backend == "command":
            from .backends.command import PRESETS, SAFE_MODEL
            preset = self.get("agent.preset")
            names = [str(v) for v in (self.get("agent.model_map", {}) or {}).values()]
            if preset and any(not SAFE_MODEL.fullmatch(n) for n in names):
                errs.append("agent.model_map names may use only letters, digits and . _ : / @ -")
            if preset and preset not in PRESETS:
                errs.append(f"agent.preset must be one of {', '.join(PRESETS)}, got {preset!r}")
            elif not (self.get("agent.command") or preset):
                errs.append(f"agent.backend=command needs agent.command or agent.preset ({', '.join(PRESETS)})")  # P08-T02
        fallback = self.get("agent.fallback") or []
        if fallback:  # N11 reads the runner table (Q1): a name that is no preset can never run
            from .backends.command import PRESETS
            from .doctor import RUNNERS
            from .handoff import entry_folder
            known = set(PRESETS) | {r.preset for r in RUNNERS if r.preset}
            items = fallback if isinstance(fallback, list) else [fallback]
            bad = [str(n) for n in items if not isinstance(n, dict) and n not in known]
            bad += [str(n) for n in items if isinstance(n, dict) and not entry_folder(n)]  # W28
            if bad:
                errs.append(f"agent.fallback names must be presets ({', '.join(sorted(known))}) or {{claude_cli: {{CLAUDE_CONFIG_DIR: folder}}}}, got {', '.join(bad)}")
        for env in ("staging", "prod"):
            if self.get(f"deploy.{env}.enabled") and not self.get(f"deploy.{env}.cmd"):
                errs.append(f"deploy.{env}.enabled but deploy.{env}.cmd is empty")
        if self.get("deploy.prod.max_auto_risk") not in RISKS:
            errs.append("deploy.prod.max_auto_risk must be one of " + ", ".join(RISKS))
        if not self.commands("build", "lint", "typecheck", "test"):
            errs.append("no verify commands (build/lint/typecheck/test) — the gate would pass anything")
        if self.get("usage.billing", "subscription") not in ("subscription", "api"):
            errs.append("usage.billing must be subscription or api")
        scope = self.get("review.scope", "critical")
        if scope not in REVIEW_SCOPES:  # W4: at run time any other value acts as critical
            errs.append(f"review.scope must be critical or all, got {scope!r}. Use critical to review only critical tasks, "
                        "or all to review every task above low risk.")
        return errs + self._git_errors() + self._sandbox_errors() + self._gate_errors()

    def _gate_errors(self) -> list[str]:
        always = self.get("gate.scope_always")
        if always is not None and (not isinstance(always, list) or not all(isinstance(p, str) for p in always)):
            return ["gate.scope_always must be a list of file paths, for example - REFERENCE.md"]
        mode = self.get("gate.tests")
        if mode is not None and mode not in TEST_MODES:  # W22
            return [f"gate.tests must be changed or full, got {mode!r}. Use changed to run the tests of the changed "
                    "modules per task, or full to run the whole suite per task."]
        return []

    def _sandbox_errors(self) -> list[str]:
        mode = sandbox_mode(self)
        if mode not in SANDBOX_MODES:  # W11
            return [f"sandbox.mode must be off, allowlist or docker, got {mode!r}."]
        if mode == "off" and not allowlist_on(self):
            return []
        if self.get("agent.backend") != "claude_cli":
            what = "sandbox.mode: docker" if mode == "docker" else "sandbox.enabled"
            return [f"{what} needs agent.backend: claude_cli (it runs the Claude CLI)"]
        if mode == "docker" and not str(self.get("sandbox.image", "") or "").strip():
            return ["sandbox.mode: docker needs sandbox.image: the name of the image you built from deploy/Dockerfile."]
        if NATIVE_WINDOWS and mode == "allowlist":  # W32: Claude Code's sandbox is Linux, WSL2 and macOS only; docker runs on Docker Desktop
            return ["sandbox.mode: allowlist is not supported on native Windows: use sandbox.mode: docker (Docker Desktop) or run Autopilot in WSL2"]
        if not allowlist_on(self):
            return []
        if not isinstance(self.get("sandbox.allowed_domains", []), list):
            return ["sandbox.allowed_domains must be a list of host names"]
        unsafe = [a for a in self.get("agent.extra_args", []) if str(a).split("=")[0] in SANDBOX_UNSAFE_ARGS]
        if unsafe:
            return [f"agent.extra_args {unsafe} would override the sandbox; remove them or set sandbox.enabled: false"]
        return []

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
        return errs + self._git_errors() + self._sandbox_errors()
