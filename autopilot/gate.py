"""Verification gate: the orchestrator runs the checks itself instead of trusting the agent."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import allowlist_on, scope_always, tests_mode
from .contracts import contract_problems
from .kill_guard import kill_commands
from .proc import agent_env, run_proc, with_tool_dirs

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
    (re.compile(r"\bcf_[A-Za-z0-9_\-]{20,}"), "Cloudflare API token"),
    (re.compile(r"\bre_[A-Za-z0-9_]{20,}"), "Resend API key"),
    (re.compile(r"\bpmark_live_[A-Za-z0-9]{20,}"), "Postmark token"),
    # SSH private keys (RSA/EC/OPENSSH/plain) are already caught by the "private key" line above
    (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{33}\b"), "Telegram bot token"),
    (re.compile(r"(?i)(password|secret|api_key|apikey|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"), "hardcoded credential"),
]
TEST_GLOBS = ["tests/**", "test/**", "**/tests/**", "**/test/**", "test_*.py", "*_test.py", "*_test.go", "*.test.*",
              "*.spec.*", "**/__tests__/**", "src/test/**"]
TEST_DEF_RX = re.compile(r"^\s*(?:async\s+def\s+test_|def\s+test_|func\s+Test|@Test\b|#\[test\])|\b(?:it|test)\s*\(", re.M)
SKIP_RX = re.compile(r"@pytest\.mark\.skip|pytest\.skip\(|@unittest\.skip|\.skip\(|\bxit\(|\bxdescribe\(|\.only\(|t\.Skip\(|"
                     r"@Disabled|@Ignore|#\[ignore\]")
ASSERT_RX = re.compile(r"\bassert\w*\b|\bexpect\s*\(|\bt\.(?:Error|Fatal)\w*\(|\brequire\.\w+\(|\.should\b")
COLLECT_RX = re.compile(r"pytest_collection_modifyitems|pytest_ignore_collect|collect_ignore|deselect")
PLACEHOLDER_RX = re.compile(r"(?i)example|placeholder|change_?me|dummy|fake|sample|your[_-]|xxx|\*\*\*|<[^>]*>|\$\{|\{\{|%\(")
# G2: each finding says how to fix it. The retry reads these; no rule is weaker for it.
SKIP_HINT = (" (skips are not allowed, `skipif` on a platform condition too: make the test run on this machine, "
             "or test the behavior another way and list the gap under followups)")
FAKE_HINT = " (test data? put example, dummy or fake inside the value itself, e.g. AKIAIOSFODNN7EXAMPLE, ghp_fakefake…)"
FAKE_SECRET_RULE = ("A fake secret in a test is built from pieces (`'sk-' + 'a' * 24`), never written as one literal: "
                    "the secret scan cannot tell a fake key from a real one.")
# N7: the new-file rule; system.md repeats it word for word and the gate (P07-T02) quotes it in the retry
# (only with `gate.new_file_reasons: true`)
NEW_FILE_RULE = ("Edit the file that owns the content; a move or rename is allowed. A new file (test files excepted) "
                 "needs a reason: list each one with its reason in the report field `new_files`.")
SETTINGS_FILES = {"pyproject.toml", "setup.cfg", "package.json", "tox.ini", "pytest.ini"}
SETTINGS_REMOVED_RX = re.compile(r'addopts|testpaths|python_files|"test"\s*:|testMatch|testPathIgnorePatterns')
SETTINGS_ADDED_RX = re.compile(r"--ignore|--deselect|(^|\s)-k\s|testPathIgnorePatterns|modulePathIgnorePatterns|"
                               r"--passWithNoTests|\|\|\s*true|exit 0")
# features.json and LEARNINGS.md are written only by the orchestrator (LEARNINGS feeds every session's system prompt)
PROTECTED = [".agent/plan.yaml", ".agent/project.yaml", ".agent/features.json", ".agent/LEARNINGS.md"]


def protected_files(cfg) -> list[str]:
    """Files no agent session may change: the plan, the config and the owner's answers (it would answer itself)."""
    owner = [cfg.get("needs_you.path", "docs/NEEDS-YOU.md"), cfg.get("docs.backlog", "docs/BACKLOG.md")]  # L7: ideas
    if allowlist_on(cfg):  # P5: project settings merge into later sessions and could widen the allowlist
        owner += [".claude/settings.json", ".claude/settings.local.json", ".mcp.json"]
    return PROTECTED + [str(p).replace("\\", "/") for p in owner if p]
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

    def keepable(self) -> bool:
        """W25: a failure whose diff is worth keeping: only scope lines, or only failed test commands."""
        return (bool(self.problems) or any(r.rc != 0 for r in self.results)) and all(
            p.startswith(("outside files_in_scope", "scope_additions")) for p in self.problems)

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
    full_env = with_tool_dirs({**(base_env if base_env is not None else os.environ), **(env or {})})
    for cmd in cmds:
        t0 = time.monotonic()
        try:
            p = run_proc(cmd, shell=True, cwd=cwd, env=full_env, timeout=timeout)
            out, rc = (p.stdout + "\n" + p.stderr).strip(), p.rc
            if p.timed_out:
                out, rc = f"TIMEOUT after {timeout}s\n{out}", 124
        except OSError as e:
            out, rc = str(e), 127
        results.append(CmdResult(cmd, rc, out[-4000:], round(time.monotonic() - t0, 1)))
        if rc != 0 and stop_on_fail:
            break
    return results


