"""Session-end documentation, written by the orchestrator so it happens every time, reliably."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .context import bullets
from .gate import verify_commands


def _append(path: Path, text: str, header: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and header:
        path.write_text(header, encoding="utf-8")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def today() -> str:
    return dt.date.today().isoformat()


class Documenter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ad = cfg.agent_dir
        self.root = cfg.root

    def task_done(self, task, phase, report: dict, *, model: str, attempt: int, cost: float,
                  gate_warnings: list[str], files: list[str], next_task: str | None):
        summary = report.get("summary") or f"Implemented {task.title}."
        decisions = report.get("decisions") or []
        followups = report.get("followups") or []

        # 1. per-task history record (committed; the long-term audit trail)
        hist = self.root / self.cfg.get("docs.history_dir", ".agent/history") / phase.id / f"{task.id}.md"
        hist.parent.mkdir(parents=True, exist_ok=True)
        hist.write_text(
            f"# {task.id} — {task.title}\n\n- Date: {today()}\n- Model: {model} (attempt {attempt})\n"
            f"- Cost: ${cost:.2f}\n- Risk: {task.risk}\n\n## Summary\n{summary}\n\n"
            f"## Acceptance criteria\n{bullets(task.acceptance_criteria)}\n\n"
            f"## Files changed\n{bullets(files)}\n\n## Tests added\n{bullets(report.get('tests_added'))}\n\n"
            f"## Docs updated\n{bullets(report.get('docs_updated'))}\n\n## Decisions\n{bullets(decisions)}\n\n"
            f"## Follow-ups\n{bullets(followups)}\n\n## Gate warnings\n{bullets(gate_warnings)}\n\n"
            f"## How to verify\n{bullets([f'`{c}`' for c in verify_commands(self.cfg, task.verify)], '(no commands configured)')}\n\n"
            f"## Rollback\nRevert the merge commit `[autopilot] merge {task.id}`: `git revert -m 1 <sha>`\n",
            encoding="utf-8")

        # 2. decision log
        if decisions:
            _append(self.ad / "DECISIONS.md", "".join(f"- [{today()}] [{task.id}] {d}\n" for d in decisions))

        # 3. follow-ups queue (read by auditor / replanner)
        if followups:
            _append(self.ad / "FOLLOWUPS.md", "".join(f"- [{task.id}] {f}\n" for f in followups),
                    "# Follow-ups\n\nReported by sessions; consumed by the auditor and replanner.\n\n")

        # 4. changelog
        cl = self.cfg.get("docs.changelog", "CHANGELOG.md")
        if cl:
            _append(self.root / cl, f"- {today()} **{task.id}** {task.title} — {summary.splitlines()[0][:200]}\n",
                    "# Changelog\n\n")

        # 5. handoff for the next session
        (self.ad / "HANDOFF.md").write_text(
            f"# Handoff\n\nLast completed: **{task.id} — {task.title}** ({today()})\n\n{summary}\n\n"
            f"Files: {', '.join(files[:25]) or '(none)'}\n\nFollow-ups noted:\n{bullets(followups)}\n\n"
            f"Next planned task: {next_task or '(none)'}\n", encoding="utf-8")

    def rca(self, ident: str, title: str, rca: dict):
        """Append a root-cause entry to the RCA log; missing fields are marked, never rejected."""
        rca = rca if isinstance(rca, dict) else {}
        f = lambda k: " ".join(str(rca.get(k) or "").split()) or "(not reported)"  # noqa: E731
        _append(self.root / self.cfg.get("docs.rca", "docs/RCA.md"),
                f"## {today()} · {ident} {title}\n- Symptom: {f('symptom')}\n- Root cause: {f('root_cause')}\n"
                f"- Fix: {f('fix')}\n- Prevention: {f('prevention')}\n\n", "# RCA log\n\n")

    def adr(self, task, rep: dict, source: str) -> Path:
        """Write an ADR (MADR layout) as docs/adr/NNNN-title.md and return its path relative to the project root."""
        d = self.root / self.cfg.get("docs.adr_dir", "docs/adr")
        d.mkdir(parents=True, exist_ok=True)
        n = max([int(m[1]) for f in d.glob("*.md") if (m := re.match(r"(\d{4})-", f.name))] + [0]) + 1
        title = " ".join(str(rep.get("title") or task.title).split())[:120]
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "decision"
        options = []
        for i, o in enumerate(rep.get("options") or [], 1):
            o = o if isinstance(o, dict) else {"name": str(o)}
            score = f" (score {o['score']}/10)" if o.get("score") not in (None, "") else ""
            options.append(f"{i}. **{o.get('name', '?')}**{score}: {o.get('summary') or ''}".rstrip(": "))
            options += [f"   - Good: {x}" for x in o.get("pros") or []] + [f"   - Bad: {x}" for x in o.get("cons") or []]
        path = d / f"{n:04d}-{slug}.md"
        path.write_text(
            f"# {n:04d}. {title}\n\n- Status: accepted ({source})\n- Date: {today()}\n- Task: {task.id} {task.title}\n\n"
            f"## Context and problem statement\n{rep.get('context') or task.description or task.title}\n\n"
            f"## Decision drivers\n{bullets(rep.get('criteria'))}\n\n"
            f"## Considered options\n{chr(10).join(options) or '(none listed)'}\n\n"
            f"## Decision outcome\nChosen option: **{rep.get('decision')}**"
            + (f", because {rep['rationale']}" if rep.get("rationale") else "") + "\n\n"
            f"### Consequences\n{bullets(rep.get('consequences'))}\n", encoding="utf-8")
        return path.relative_to(self.root)

    def phase_done(self, phase, state, status: str, deploy_note: str = ""):
        lines = [f"# Phase {phase.id} — {phase.title}\n", f"- Closed: {today()}", f"- Status: {status}",
                 f"- Cost: ${state.cost(phase=phase.id):.2f}"]
        if deploy_note:
            lines.append(f"- Deploy: {deploy_note}")
        lines += ["", "## Goal", phase.goal or "(none)", "", "## Tasks"]
        for t in phase.tasks:
            row = state.task(t.id)
            s = row["status"] if row else "pending"
            lines.append(f"- [{s}] {t.id} {t.title}")
            if s == "blocked" and row and row["last_error"]:
                lines.append(f"  - reason: {row['last_error'][:300].replace(chr(10), ' ')}")
        path = self.root / self.cfg.get("docs.history_dir", ".agent/history") / phase.id / "PHASE.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def audit(self, kind: str, report: dict, phase_id: str | None, new_phase: str | None):
        path = self.ad / "audits" / f"{dt.datetime.now():%Y%m%d-%H%M%S-%f}-{kind}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        gaps = report.get("gaps") or []
        path.write_text(
            f"# Audit ({kind}) {today()}\n\n- After phase: {phase_id or '-'}\n"
            f"- Complete: {report.get('complete')}  ({report.get('completion_pct', '?')}%)\n"
            f"- Corrective phase: {new_phase or '(none)'}\n\n## Summary\n{report.get('summary', '')}\n\n## Gaps\n"
            + "\n".join(f"- **{g.get('title')}** [{g.get('kind')}/{g.get('risk')}] {g.get('description', '')}"
                        for g in gaps) + "\n", encoding="utf-8")
        return path

    def consume_followups(self):
        f = self.ad / "FOLLOWUPS.md"
        if f.exists():
            archive = self.ad / "audits" / "followups-consumed.md"
            _append(archive, f"\n## {today()}\n" + f.read_text(encoding="utf-8"))
            f.unlink()
