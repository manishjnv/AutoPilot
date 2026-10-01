"""Verification gate: the orchestrator runs the checks itself instead of trusting the agent."""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "OpenAI-style API key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub token"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"(?i)(password|secret|api_key|apikey|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"), "hardcoded credential"),
]
PROTECTED = [".agent/plan.yaml", ".agent/project.yaml"]


@dataclass
class CmdResult:
    cmd: str
    rc: int
    output: str
    seconds: float


@dataclass
class GateResult:
    ok: bool
    results: list[CmdResult] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def report(self, max_chars: int = 6000) -> str:
        parts = [f"PROBLEM: {p}" for p in self.problems]
        for r in self.results:
            if r.rc != 0:
                parts.append(f"$ {r.cmd}\n(exit {r.rc})\n{r.output}")
        text = "\n\n".join(parts) or "all checks passed"
        return text[-max_chars:]


def run_commands(cmds: list[str], cwd: Path, timeout: int, env: dict | None = None,
                 stop_on_fail: bool = True) -> list[CmdResult]:
    results = []
    full_env = {**os.environ, **(env or {})}
    for cmd in cmds:
        t0 = time.time()
        try:
            p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                               timeout=timeout, env=full_env)
            out = (p.stdout + "\n" + p.stderr).strip()
            rc = p.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = f"TIMEOUT after {timeout}s\n{(e.stdout or '')!s}"[-3000:], 124
        results.append(CmdResult(cmd, rc, out[-4000:], round(time.time() - t0, 1)))
        if rc != 0 and stop_on_fail:
            break
    return results


def scan_secrets(lines: list[str]) -> list[str]:
    found = []
    for line in lines:
        for rx, label in SECRET_PATTERNS:
            if rx.search(line):
                found.append(f"possible {label} added: {line.strip()[:80]}")
    return found


def out_of_scope(files: list[str], scope: list[str]) -> list[str]:
    if not scope:
        return []
    allowed = scope + [".agent/*", ".agent/**", "CHANGELOG.md", "README.md", "docs/**"]
    return [f for f in files if not any(fnmatch.fnmatch(f, g) for g in allowed)]


def verify_commands(cfg, extra: list[str] | None = None, phase: bool = False) -> list[str]:
    cmds = cfg.commands("build", "lint", "typecheck", "test") + list(extra or [])
    if phase:
        cmds += cfg.commands("phase_verify")
    return cmds


def task_gate(cfg, git, task) -> GateResult:
    """Run on the task branch with the agent's changes staged."""
    gate = GateResult(ok=True)
    files = git.staged_files()
    if not files and not task.allow_no_changes:
        gate.problems.append("the session produced no file changes")
    touched_protected = [f for f in files if f in PROTECTED]
    if touched_protected:
        gate.problems.append(f"session modified protected files: {touched_protected}")
    gate.problems += scan_secrets(git.staged_added_lines())
    gate.warnings += [f"outside files_in_scope: {f}" for f in out_of_scope(files, task.files_in_scope)]
    if not gate.problems:
        gate.results = run_commands(verify_commands(cfg, task.verify), cfg.root,
                                    int(cfg.get("verify_timeout_sec", 1200)))
    gate.ok = not gate.problems and all(r.rc == 0 for r in gate.results)
    return gate


def main_gate(cfg, phase: bool = False) -> GateResult:
    results = run_commands(verify_commands(cfg, phase=phase), cfg.root, int(cfg.get("verify_timeout_sec", 1200)))
    return GateResult(ok=all(r.rc == 0 for r in results), results=results)