def scan_secrets(lines: list[str]) -> list[str]:
    found, hint = [], FAKE_HINT  # the hint rides on the first such finding only
    for line in lines:
        for rx, label in SECRET_PATTERNS:
            m = rx.search(line)
            # test data: a placeholder word inside the matched value itself (AKIAIOSFODNN7EXAMPLE, ghp_fake…); a
            # private-key header has no value, so the word may stand anywhere on its line. The hint says the same.
            fake = PLACEHOLDER_RX.search(m.group(0)) or (label == "private key" and PLACEHOLDER_RX.search(line)) if m else None
            if m and not fake:
                # redacted: these messages reach logs, prompts and notifications
                msg = f"possible {label} added: {line.replace(m.group(0), m.group(0)[:4] + '…').strip()[:80]}"
                if label == "hardcoded credential":  # a real-looking key gets no "just rename it" hint
                    msg, hint = msg + hint, ""
                found.append(msg)
    return found


SCOPE_FREE = [".agent/*", ".agent/**", "CHANGELOG.md", "README.md", "docs/**", "tests/**", "test/**"]  # O1 allowlist
SCOPE_HINT = ('Add each file to the task scope with a reason in the report ("scope_additions": {"path": "why"}, '
              "counted from attempt 2, at most 3), or leave it unchanged.")
SCOPE_MAX_ADDS = 3


def out_of_scope(files: list[str], scope: list[str], extra: list[str] | None = None) -> list[str]:
    """Changed files outside the task's `files_in_scope` globs. An empty scope means the whole repo (nothing is out).
    `extra`: globs the session added with a reason (O1)."""
    if not scope:
        return []
    allowed = list(scope) + list(extra or []) + SCOPE_FREE
    return [f for f in files if not any(fnmatch.fnmatch(f, g) for g in allowed)]


def scope_additions(report, attempt: int = 1, files: list[str] | None = None) -> tuple[list[str], list[str], list[str]]:
    """O1: the report's `scope_additions` {"path": "reason"}: only entries with a reason count, only from attempt 2
    (the first try must stay in scope), at most SCOPE_MAX_ADDS, and each key must be a changed file's exact path (no
    glob: `*` would open the whole repository). Returns (accepted paths, warnings, problems); every accepted addition
    is a warning `scope added: <file>: <reason>` that lands in the history file, PROOF.md and the dashboard."""
    adds = (report or {}).get("scope_additions") if isinstance(report, dict) else None
    pairs = [(str(k), str(v).strip()) for k, v in adds.items() if str(v or "").strip()] if isinstance(adds, dict) else []
    if not pairs:
        return [], [], []
    if attempt < 2:
        return [], [], [f"scope_additions count only from attempt 2: {[k for k, _ in pairs]}. Leave the file unchanged."]
    if len(pairs) > SCOPE_MAX_ADDS:
        return [], [], [f"scope_additions: {len(pairs)} given, at most {SCOPE_MAX_ADDS}. Keep the task in its scope."]
    if bad := [k for k, _ in pairs if k not in (files or [])]:
        return [], [], [f"scope_additions must name a changed file exactly (no pattern): {bad}"]
    return [k for k, _ in pairs], [f"scope added: {k}: {v}" for k, v in pairs], []


