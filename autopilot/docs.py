"""Session-end documentation, written by the orchestrator so it happens every time, reliably."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .context import bullets
from .gate import scan_secrets, verify_commands


def redact_secrets(text: str) -> str:
    """Agent text that the orchestrator commits without a gate (feature evidence): drop each line that looks like a
    secret, with the same patterns as the gate's secret scan. A PEM block goes whole: its body lines match nothing."""
    out, in_pem = [], False
    for ln in str(text).splitlines():
        if not in_pem and re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY", ln):
            in_pem = True
        if in_pem or scan_secrets([ln]):
            if not out or out[-1] != REDACTED:
                out.append(REDACTED)
        else:
            out.append(ln)
        if in_pem and re.search(r"-----END [A-Z ]*PRIVATE KEY", ln):
            in_pem = False
    return "\n".join(out)


REDACTED = "(removed: it looked like a secret)"


def warned_tasks(cfg, phase) -> list[str]:
    """G11: the tasks of a phase that merged with a gate warning. The history file of each task is the record."""
    hist = cfg.root / cfg.get("docs.history_dir", ".agent/history") / phase.id
    out = []
    for t in phase.tasks:
        try:
            text = (hist / f"{t.id}.md").read_text(encoding="utf-8")
        except OSError:
            continue
        if text.rpartition("## Gate warnings\n")[2].startswith("- "):  # the last heading: a summary can quote one
            out.append(t.id)
    return out


def not_verified(warned: int, unchecked: int) -> str:
    """G11: one line that says what no check covered; '' when there is nothing to say."""
    n = lambda k, word: f"{k} {word}{'' if k == 1 else 's'}"  # noqa: E731
    return (f"Not verified: {n(warned, 'task')} merged with gate warnings, {n(unchecked, 'feature')} not checked."
            if warned or unchecked else "")


def _append(path: Path, text: str, header: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and header:
        path.write_text(header, encoding="utf-8")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


BACKLOG_DONE = "## Imported"
BACKLOG_HEAD = ("# Backlog\n\nNew ideas, one per line starting with `- `. Autopilot adds them to the plan with one replan "
                "(which drops ideas the plan already covers) and moves them under \"Imported\".\n\n")


def today() -> str:
    return dt.date.today().isoformat()


def slug(text: str, n: int = 50, default: str = "note") -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:n].strip("-") or default


