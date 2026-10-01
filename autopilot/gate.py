"""Verification gate: the orchestrator runs the checks itself instead of trusting the agent."""
from __future__ import annotations

import fnmatch
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .proc import agent_env, run_proc

SECRET_PATTERNS = [
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"), "OpenAI/Anthropic API key"),
    (re.compile(r"\bxai-[A-Za-z0-9]{20,}"), "xAI API key"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "Hugging Face token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub token"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"), "GitLab token"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{30,}"), "Google API key"),
    (re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{20,}"), "Google OAuth secret"),
    (re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}"), "Stripe live key"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"), "Slack webhook"),
    (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{33}\b"), "Telegram bot token"),
    (re.compile(r"(?i)(password|secret|api_key|apikey|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"), "hardcoded credential"),
]
TEST_GLOBS = ["tests/**", "test/**", "**/tests/**", "**/test/**", "test_*.py", "*_test.py", "*_test.go", "*.test.*",
              "*.spec.*", "**/__tests__/**", "src/test/**"]
TEST_DEF_RX = re.compile(r"^\s*(?:async\s+def\s+test_|def\s+test_|func\s+Test|@Test\b|#\[test\])|\b(?:it|test)\s*\(", re.M)
SKIP_RX = re.compile(r"@pytest\.mark\.skip|pytest\.skip\(|@unittest\.skip|\.skip\(|\bxit\(|\bxdescribe\(|\.only\(|t\.Skip\(|"
                     r"@Disabled|@Ignore|#\[ignore\]")
SETTINGS_FILES = {"pyproject.toml", "setup.cfg", "package.json", "tox.ini", "pytest.ini"}
SETTINGS_REMOVED_RX = re.compile(r'addopts|testpaths|python_files|"test"\s*:|testMatch|testPathIgnorePatterns')
SETTINGS_ADDED_RX = re.compile(r"--ignore|--deselect|(^|\s)-k\s|testPathIgnorePatterns|modulePathIgnorePatterns|"
                               r"--passWithNoTests|\|\|\s*true|exit 0")
PROTECTED = [".agent/plan.yaml", ".agent/project.yaml"]
# CI runs with repository secrets on push: adding, editing or deleting a pipeline is never routine task work
CI_GLOBS = [".github/workflows/**", ".gitlab-ci.yml", ".circleci/**", "Jenkinsfile", "azure-pipelines.yml",
            "bitbucket-pipelines.yml", ".buildkite/**"]


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
                 stop_on_fail: bool = True, base_env: dict | None = None) -> list[CmdResult]:
    results = []
    full_env = {**(base_env if base_env is not None else os.environ), **(env or {})}
    for cmd in cmds:
        t0 = time.time()
        try:
            p = run_proc(cmd, shell=True, cwd=cwd, env=full_env, timeout=timeout)
            out, rc = (p.stdout + "\n" + p.stderr).strip(), p.rc
            if p.timed_out:
                out, rc = f"TIMEOUT after {timeout}s\n{out}", 124
        except OSError as e:
            out, rc = str(e), 127
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


def _match(path: str, globs) -> bool:
    return any(fnmatch.fnmatch(path if "/" in g else path.rsplit("/", 1)[-1], g) for g in globs)


def _added(git, path: str) -> list[str]:
    diff = git.run("diff", "--cached", "-U0", "--no-color", "--", path).splitlines()
    return [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]


def test_tamper(cfg, git, allow: bool = False) -> list[str]:
    """Weakened tests or CI changes in the staged diff vs HEAD. New test files never count; `allow` only labels."""
    tests = cfg.get("gate.test_globs") or TEST_GLOBS
    protected = cfg.get("gate.protected") or []
    ci = cfg.get("gate.ci_files") or CI_GLOBS
    out, tag = [], "(allowed) " if allow else ""
    status = git.run("-c", "core.quotepath=false", "diff", "--cached", "--name-status", "-M")
    for line in status.splitlines():
        st, *paths = line.split("\t")
        st, old, new = st[0], paths[0], paths[-1]
        if _match(old, ci) or _match(new, ci):
            out.append(f"{tag}CI pipeline file {dict(A='added', C='added', D='deleted').get(st, 'changed')}: {new}")
        if st == "A" or st == "C":
            if st == "A" and _match(new, tests):
                out += [f"{tag}skip/focus marker added in {new}: {l.strip()[:80]}" for l in _added(git, new) if SKIP_RX.search(l)]
            continue
        if _match(old, tests):
            if st == "D":
                out.append(f"{tag}test file deleted: {old}")
            elif st == "R" and not _match(new, tests):
                out.append(f"{tag}test file renamed to a non-test path: {old} -> {new}")
            else:
                before = len(TEST_DEF_RX.findall(git.run("show", f"HEAD:{old}", check=False)))
                after = len(TEST_DEF_RX.findall(git.run("show", f":{new}", check=False)))
                if after < before:
                    out.append(f"{tag}test count dropped in {new}: {before} -> {after}")
                out += [f"{tag}skip/focus marker added in {new}: {l.strip()[:80]}" for l in _added(git, new) if SKIP_RX.search(l)]
        if _match(old, protected):
            out.append(f"{tag}protected file {'deleted' if st == 'D' else 'modified'}: {old}")
        if st == "M" and new.rsplit("/", 1)[-1] in SETTINGS_FILES:
            for l in git.run("diff", "--cached", "-U0", "--no-color", "--", new).splitlines():
                if l.startswith("-") and not l.startswith("---") and SETTINGS_REMOVED_RX.search(l):
                    out.append(f"{tag}test setting removed in {new}: {l[1:].strip()[:80]}")
                elif l.startswith("+") and not l.startswith("+++") and SETTINGS_ADDED_RX.search(l[1:]):
                    out.append(f"{tag}test setting weakened in {new}: {l[1:].strip()[:80]}")
    return out


test_tamper.__test__ = False  # stop pytest collecting it when imported into test modules


def task_gate(cfg, git, task) -> GateResult:
    """Run on the task branch with the agent's changes staged."""
    gate = GateResult(ok=True)
    files = git.staged_files()
    if not files and not task.allow_no_changes:
        gate.problems.append("the session produced no file changes")
    touched_protected = [f for f in files if f in PROTECTED]
    if touched_protected:
        gate.problems.append(f"session modified protected files: {touched_protected}")
    (gate.warnings if task.allow_test_changes else gate.problems).extend(test_tamper(cfg, git, task.allow_test_changes))
    gate.problems += scan_secrets(git.staged_added_lines())
    gate.warnings += [f"outside files_in_scope: {f}" for f in out_of_scope(files, task.files_in_scope)]
    if not gate.problems:
        gate.results = run_commands(verify_commands(cfg, task.verify), cfg.root,
                                    int(cfg.get("verify_timeout_sec", 1200)), base_env=agent_env(cfg))
    gate.ok = not gate.problems and all(r.rc == 0 for r in gate.results)
    return gate


def main_gate(cfg, phase: bool = False) -> GateResult:
    results = run_commands(verify_commands(cfg, phase=phase), cfg.root, int(cfg.get("verify_timeout_sec", 1200)),
                           base_env=agent_env(cfg))
    return GateResult(ok=all(r.rc == 0 for r in results), results=results)