def changed_tests(cfg, cmd: str, files: list[str]) -> str:
    """O10: the test command narrowed to the changed modules; the full command when nothing maps. pytest: by path
    (`tests/test_<module>.py` when it exists, else the test files in the diff); vitest: `related`; go: changed dirs."""
    tests = cfg.get("gate.test_globs") or TEST_GLOBS
    if "pytest" in cmd:
        paths = []
        for f in files:
            stem = f.rsplit("/", 1)[-1].removesuffix(".py")
            mapped = f"tests/test_{stem}.py"
            if f.endswith(".py") and _match(f, tests):
                paths.append(f)
            elif f.endswith(".py") and (cfg.root / mapped).exists():
                paths.append(mapped)
        return f"{cmd} {' '.join(dict.fromkeys(paths))}" if paths else cmd
    code = [f for f in files if re.search(r"\.(?:[cm]?[jt]sx?)$", f) and not _match(f, tests)]
    if "vitest" in cmd and code:
        return re.sub(r"vitest(\s+run)?", f"vitest related {' '.join(code)} --run", cmd, count=1)
    dirs = {f.rsplit("/", 1)[0] if "/" in f else "" for f in files if f.endswith(".go")}
    if "go test" in cmd and dirs and "" not in dirs:
        return cmd.replace("./...", " ".join(f"./{d}/..." for d in sorted(dirs)))
    return cmd


def verify_commands(cfg, extra: list[str] | None = None, phase: bool = False, files: list[str] | None = None) -> list[str]:
    tests = cfg.commands("test")
    if files is not None and not phase and tests_mode(cfg) == "changed":  # W22: per task the changed modules' tests in every profile; the phase close runs it all
        tests = [changed_tests(cfg, c, files) for c in tests]
    cmds = cfg.commands("build", "lint", "typecheck") + tests + list(extra or [])
    if phase:
        cmds += cfg.commands("phase_verify")
    return cmds


def _match(path: str, globs) -> bool:
    return any(fnmatch.fnmatch(path if "/" in g else path.rsplit("/", 1)[-1], g) for g in globs)


def _added(git, path: str) -> list[str]:
    diff = git.run("diff", "--cached", "-U0", "--no-color", "--no-textconv", "--no-ext-diff", "--", path).splitlines()
    return [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]


def test_tamper(cfg, git, allow: bool = False) -> list[str]:
    """Weakened tests or CI changes in the staged diff vs HEAD. New test files never count; `allow` only labels."""
    tests = cfg.get("gate.test_globs") or TEST_GLOBS
    protected = cfg.get("gate.protected") or []
    ci = cfg.get("gate.ci_files") or CI_GLOBS
    out, tag, hint = [], "(allowed) " if allow else "", "" if allow else SKIP_HINT

    def skips(path):  # one hint per file: the retry prompt keeps only the tail of the report
        marks = [f"{tag}skip/focus marker added in {path}: {l.strip()[:80]}" for l in _added(git, path) if SKIP_RX.search(l)]
        return [marks[0] + hint, *marks[1:]] if marks else []

    status = git.run("-c", "core.quotepath=false", "diff", "--cached", "--name-status", "-M")
    for line in status.splitlines():
        st, *paths = line.split("\t")
        st, old, new = st[0], paths[0], paths[-1]
        if new.rsplit("/", 1)[-1] == "conftest.py" and st != "D":
            out += [f"{tag}test collection hook in {new}: {l.strip()[:80]}" for l in _added(git, new) if COLLECT_RX.search(l)]
        if _match(old, ci) or _match(new, ci):
            out.append(f"{tag}CI pipeline file {dict(A='added', C='added', D='deleted').get(st, 'changed')}: {new}")
        if st == "A" or st == "C":
            if st == "A" and _match(new, tests):
                out += skips(new)
            continue
        if _match(old, tests):
            if st == "D":
                out.append(f"{tag}test file deleted: {old}")
            elif st == "R" and not _match(new, tests):
                out.append(f"{tag}test file renamed to a non-test path: {old} -> {new}")
            else:
                head = git.run("cat-file", "blob", f"HEAD:{old}", check=False)  # plumbing: no textconv
                staged = git.run("cat-file", "blob", f":{new}", check=False)
                before, after = len(TEST_DEF_RX.findall(head)), len(TEST_DEF_RX.findall(staged))
                if after < before:
                    out.append(f"{tag}test count dropped in {new}: {before} -> {after}")
                before, after = len(ASSERT_RX.findall(head)), len(ASSERT_RX.findall(staged))
                if after < before:  # tests kept but emptied
                    out.append(f"{tag}assertion count dropped in {new}: {before} -> {after}")
                out += skips(new)
        if _match(old, protected):
            out.append(f"{tag}protected file {'deleted' if st == 'D' else 'modified'}: {old}")
        if st == "M" and new.rsplit("/", 1)[-1] in SETTINGS_FILES:
            for l in git.run("diff", "--cached", "-U0", "--no-color", "--no-textconv", "--no-ext-diff", "--", new).splitlines():
                if l.startswith("-") and not l.startswith("---") and SETTINGS_REMOVED_RX.search(l):
                    out.append(f"{tag}test setting removed in {new}: {l[1:].strip()[:80]}")
                elif l.startswith("+") and not l.startswith("+++") and SETTINGS_ADDED_RX.search(l[1:]):
                    out.append(f"{tag}test setting weakened in {new}: {l[1:].strip()[:80]}")
    return out


