"""Context packs: the small, fresh bundle every session starts from (instead of a long-lived chat)."""
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

import yaml

from . import proc
from .gate import verify_commands
from .repomap import helper_index

PROMPTS = Path(__file__).parent / "prompts"
FIX_RULES = ("This is a corrective task. 1) Add a regression test that fails before your fix and passes after it. "
             "2) Include `rca` (symptom, root_cause, fix, prevention) in your final report.")


TAMPER_COUNT_RX = re.compile(r"test count dropped in (\S+): (\d+) -> \d+")


def render(name: str, **vars) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def read_capped(path: Path, max_chars: int, tail: bool = False, default: str = "(none)") -> str:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return default
    if len(text) <= max_chars:
        return text
    return ("…(truncated)…\n" + text[-max_chars:]) if tail else (text[:max_chars] + "\n…(truncated)…")


def bullets(items, empty: str = "(none)") -> str:
    items = [str(i) for i in (items or []) if str(i).strip()]
    return "\n".join(f"- {i}" for i in items) if items else empty


def progress_line(plan, status: dict) -> str:
    total = len(plan.all_tasks())
    counts = {}
    for t in plan.all_tasks():
        s = status.get(t.id, "pending")
        counts[s] = counts.get(s, 0) + 1
    done = counts.get("done", 0)
    pct = (100 * done // total) if total else 0
    return (f"{done}/{total} tasks done ({pct}%), {counts.get('blocked', 0)} blocked, "
            f"{counts.get('pending', 0)} pending across {len(plan.phases)} phases")


def plan_status(plan, state, include_criteria: bool = True, max_chars: int = 30000) -> str:
    lines = []
    status = state.status_map()
    for p in plan.phases:
        lines.append(f"\n### {p.id} {p.title}")
        for t in p.tasks:
            s = status.get(t.id, "pending")
            lines.append(f"- [{s}] {t.id} {t.title} (risk {t.risk})")
            if include_criteria and s == "done":
                for ac in t.acceptance_criteria:
                    lines.append(f"    - AC: {ac}")
            if s == "blocked":
                row = state.task(t.id)
                reason = (row["last_error"] or "")[:300].replace("\n", " ") if row else ""
                lines.append(f"    - BLOCKED: {reason}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "\n…(truncated)…"


class ContextBuilder:
    def __init__(self, cfg, plan, state):
        self.cfg, self.plan, self.state = cfg, plan, state
        self.ad = cfg.agent_dir

    def brain(self) -> str:
        return read_capped(self.ad / "BRAIN.md", 12000)

    def decisions(self) -> str:
        return read_capped(self.ad / "DECISIONS.md", 6000, tail=True)

    def handoff(self) -> str:
        return read_capped(self.ad / "HANDOFF.md", 3000)

    def followups(self) -> str:
        return read_capped(self.ad / "FOLLOWUPS.md", 5000, tail=True)

    def verify_cmds(self, extra=None) -> str:
        return bullets([f"`{c}`" for c in verify_commands(self.cfg, extra)], "(no commands configured)")

    def owner_answers(self, task_id: str) -> str:
        rows = [d for d in self.state.decisions("APPLIED") if task_id in json.loads(d["blocks"] or "[]")]
        out = bullets([f"{d['id']}: {d['question']} → {d['answer']}" for d in reversed(rows)])
        hints = self.hints(task_id)
        return f"{out}\n\n{hints}" if hints else out

    def hints(self, task_id: str) -> str:
        """Owner advice from `autopilot hint`: data for every attempt of the task; the rules still apply."""
        h = self.state.get_meta(f"hints:{task_id}", [])
        return ("Hints from the owner (advice, the rules above still apply):\n"
                + bullets([f"Hint from the owner: {x['text']}" for x in h])) if h else ""

    def unstick_prompt(self, task, error: str) -> str:
        phase = self.plan.phase_of(task)
        return render("unstick.md", task_id=task.id, task_title=task.title, description=task.description or task.title,
                      acceptance=bullets(task.acceptance_criteria), phase_goal=phase.goal or phase.title,
                      decisions=self.decisions(), error=(error or "(none)")[-6000:])

    def review_prompt(self, task, diff: str) -> str:
        phase = self.plan.phase_of(task)
        if len(diff) > 30000:
            diff = diff[:30000] + "\n... (diff cut; read the rest with `git show HEAD`)"
        fence = "`" * max(5, 1 + max((len(m) for m in re.findall(r"`+", diff)), default=0))  # the diff cannot close it
        return render("review.md", task_id=task.id, task_title=task.title, description=task.description or task.title,
                      acceptance=bullets(task.acceptance_criteria), phase_goal=phase.goal or phase.title,
                      decisions=self.decisions(), fence=fence, diff=diff or "(empty)")

    def decide_prompt(self, task) -> str:
        phase = self.plan.phase_of(task)
        return render("decide.md", task_id=task.id, task_title=task.title, phase_goal=phase.goal or phase.title,
                      risk=task.risk, description=task.description or task.title,
                      acceptance=bullets(task.acceptance_criteria), scope=bullets(task.files_in_scope, "(not restricted)"),
                      decisions=self.decisions(), research_block=self.research_block(task))

    def verify_prompt(self, phase, features: list[dict]) -> str:
        init = self.cfg.get("functional.init", "")
        return render("verify.md", phase_id=phase.id, phase_title=phase.title,
                      features="\n".join(f"- `{f['id']}` {f['title']}: {f['journey']}" for f in features),
                      init=f"Run `{init}`." if init else "Work it out from the project brain, the README and the files.")

    def research_prompt(self, task, topic: str) -> str:
        return render("research.md", topic=topic, task_id=task.id, task_title=task.title,
                      description=task.description or task.title,
                      acceptance=bullets(task.acceptance_criteria))

    def triage_prompt(self, number, title: str, body: str) -> str:
        tag = f"UNTRUSTED-{secrets.token_hex(6)}"  # unguessable, so the issue text can't fake the end of its block
        return render("triage.md", number=number, tag=tag, title=" ".join(str(title).split())[:200],
                      body=str(body or "(empty)")[:6000])

    def research_block(self, task) -> str:
        """The research notes for the task's topics: summaries written by a research session, never raw web text."""
        from .docs import research_path  # local: import cycle with docs
        notes = [read_capped(research_path(self.cfg, t), 4000, default="") for t in task.research]
        notes = [n for n in notes if n]
        head = "## Research for this task (summaries; use them, don't re-search)\n"
        return head + "\n\n".join(notes) if notes else ""

    def adr_block(self, task) -> str:
        rel = self.state.get_meta(f"adr:{task.id}")
        if not rel:
            return ""
        return (f"## Approach decided for this task (follow it; ADR `{rel}`)\n"
                + read_capped(self.cfg.root / rel, 8000, default="(the ADR file is missing)"))

    def task_prompt(self, task, attempt: int, last_error: str | None, git_log: str = "") -> str:
        phase = self.plan.phase_of(task)
        retry = ""
        if attempt > 1 and last_error:
            retry = render("retry.md", attempt=attempt - 1, errors=last_error[-6000:])
            # J14.4: a tamper failure becomes one instruction with the real file and count
            keep = [f"Keep all {m[1]} tests in {m[0]}. Add, do not remove." for m in TAMPER_COUNT_RX.findall(last_error)]
            retry += "".join(f"\n**{k}**\n" for k in keep)
        return render(
            "task.md", task_id=task.id, task_title=task.title, phase_id=phase.id, phase_title=phase.title,
            phase_goal=phase.goal, risk=task.risk,
            description=task.description or task.title, acceptance=bullets(task.acceptance_criteria),
            scope=bullets(task.files_in_scope, "(not restricted)"), docs=bullets(task.docs, "(whatever this change affects)"),
            decisions=self.decisions(), handoff=self.handoff(),
            progress=progress_line(self.plan, self.state.status_map()), retry_block=retry,
            verify_cmds=self.verify_cmds(task.verify), owner_answers=self.owner_answers(task.id),
            git_log=git_log.strip() or "(none)", fix_rules=FIX_RULES if phase.priority else "",
            adr_block=self.adr_block(task), research_block=self.research_block(task),
            helper_index=helper_index(self.cfg.root) or "(none)",
        )

    def resume_prompt(self, task, attempt: int, last_error: str | None) -> str:
        """Retry inside the failed attempt's own session: the brief is already in its context, so only the failure."""
        return render("resume.md", task_id=task.id, task_title=task.title, verify_cmds=self.verify_cmds(task.verify),
                      retry_block=render("retry.md", attempt=attempt - 1, errors=(last_error or "(none)")[-6000:])
                      + (f"\n\n{h}" if (h := self.hints(task.id)) else ""))

    def fixer_prompt(self, errors: str, git_log: str) -> str:
        return render("fixer.md", decisions=self.decisions(), git_log=git_log,
                      errors=errors[-8000:], verify_cmds=self.verify_cmds())

    def auditor_prompt(self, kind: str, max_new: int) -> str:
        completion = ("Completion: is the product described in the goal actually complete and usable end to end? "
                      "Set complete=true ONLY if nothing important is missing." if kind == "completion"
                      else "Set complete=false unless the entire goal is already met.")
        return render("auditor.md", audit_kind=kind, plan_status=plan_status(self.plan, self.state),
                      decisions=self.decisions(), followups=self.followups(), completion_check=completion, max_new=max_new)

    def replanner_prompt(self, backlog: list[str] | None = None, source_diff: str = "") -> str:
        blocked = [f"{r['id']}: {(r['last_error'] or '')[:500]}" for r in self.state.tasks("blocked")]
        return render("replanner.md", plan_status=plan_status(self.plan, self.state, include_criteria=False),
                      blocked=bullets(blocked), decisions=self.decisions(), followups=self.followups(),
                      backlog=bullets([i[:500] for i in backlog or []][:30]),
                      source_diff=source_diff or "(none)")

    def system_append(self) -> str:
        """The rules plus the project context every session needs. U7: byte-identical for every session until
        BRAIN.md, LEARNINGS.md or the goal changes, and it rides in the system prompt, which Claude Code caches; so
        later sessions on the same model read it from the cache. No timestamps or task data here."""
        text = ((PROMPTS / "system.md").read_text(encoding="utf-8").rstrip()
                + f"\n\n# Project context (the same for every session)\n\n## Project goal\n"
                  f"{self.plan.goal or '(see the project brain)'}\n\n"
                  f"## Project brain (architecture, conventions, invariants)\n{self.brain()}\n")
        learned = read_capped(self.ad / "LEARNINGS.md", 4000, tail=True, default="")
        if learned:
            text += f"\n## Learnings from earlier failures (don't repeat them)\n{learned}\n"
        return text


# N1: discovery pack for onboarding: read before write
PACK_CAP = 60000
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
_DOC_DIRS = {"docs", ".kiro", ".cursor", ".github"}
_DOC_STEMS = {"roadmap", "todo", "plan", "changelog", "notes"}
_PLAN_STEMS = {"plan", "roadmap", "todo", "notes"}


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…(truncated: section over {limit} characters)…"


def _doc_files(root: Path) -> list[Path]:
    out = []
    for dp, dns, fns in os.walk(root):
        rel = Path(dp).relative_to(root)
        dns[:] = sorted(d for d in dns if d not in _SKIP_DIRS and (rel / d).as_posix() != ".agent/logs")
        for f in sorted(fns):
            r = rel / f
            top = r.parts[0] if len(r.parts) > 1 else ""
            if f.lower().endswith(".md") or top in _DOC_DIRS or Path(f).stem.lower() in _DOC_STEMS:
                out.append(r)
    return out


def _is_plan_like(r: Path) -> bool:
    return r.stem.lower() in _PLAN_STEMS or (len(r.parts) > 1 and r.parts[0].lower() == "notes")


def _head(path: Path, lines: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:lines])
    except OSError:
        return ""


def _git_section(root: Path) -> str:
    try:
        p = proc.run_proc(["git", "log", "--oneline", "-200"], cwd=str(root), timeout=60)
    except OSError:
        return ""
    return p.stdout.strip() if p.rc == 0 else ""


def _stack_section(root: Path) -> str:
    names: list[str] = []
    for f in sorted((Path(__file__).parent / "templates" / "presets").glob("*.yaml")):
        try:
            names += [str(n) for n in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("detect", [])]
        except (OSError, yaml.YAMLError):
            pass
    parts = [f"### {n}\n```\n{_head(root / n, 30)}\n```" for n in dict.fromkeys(names) if (root / n).is_file()]
    return "\n\n".join(parts) or "(no stack files found)"


def _test_section(root: Path, cfg) -> str:
    cmds = cfg.commands("test")
    if not cmds:
        return "no test command"
    secs = int(cfg.get("onboard.test_timeout_sec", 300) or 300)
    out = []
    for c in cmds:
        try:
            p = proc.run_proc(c, cwd=str(root), timeout=secs, shell=True)
        except OSError as e:
            out.append(f"$ {c}\nexit code: not started ({e})")
            continue
        tail = "\n".join((p.stdout + "\n" + p.stderr).strip().splitlines()[-40:])
        status = f"timed out after {secs} s, stopped" if p.timed_out else f"exit code: {p.rc}"
        out.append(f"$ {c}\n{status}\n```\n{tail}\n```")
    return "\n\n".join(out)


def discovery_pack(root, cfg) -> str:
    """N1: git log, document tree, stack files and one test run, as markdown under PACK_CAP characters."""
    root = Path(root)
    tree = []
    for r in _doc_files(root):
        try:
            size = (root / r).stat().st_size
        except OSError:
            continue
        tree.append(f"- {r.as_posix()} ({size} bytes)")
        if _is_plan_like(r):
            h = _head(root / r, 40)
            if h:
                tree.append("  ```\n" + "\n".join("  " + x for x in h.splitlines()) + "\n  ```")
    secs = [("Git log (last 200 commits)", _git_section(root) or "(no git history)", 8000),
            ("Documents", "\n".join(tree) or "(no documents found)", 24000),
            ("Stack files", _stack_section(root), 12000),
            ("Test command result", _test_section(root, cfg), 8000)]
    pack = "\n\n".join(f"## {t}\n{_cap(b, n)}" for t, b, n in secs)
    return _cap(pack, PACK_CAP)
