"""Context packs: the small, fresh bundle every session starts from (instead of a long-lived chat)."""
from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"
FIX_RULES = ("This is a corrective task. 1) Add a regression test that fails before your fix and passes after it. "
             "2) Include `rca` (symptom, root_cause, fix, prevention) in your final report.")


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
        from .gate import verify_commands
        return bullets([f"`{c}`" for c in verify_commands(self.cfg, extra)], "(no commands configured)")

    def owner_answers(self, task_id: str) -> str:
        import json
        rows = [d for d in self.state.decisions("APPLIED") if task_id in json.loads(d["blocks"] or "[]")]
        return bullets([f"{d['id']}: {d['question']} → {d['answer']}" for d in reversed(rows)])

    def unstick_prompt(self, task, error: str) -> str:
        phase = self.plan.phase_of(task)
        return render("unstick.md", task_id=task.id, task_title=task.title, description=task.description or task.title,
                      acceptance=bullets(task.acceptance_criteria), phase_goal=phase.goal or phase.title,
                      decisions=self.decisions(), error=(error or "(none)")[-6000:])

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
        import secrets
        tag = f"UNTRUSTED-{secrets.token_hex(6)}"  # unguessable, so the issue text can't fake the end of its block
        return render("triage.md", number=number, tag=tag, title=" ".join(str(title).split())[:200],
                      body=str(body or "(empty)")[:6000])

    def research_block(self, task) -> str:
        """The research notes for the task's topics: summaries written by a research session, never raw web text."""
        from .docs import research_path
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
        )

    def resume_prompt(self, task, attempt: int, last_error: str | None) -> str:
        """Retry inside the failed attempt's own session: the brief is already in its context, so only the failure."""
        return render("resume.md", task_id=task.id, task_title=task.title, verify_cmds=self.verify_cmds(task.verify),
                      retry_block=render("retry.md", attempt=attempt - 1, errors=(last_error or "(none)")[-6000:]))

    def fixer_prompt(self, errors: str, git_log: str) -> str:
        return render("fixer.md", decisions=self.decisions(), git_log=git_log,
                      errors=errors[-8000:], verify_cmds=self.verify_cmds())

    def auditor_prompt(self, kind: str, max_new: int) -> str:
        completion = ("Completion: is the product described in the goal actually complete and usable end to end? "
                      "Set complete=true ONLY if nothing important is missing." if kind == "completion"
                      else "Set complete=false unless the entire goal is already met.")
        return render("auditor.md", audit_kind=kind, plan_status=plan_status(self.plan, self.state),
                      decisions=self.decisions(), followups=self.followups(), completion_check=completion, max_new=max_new)

    def replanner_prompt(self) -> str:
        blocked = [f"{r['id']}: {(r['last_error'] or '')[:500]}" for r in self.state.tasks("blocked")]
        return render("replanner.md", plan_status=plan_status(self.plan, self.state, include_criteria=False),
                      blocked=bullets(blocked), decisions=self.decisions(), followups=self.followups())

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