test_tamper.__test__ = False  # stop pytest collecting it when imported into test modules


def _norm(path) -> str:
    return str(path).replace("\\", "/").strip().removeprefix("./")


MANIFESTS = ["package.json", "pyproject.toml", "requirements*.txt", "go.mod", "Cargo.toml", "Gemfile", "pom.xml",
             "build.gradle*"]  # O3: a change here is a new dependency unless declared
DEP_RULE = ("A new dependency needs a reason: the task lists it under `new_deps`, or the report lists each one with "
            "its reason in the field `new_deps`.")
DOC_GLOBS = ["docs/**", "LICENSE*"]  # a root NOTES2.md still needs a reason (N7: no second notes file)
CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs",
            ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".scala", ".sh", ".ps1", ".sql", ".vue", ".svelte")
GROWTH_LINES, GROWTH_PCT = 400, 25  # O2: a file may not grow past 400 lines or 25 percent in one task, the larger


def missing_reasons(cfg, git, report, task=None) -> list[str]:
    """N7: files added in the staged diff (test files, .agent/ and renames excepted) need a `new_files` reason.
    O3: files the task declares under `new_files` pass; a manifest change needs `new_deps` on the task or in the report."""
    tests = cfg.get("gate.test_globs") or TEST_GLOBS
    added = git.run("-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--diff-filter=A", "-M").splitlines()
    entries = report.get("new_files") if isinstance(report, dict) else None
    reasons = {_norm(e["path"]) for e in (entries if isinstance(entries, list) else [])
               if isinstance(e, dict) and str(e.get("path") or "").strip() and str(e.get("reason") or "").strip()}
    declared = [_norm(p) for p in (getattr(task, "new_files", None) or [])]
    bare = [p for p in added if p and not _match(p, tests) and not _match(p, DOC_GLOBS) and not p.startswith(".agent/")
            and p not in reasons and not _match(p, declared)]
    out = []
    if bare:
        paths = ", ".join(bare[:20]) + (f", and {len(bare) - 20} more" if len(bare) > 20 else "")
        out.append(f"new file without a reason: {paths}. {NEW_FILE_RULE}")  # the rule last: the retry keeps the tail
    changed = git.run("-c", "core.quotepath=false", "diff", "--cached", "--name-only").splitlines()
    # a manifest the task creates (new file with a reason, or declared) is the project's first one: no `new_deps` needed
    manifests = [p for p in changed if _match(p, MANIFESTS)
                 and not (p in added and (_norm(p) in reasons or _match(_norm(p), declared)))]
    deps = report.get("new_deps") if isinstance(report, dict) else None
    with_reason = [d for d in (deps if isinstance(deps, list) else []) if isinstance(d, dict)
                   and str(d.get("name") or "").strip() and str(d.get("reason") or "").strip()]
    if manifests and not (getattr(task, "new_deps", None) or with_reason):
        out.append(f"dependency manifest changed without a declared dependency: {', '.join(manifests)}. {DEP_RULE}")
    return out


def _count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def write_baseline(root) -> int:
    """O2: `.agent/quality_baseline.json` = line count per code file on day one; only growth past it (and the budget)
    fails later. Returns the number of files recorded."""
    root = Path(root)
    skip = {".git", ".agent", "node_modules", ".venv", "venv", "env", "dist", "build", "__pycache__", "docs"}
    counts = {}
    for p in root.rglob("*"):
        if any(part in skip for part in p.relative_to(root).parts) or not p.is_file() or p.suffix not in CODE_EXT:
            continue
        rel = p.relative_to(root).as_posix()
        if not _match(rel, TEST_GLOBS):
            counts[rel] = _count_lines(p)
    out = root / ".agent" / "quality_baseline.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(counts, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    return len(counts)