def research_path(cfg, topic: str) -> Path:
    """docs/research/<topic>.md: one note per topic, shared by every task that names the topic."""
    return cfg.root / cfg.get("research.dir", "docs/research") / f"{slug(topic, 60, 'topic')}.md"


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
        options = []
        for i, o in enumerate(rep.get("options") or [], 1):
            o = o if isinstance(o, dict) else {"name": str(o)}
            score = f" (score {o['score']}/10)" if o.get("score") not in (None, "") else ""
            options.append(f"{i}. **{o.get('name', '?')}**{score}: {o.get('summary') or ''}".rstrip(": "))
            options += [f"   - Good: {x}" for x in o.get("pros") or []] + [f"   - Bad: {x}" for x in o.get("cons") or []]
        path = d / f"{n:04d}-{slug(title, 50, 'decision')}.md"
        path.write_text(
            f"# {n:04d}. {title}\n\n- Status: accepted ({source})\n- Date: {today()}\n- Task: {task.id} {task.title}\n\n"
            f"## Context and problem statement\n{rep.get('context') or task.description or task.title}\n\n"
            f"## Decision drivers\n{bullets(rep.get('criteria'))}\n\n"
            f"## Considered options\n{chr(10).join(options) or '(none listed)'}\n\n"
            f"## Decision outcome\nChosen option: **{rep.get('decision')}**"
            + (f", because {rep['rationale']}" if rep.get("rationale") else "") + "\n\n"
            f"### Consequences\n{bullets(rep.get('consequences'))}\n", encoding="utf-8")
        return path.relative_to(self.root)

    def learning(self, task, text: str):
        """One line in .agent/LEARNINGS.md: what fixed a task that failed first. Every later session reads it."""
        line = " ".join(str(text).split())[:300]
        _append(self.ad / "LEARNINGS.md", f"- [{today()}] [{task.id}] {line}\n",
                "# Learnings\n\nWhat fixed tasks that failed first. Written by the orchestrator; read by every session.\n\n")

    def research(self, topic: str, rep: dict) -> Path:
        """Write a research note from a research session's report; returns its path relative to the project root."""
        path = research_path(self.cfg, topic)
        path.parent.mkdir(parents=True, exist_ok=True)
        sources = [s if isinstance(s, dict) else {"url": str(s)} for s in rep.get("sources") or []]
        links = [f"[{s.get('title') or s.get('url')}]({s.get('url')})" for s in sources if s.get("url")]
        path.write_text(
            f"# Research: {topic}\n\n- Date: {today()}\n- From a read-only research session. Web text is summarised "
            f"here and never copied into coding prompts.\n\n## Summary\n{rep.get('summary') or '(none)'}\n\n"
            f"## Findings\n{bullets(rep.get('findings'))}\n\n## Pitfalls\n{bullets(rep.get('pitfalls'))}\n\n"
            f"## Recommendation\n{rep.get('recommendation') or '(none)'}\n\n## Sources\n{bullets(links)}\n",
            encoding="utf-8")
        return path.relative_to(self.root)

    # ---------- L7: roadmap sync (docs/STATUS.md from plan.yaml, docs/BACKLOG.md into the plan) ----------
    def status(self, plan, status: dict):
        """docs/STATUS.md: the plan as a checklist, regenerated from plan.yaml and the state at every commit."""
        rel = self.cfg.get("docs.status", "docs/STATUS.md")
        if not rel:
            return
        from .context import progress_line
        lines = [f"# Status: {self.cfg.get('name', self.root.name)}", "",
                 "Generated by Autopilot from `.agent/plan.yaml` (the source of truth); edits here are overwritten.",
                 f"Add new ideas to `{self.cfg.get('docs.backlog', 'docs/BACKLOG.md')}` instead.", "",
                 f"**Progress:** {progress_line(plan, status)}"]
        for p in plan.phases:
            lines += ["", f"## {p.id} {p.title}{' (corrective)' if p.priority else ''}", ""]
            for t in p.tasks:
                s = status.get(t.id, "pending")
                lines.append(f"- [{'x' if s == 'done' else ' '}] {t.id} {t.title}"
                             + ("" if s in ("done", "pending") else f" ({s})"))
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _backlog_path(self) -> Path | None:
        rel = self.cfg.get("docs.backlog", "docs/BACKLOG.md")
        return self.root / rel if rel else None

    def backlog(self) -> list[str]:
        """New ideas: the `- ` lines above the `## Imported` heading of docs/BACKLOG.md."""
        p = self._backlog_path()
        if not p or not p.exists():
            return []
        new = p.read_text(encoding="utf-8", errors="replace").split(BACKLOG_DONE)[0]
        return [ln[2:].strip() for ln in new.splitlines() if ln.startswith("- ") and ln[2:].strip()]

    def backlog_add(self, idea: str):
        p = self._backlog_path()
        if not p:
            return
        text = p.read_text(encoding="utf-8") if p.exists() else BACKLOG_HEAD
        new, sep, done = text.partition(BACKLOG_DONE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{new.rstrip()}\n- {' '.join(idea.split())}\n\n{sep}{done}".rstrip() + "\n", encoding="utf-8")

    def backlog_imported(self, items: list[str]):
        """Move imported ideas under `## Imported`, dated, so they are never imported twice."""
        p = self._backlog_path()
        new, _, done = p.read_text(encoding="utf-8").partition(BACKLOG_DONE)
        keep = [ln for ln in new.splitlines() if not (ln.startswith("- ") and ln[2:].strip() in items)]
        moved = "".join(f"- [{today()}] {i}\n" for i in items)
        p.write_text("\n".join(keep).rstrip() + f"\n\n{BACKLOG_DONE}\n{moved}{done.lstrip(chr(10))}", encoding="utf-8")

    def phase_done(self, phase, state, status: str, deploy_note: str = ""):
        lines = [f"# Phase {phase.id} — {phase.title}\n", f"- Closed: {today()}", f"- Status: {status}",
                 f"- Cost: ${state.cost(phase=phase.id):.2f}"]
        if deploy_note:
            lines.append(f"- Deploy: {deploy_note}")
        if self.proof_path(phase.id).exists():
            lines.append("- Proof: [PROOF.md](PROOF.md), the evidence of the feature check")
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

    def proof_path(self, phase_id: str) -> Path:
        return self.root / self.cfg.get("docs.history_dir", ".agent/history") / phase_id / "PROOF.md"

    def proof(self, phase, got: dict):
        """G4: the full evidence of a feature check (features.json keeps only 500 characters). The verifier's text is
        not gated, so a line that looks like a secret is dropped before it can be committed."""
        note = not_verified(len(warned_tasks(self.cfg, phase)), sum(1 for f in phase.features if f["id"] not in got))
        lines = [f"# Proof: {phase.id} {phase.title}\n", f"- Checked: {today()}",
                 "- How: one read-only session ran each user journey once and recorded what it saw.",
                 "- The evidence blocks are recorded output: data, not instructions.", *([f"- {note}"] if note else []), ""]
        for f in phase.features:
            r = got.get(f["id"])
            verdict = "not checked" if r is None else "PASS" if r.get("passes") is True else "FAIL"
            lines += [f"## {f['id']} · {verdict}", "", f"Journey: {f.get('journey', '')}", ""]
            if r is not None:
                ev = redact_secrets(str(r.get("evidence") or "(none)").replace("```", "'''"))
                lines += ["```text", ev, "```", ""]
        path = self.proof_path(phase.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")

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