def growth_limit(cfg, path: str, lines: int) -> int:
    """O2: the line limit of one code file that has `lines` lines now: max(400, +25 percent of those lines or of its baseline)."""
    try:
        base = int(json.loads((cfg.root / ".agent" / "quality_baseline.json").read_text(encoding="utf-8")).get(path, 0))
    except (OSError, ValueError, TypeError, AttributeError):
        base = 0
    return max([GROWTH_LINES] + [n * (100 + GROWTH_PCT) // 100 for n in (lines, base) if n > GROWTH_LINES])


def file_growth(cfg, git) -> list[str]:
    """O2: a changed code file may not grow past max(400 lines, +25 percent, 125 percent of its baseline) in one task."""
    tests = cfg.get("gate.test_globs") or TEST_GLOBS
    out = []
    for line in git.run("-c", "core.quotepath=false", "diff", "--cached", "--numstat").splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        plus, minus, path = int(parts[0]), int(parts[1]), parts[2]
        if plus <= minus or not path.endswith(CODE_EXT) or _match(path, tests):
            continue
        new = _count_lines(cfg.root / path)
        old = new - plus + minus
        limit = growth_limit(cfg, path, old)
        if new > limit:
            out.append(f"file grew past the budget: {path} {old} -> {new} lines (limit {limit}). Split, do not grow.")
    return out


def _added(git, path: str) -> list[str]:
    out = git.run("diff", "--cached", "-U0", "--no-color", "--no-textconv", "--no-ext-diff", "--", path)
    return [l[1:] for l in out.splitlines() if l.startswith("+") and not l.startswith("+++")]


def task_gate(cfg, git, task, report=None, attempt: int = 1, log_path=None) -> GateResult:
    """Run on the task branch with the agent's changes staged. `attempt`: the try this diff comes from (O1).
    `log_path`: the session log; a kill by name in it fails the gate (W37)."""
    gate = GateResult(ok=True)
    files = git.staged_files()
    if not files and not task.allow_no_changes:
        gate.problems.append("the session produced no file changes")
    touched_protected = [f for f in files if f in protected_files(cfg)]
    if touched_protected:
        gate.problems.append(f"session modified protected files: {touched_protected}")
    (gate.warnings if task.allow_test_changes else gate.problems).extend(test_tamper(cfg, git, task.allow_test_changes))
    gate.problems += contract_problems(cfg, git, report)  # W36b: always a problem, even with allow_test_changes
    found = scan_secrets(git.staged_added_lines())
    if found and any(scan_secrets(_added(git, f)) for f in files if _match(f, cfg.get("gate.test_globs") or TEST_GLOBS)):
        found[0] += " " + FAKE_SECRET_RULE  # W44: the flagged file is a test
    gate.problems += found
    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace") if log_path and Path(log_path).is_file() else ""
    gate.problems += [f"the session ran a process-wide kill: {c}. Stop only the processes you started, by pid."
                      for c in kill_commands(log_text)]
    if report is not None and cfg.get("gate.new_file_reasons"):  # N7: P07-T02; None = old callers, no check
        gate.problems += missing_reasons(cfg, git, report, task)  # O3: task-declared files and dependencies
    if cfg.get("gate.file_growth"):  # O2: on in the template (new projects); a missing key = off
        gate.problems += file_growth(cfg, git)
    if cfg.get("gate.layers", True):  # O4: the ```layers block in BRAIN.md is the real switch; no block = no check
        from .layers import layers_problems  # local: layers.py imports gate.py
        gate.problems += layers_problems(cfg, git)
    extra, added, bad = scope_additions(report, attempt, files)
    outside = out_of_scope(files, task.files_in_scope, extra + scope_always(cfg))  # W19: docs are always in scope
    if (outside or bad) and cfg.get("gate.scope_fail", True):  # O1: a hard gate; `gate.scope_fail: false` = old warning
        gate.problems += bad + ([f"outside files_in_scope: {outside}. {SCOPE_HINT}"] if outside else [])
    else:
        gate.warnings += [f"outside files_in_scope: {f}" for f in outside]
        gate.warnings += added
    if not gate.problems:
        gate.results = run_commands(verify_commands(cfg, task.verify, files=files), cfg.root,
                                    int(cfg.get("verify_timeout_sec", 1200)), base_env=agent_env(cfg))
    gate.ok = not gate.problems and all(r.rc == 0 for r in gate.results)
    return gate


def main_gate(cfg, phase: bool = False) -> GateResult:
    results = run_commands(verify_commands(cfg, phase=phase), cfg.root, int(cfg.get("verify_timeout_sec", 1200)),
                           base_env=agent_env(cfg))
    return GateResult(ok=all(r.rc == 0 for r in results), results=results)
