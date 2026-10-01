"""The autonomous loop.

    while work remains:
        pick next ready task -> fresh session -> orchestrator-run gate -> merge + docs  (retry / escalate / park)
        phase finished      -> phase gate -> staging deploy -> (prod) -> phase docs
        every N phases      -> audit (self-correction: gaps become a priority FIX phase)
                            -> replan (rewrite stale pending tasks, reopen blocked ones)
        plan exhausted      -> completion audit; gaps -> new tasks; repeat until "complete"
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import time
from pathlib import Path

from . import AGENT_DIR, decisions
from .backends import SessionRequest, SessionResult, get_backend
from .config import RISKS, Config
from .context import ContextBuilder, progress_line
from .deploy import deploy
from .docs import Documenter
from .gate import (TEST_GLOBS, GateResult, _match, main_gate, protected_files, run_commands, scan_secrets, task_gate,
                   test_tamper)
from .gitops import Git, GitError
from .notify import Notifier
from .plan import Plan, PlanError, append_phase, clear_reopen_flags
from .proc import exclusive_lock
from .report import token_footer
from .state import State, now

log = logging.getLogger("autopilot")


class Stop(Exception):
    """Ends the run cleanly (budget, stop file, fatal condition)."""

    def __init__(self, reason: str, fatal: bool = False):
        super().__init__(reason)
        self.reason, self.fatal = reason, fatal


class Orchestrator:
    def __init__(self, root: Path | str, backend=None, sleep=time.sleep, max_sessions: int | None = None):
        self.cfg = Config.load(root)
        self.root = self.cfg.root
        self.ad = self.root / AGENT_DIR
        self.state = State(self.ad / "state.db")
        self.git = Git(self.root)
        self.backend = backend or get_backend(self.cfg)
        self.sleep = sleep
        self.notify = Notifier(self.cfg, self.state)
        self.docs = Documenter(self.cfg)
        self.main = self.cfg.main_branch
        limit = max_sessions if max_sessions is not None else int(self.cfg.get("scheduling.max_sessions_per_run", 0))
        self.max_sessions = limit or None
        self.sessions_this_run = 0
        self.rate_limit_streak = 0
        self.run_info: dict = {}
        self.first_session = 0
        self.plan: Plan | None = None
        self.ctx: ContextBuilder | None = None
        self.main_red, self.main_checked, self.main_error = False, None, ""

    # ------------------------------------------------------------------ plan
    def reload_plan(self):
        self.plan = Plan.load(self.ad / "plan.yaml")
        sync = self.state.sync_plan(self.plan)
        if any(not self.plan.phase_of(i).priority for i in sync["added"]):
            self.state.set_meta("completion_rounds", 0)
        if sync["reopened"]:
            clear_reopen_flags(self.ad / "plan.yaml", sync["reopened"])
            self.plan = Plan.load(self.ad / "plan.yaml")
            self._commit_main("[autopilot] reopen " + ", ".join(sync["reopened"]))
        self.ctx = ContextBuilder(self.cfg, self.plan, self.state)
        return sync

    def _commit_main(self, message: str):
        if self.git.branch() != self.main:
            self.git.checkout_main(self.main)
        before = self.git.head()
        self.git.commit_all(message)
        if self.main_red and self.main_checked == before:  # our own docs/plan commits don't change the gate result
            self.main_checked = self.git.head()
        self._push()

    def _push(self):
        if self.cfg.get("git.push"):
            try:
                self.git.push(self.cfg.get("git.remote", "origin"), self.main)
            except Exception as exc:  # noqa: BLE001
                log.warning("push failed: %s", exc)

    # ------------------------------------------------------------------ run
    def run(self) -> str:
        self.ad.mkdir(exist_ok=True)
        try:
            with exclusive_lock(self.ad / "run.lock"):
                return self._run()
        except BlockingIOError:
            raise SystemExit("another autopilot run is active for this project")

    def _journal(self, **kw):
        """.agent/run.json: what this run is doing right now. A write failure never breaks the run."""
        try:
            self.run_info.update(kw, sessions=self.sessions_this_run, updated_at=now())
            tmp = self.ad / "run.json.tmp"
            tmp.write_text(json.dumps(self.run_info, indent=1), encoding="utf-8")
            os.replace(tmp, self.ad / "run.json")
        except Exception as exc:  # noqa: BLE001
            log.warning("run journal failed: %s", exc)

    def _footer(self) -> str:
        return token_footer(self.state, self.first_session)

    def _run(self) -> str:
        blocking = self.cfg.blocking_errors()
        if blocking:
            msg = "; ".join(blocking)
            self.notify.send("fatal", f"config: {msg}")
            return "fatal: config: " + msg
        for e in self.cfg.validate():
            if e not in blocking:
                log.warning("config: %s", e)
        self.first_session = self.state.next_session_id()
        self._journal(run_id=f"{dt.datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}", pid=os.getpid(), started_at=now(),
                      status="running", outcome="", current="starting", first_session=self.first_session)
        self._prepare_repo()
        try:
            self.reload_plan()
        except (PlanError, FileNotFoundError) as e:
            self.notify.send("fatal", f"plan.yaml invalid: {e}")
            self._journal(status="finished", outcome="fatal: invalid plan", current="")
            return "fatal: invalid plan"
        self.intake_answers()
        self.apply_answers()
        crashed = self.state.recover_crashed()
        if crashed:
            log.info("recovered crashed tasks: %s", crashed)
        self.notify.send("run_start", progress_line(self.plan, self.state.status_map()))

        outcome = "interrupted"
        try:
            setup = self.cfg.commands("setup")
            if setup:
                bad = [r for r in run_commands(setup, self.root, int(self.cfg.get("verify_timeout_sec", 1200)))
                       if r.rc != 0]
                if bad:
                    log.warning("setup command failed (continuing): %s\n%s", bad[0].cmd, bad[0].output[-800:])
            greenfield = not self.state.tasks("done")  # nothing built yet: checks can't pass on an empty repo
            if not greenfield and not self.ensure_main_green():
                self.start_main_red()
            self.close_finished_phases()
            outcome = self.loop()
        except Stop as s:
            outcome = s.reason
            self.notify.send("fatal" if s.fatal else "budget" if "budget" in s.reason else "run_done",
                             f"{s.reason}\n{self._footer()}")
            return outcome
        finally:
            self._journal(status="finished", outcome=outcome, current="")
            self.write_report()
        self.notify.send("run_done", f"{outcome} — {progress_line(self.plan, self.state.status_map())}, "
                                     f"total cost ${self.state.cost():.2f}\n{self._footer()}")
        return outcome

    def _prepare_repo(self):
        self.git.ensure_repo(self.main)
        br = self.git.branch()
        if br.startswith(("autopilot/", "autodev/")):          # crashed mid-session: throw away the partial work
            self.git.discard()
            self.git.checkout_main(self.main)
            self.git.delete_branch(br)
        elif br != self.main:
            self.git.checkout_main(self.main)
        if not self.git.is_clean():
            self.git.staged_files()
            found = scan_secrets(self.git.staged_added_lines())
            if not found:
                self.git.commit_all("[autopilot] snapshot of uncommitted changes found at run start")
            else:
                self.git.stash_all("autopilot: uncommitted changes found at run start")
                self.notify.send("stashed", f"{len(found)} possible secret(s) in the uncommitted changes found at run "
                                            "start; stashed instead of committed. Review them, then `git stash pop` to restore.")

    def loop(self) -> str:
        stall_replanned = False
        while True:
            self.check_stop()
            self.process_approvals()
            self.intake_answers()
            self.apply_answers()
            self.recheck_main()
            status = self.state.status_map()
            if self.main_red:  # only corrective (priority) work may run until main is green again
                view = {k: ("hold" if v == "pending" and k in self.plan.task_by_id
                            and not self.plan.phase_of(k).priority else v) for k, v in status.items()}
            else:
                view = status
            task = self.plan.next_ready(view, self.cfg.get("scheduling.phase_dependency", "soft"))
            if task:
                if self.execute_task(task):
                    stall_replanned = False
                    self.main_red = False  # its gate ran the full checks on top of main
                self.close_finished_phases()
                continue

            pending = [t for t in self.plan.all_tasks() if status.get(t.id) == "pending"]
            if pending and self.cfg.get("replan.enabled") and self.cfg.get("replan.on_stall") and not stall_replanned:
                stall_replanned = True
                self.notify.send("stalled", f"{len(pending)} tasks waiting on blocked work — replanning")
                self.replan("stall")
                continue
            if self.main_red:
                self.needs_you("main", "Checks on main are failing",
                               "The project's checks fail on the main branch and my repair attempts did not fix them. "
                               "How should I proceed?", why=self.main_error[-300:],
                               checked="The failing checks, a repair session and a corrective task",
                               suggestion="Tell me what changed, or what to fix first.")
            for r in self.state.tasks("blocked"):  # runs from before decisions existed
                if not self.state.open_decision(task_id=r["id"], kind="task"):
                    t = self.plan.task_by_id.get(r["id"])
                    self.needs_you("task", f"{r['id']} {t.title if t else ''}".strip(), self.GENERIC_QUESTION,
                                   task_id=r["id"], why=(r["last_error"] or "")[-300:])
            open_d = self.state.decisions("OPEN")
            if open_d:
                ids = sorted(d["id"] for d in open_d)
                path = self.cfg.get("needs_you.path", "docs/NEEDS-YOU.md")
                if not self.cfg.get("needs_you.wait", True):
                    return f"stalled: waiting on {len(ids)} decisions (see {path})"
                if self.state.get_meta("needs_you_digest") != ids:
                    self.state.set_meta("needs_you_digest", ids)
                    self.notify.send("needs_you", f"{len(ids)} decisions need you, see {path}: {', '.join(ids)}")
                self._journal(current="waiting for answers")
                self.sleep(float(self.cfg.get("needs_you.poll_minutes", 15)) * 60)
                continue
            if pending or self.main_red:
                return f"stalled: {len(pending)} tasks wait on skipped or blocked work"

            # plan exhausted -> is the app actually complete?
            if not self.cfg.get("audit.enabled") or not self.cfg.get("audit.completion_audit"):
                return "plan complete"
            rounds = self.state.get_meta("completion_rounds", 0)
            if rounds >= int(self.cfg.get("audit.max_completion_rounds", 2)):
                return f"plan complete (completion audit limit {rounds} reached)"
            self.state.set_meta("completion_rounds", rounds + 1)
            report = self.audit("completion")
            if report is None:
                return "plan complete (completion audit failed to produce a report)"
            if report.get("_new_phase"):
                continue
            return "app complete" if report.get("complete") else "plan complete (audit found no actionable gaps)"

    def process_approvals(self):
        d = self.ad / "approvals"
        for f in sorted(d.iterdir()) if d.is_dir() else []:
            row = self.state.phase(f.name)
            if row and row["prod_status"] == "awaiting_approval":
                self.deploy_prod(f.name, row["prod_ref"])
            f.unlink(missing_ok=True)

    # ------------------------------------------------------------------ guards
    def check_stop(self):
        if (self.ad / "STOP").exists():
            raise Stop("stopped by .agent/STOP file")
        if self.max_sessions and self.sessions_this_run >= self.max_sessions:
            raise Stop(f"session limit reached ({self.max_sessions})")
        total_cap = float(self.cfg.get("budget_usd.total", 0) or 0)
        if total_cap and self.state.cost() >= total_cap:
            raise Stop(f"total budget ${total_cap} reached")
        daily_cap = float(self.cfg.get("budget_usd.daily", 0) or 0)
        if daily_cap and self.state.cost(today=True) >= daily_cap:
            if not self.cfg.get("budget_usd.wait_for_next_day"):
                raise Stop(f"daily budget ${daily_cap} reached")
            tomorrow = dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(0, 5))
            secs = max(60, (tomorrow - dt.datetime.now()).total_seconds())
            self.notify.send("budget", f"daily budget ${daily_cap} reached — sleeping {secs / 3600:.1f}h")
            self.sleep(secs)

    def session_budget(self, task_id: str | None = None) -> float:
        b = self.cfg.get
        caps = [float(b("budget_usd.per_session", 8) or 8)]
        if task_id and b("budget_usd.per_task"):
            caps.append(float(b("budget_usd.per_task")) - self.state.cost(task_id=task_id))
        if b("budget_usd.daily"):
            caps.append(float(b("budget_usd.daily")) - self.state.cost(today=True))
        if b("budget_usd.total"):
            caps.append(float(b("budget_usd.total")) - self.state.cost())
        left = min(caps)
        if left < 0.01:
            raise Stop("budget exhausted")
        return left

    def backoff(self, res):
        if res.reset_at:  # the CLI said when the window reopens: sleep until then; not a streak, not an attempt
            secs = min(max(60, res.reset_at - time.time() + 120), 8 * 86400)
            wake = dt.datetime.fromtimestamp(time.time() + secs)
            when = wake.strftime("%H:%M") if wake.date() == dt.date.today() else wake.strftime("%Y-%m-%d %H:%M")
            self.notify.send("rate_limit", f"usage limit reached — sleeping until {when}")
            self.sleep(secs)
            return
        steps = self.cfg.get("retries.rate_limit_backoff_sec", [60, 300, 900, 1800, 3600])
        self.rate_limit_streak += 1
        if self.rate_limit_streak > 30:
            raise Stop("rate limited 30 times in a row", fatal=True)
        wait = steps[min(self.rate_limit_streak - 1, len(steps) - 1)]
        self.notify.send("rate_limit", f"rate limited — waiting {wait}s (streak {self.rate_limit_streak})")
        self.sleep(wait)

    # ------------------------------------------------------------------ sessions
    def session(self, kind: str, prompt: str, model: str, *, task_id=None, phase=None, attempt=1,
                read_only=False, label: str = "") -> SessionResult:
        self.check_stop()
        budget = self.session_budget(task_id)
        self._journal(current=label or " ".join(
            x for x in (kind, task_id, f"attempt {attempt}" if kind == "task" else "") if x))
        sid = self.state.start_session(kind, task_id, phase, attempt, model)
        self.sessions_this_run += 1
        log_path = self.ad / "logs" / "sessions" / f"{sid:05d}-{kind}-{task_id or 'main'}.log"
        log.info("session #%s %s %s model=%s attempt=%s", sid, kind, task_id or "", model, attempt)
        req = SessionRequest(prompt=prompt, model=model, cwd=str(self.root),
                             timeout_sec=int(self.cfg.get("agent.session_timeout_sec", 3600)),
                             budget_usd=budget, system_append=self.ctx.system_append(),
                             read_only=read_only, log_path=str(log_path))
        main_before, config_before = self.git.ref(self.main), self.git.config_text()
        try:
            res = self.backend.run(req)
        except Exception as exc:  # noqa: BLE001 — a backend crash is just a failed session
            res = SessionResult(ok=False, error=f"backend exception: {exc!r}")
        undone = self.git.guard_config(config_before)  # e.g. husky's core.hooksPath: harmless, but never kept
        if undone:
            log.warning("session %s changed git config: %s", sid, "; ".join(undone))
        if self.git.ref(self.main, check=False) != main_before:  # moved or deleted
            self.git.set_ref(self.main, main_before)
            self.notify.send("main_guard", f"session moved {self.main}; restored")
            res.ok, res.error = False, "session moved the main branch"
        self.state.end_session(sid, cost=res.cost, ok=res.ok, claude_session_id=res.session_id,
                               summary=str(res.report.get("summary", ""))[:2000], error=res.error,
                               log_path=str(log_path), usage=res.usage, num_turns=res.num_turns,
                               duration_ms=res.duration_ms)
        if task_id:
            self.state.set_task(task_id, cost=self.state.cost(task_id=task_id))
        if res.rate_limited:
            self.backoff(res)
        else:
            self.rate_limit_streak = 0
        return res

    def model_for(self, risk: str, attempt_index: int) -> str:
        ladder = self.cfg.get(f"models.ladder.{risk}") or self.cfg.get("models.ladder.medium")
        return ladder[min(attempt_index, len(ladder) - 1)]

    # ------------------------------------------------------------------ tasks
    def execute_task(self, task) -> bool:
        phase = self.plan.phase_of(task)
        row = self.state.task(task.id)
        attempts = int(row["attempts"] or 0)
        last_error = row["last_error"] if attempts else None
        max_attempts = int(self.cfg.get("retries.max_attempts_per_task", 3))
        branch = f"autopilot/{task.id}"
        self.state.set_task(task.id, status="running", started_at=now())
        extra, guidance, suggestion, fail_err = False, "", "", ""

        while attempts < max_attempts:
            per_task = float(self.cfg.get("budget_usd.per_task", 0) or 0)
            if per_task and self.state.cost(task_id=task.id) >= per_task:
                last_error = f"task budget ${per_task} exhausted. Last error: {last_error or ''}"
                break
            per_phase = float(self.cfg.get("budget_usd.per_phase", 0) or 0)
            if per_phase and self.state.cost(phase=phase.id) >= per_phase:
                self.state.set_task(task.id, status="pending")
                raise Stop(f"phase {phase.id} budget ${per_phase} reached")

            model = self.model_for(task.risk, attempts)
            base = self.git.start_branch(branch, self.main)
            prompt = self.ctx.task_prompt(task, attempts + 1, last_error, self.git.log_oneline())
            res = self.session("task", prompt, model, task_id=task.id, phase=phase.id, attempt=attempts + 1)
            if res.rate_limited:
                self.git.discard()
                continue  # not counted as an attempt
            attempts += 1
            self.state.set_task(task.id, attempts=attempts, model=model)
            self.git.normalize_after_session(branch, base)
            agent_blocked = False

            if not res.ok:
                last_error = f"agent session failed ({model}): {res.error}"
            elif str(res.report.get("status", "done")).lower() == "blocked":
                agent_blocked = True
                last_error = f"agent reported blocked ({model}): {res.report.get('blocker') or res.report.get('summary')}"
            else:
                gate = task_gate(self.cfg, self.git, task)
                problem = self._fix_problem(task, phase, res.report) if gate.ok else ""
                if problem:
                    last_error = problem
                elif gate.ok:
                    try:
                        self._complete_task(task, phase, res, model, attempts, gate, branch)
                        return True
                    except GitError as exc:
                        last_error = f"merge failed: {exc}"
                        self.git.discard()
                        self.git.checkout_main(self.main)
                else:
                    last_error = gate.report()
            log.info("task %s attempt %s failed: %s", task.id, attempts, (last_error or "")[:300])
            self.git.discard()
            fail_err = last_error or ""
            if (self.cfg.get("unstick.enabled", True) and not self.state.get_meta(f"unstick:{task.id}", False)
                    and (agent_blocked or attempts >= int(self.cfg.get("unstick.after_attempts", 2)))):
                kind, text, rep = self.unstick(task, phase, fail_err)
                if kind == "owner":
                    self._park(task, branch, attempts, fail_err)
                    self.needs_you("task", f"{task.id} {task.title}", str(rep.get("question") or self.GENERIC_QUESTION),
                                   task_id=task.id, checked=str(rep.get("checked") or text),
                                   why=str(rep.get("why") or fail_err[-300:]), suggestion=str(rep.get("suggestion") or ""))
                    return False
                if kind != "skip":
                    extra, guidance, suggestion = True, text, str(rep.get("suggestion") or "")
                    max_attempts = attempts + 1
                    label = "DIAGNOSIS" if kind == "technical" else "DECISION"
                    last_error = f"{fail_err}\n\n{label} from a separate review session (apply it):\n{text}"

        self._park(task, branch, attempts, last_error or "")
        if extra:
            self.needs_you("task", f"{task.id} {task.title}",
                           "It still fails after a diagnosis and a retry. How should we proceed?", task_id=task.id,
                           checked=guidance, why=fail_err[-300:], suggestion=suggestion)
        else:
            self.needs_you("task", f"{task.id} {task.title}", self.GENERIC_QUESTION, task_id=task.id,
                           checked=f"{attempts} attempts by the agent", why=(fail_err or last_error or "")[-300:])
        return False

    RCA_FIELDS = ("symptom", "root_cause", "fix", "prevention")

    def _fix_problem(self, task, phase, report: dict) -> str:
        """Extra gate for corrective tasks: a complete RCA and, for bugs, a regression test."""
        if not phase.priority:
            return ""
        rca = report.get("rca") if isinstance(report.get("rca"), dict) else {}
        missing = [k for k in self.RCA_FIELDS if not str(rca.get(k) or "").strip()]
        if missing:
            return (f"RCA incomplete: missing {', '.join(missing)}. "
                    "Corrective tasks must report symptom, root_cause, fix and prevention.")
        globs = self.cfg.get("gate.test_globs") or TEST_GLOBS
        if (task.description or "").lstrip().lower().startswith(("[bug]", "[regression]")) \
                and not any(_match(f, globs) for f in self.git.staged_files()):
            return "a bug fix must add or update a regression test"
        return ""

    GENERIC_QUESTION = "I could not finish this feature and cannot decide how to proceed on my own. What should I do?"

    def _park(self, task, branch, attempts, error):
        self.git.checkout_main(self.main)
        self.git.delete_branch(branch)
        self.state.set_task(task.id, status="blocked", last_error=error[-6000:], finished_at=now())
        self.notify.send("task_blocked", f"{task.id} {task.title} parked after {attempts} attempts: {error[:400]}")

    def unstick(self, task, phase, error: str) -> tuple[str, str, dict]:
        """One read-only diagnosis session. -> (technical|spec|owner|skip, guidance text, report)."""
        self.git.start_branch("autopilot/unstick", self.main)
        try:
            res = self.session("unstick", self.ctx.unstick_prompt(task, error), self.cfg.get("models.unstick", "sonnet"),
                               task_id=task.id, phase=phase.id, read_only=True)
        finally:  # read-only: drop anything it touched
            self.git.discard()
            self.git.checkout_main(self.main)
            self.git.delete_branch("autopilot/unstick")
        if res.rate_limited:
            return "skip", "", {}
        self.state.set_meta(f"unstick:{task.id}", True)
        rep = res.report if res.ok and isinstance(res.report, dict) else {}
        cls = str(rep.get("class", "")).lower()
        diagnosis, decision = str(rep.get("diagnosis") or "").strip(), str(rep.get("decision") or "").strip()
        if cls == "technical" and diagnosis:
            return "technical", diagnosis, rep
        if cls == "spec" and decision:
            options = "; ".join(str(o) for o in (rep.get("options_considered") or []))
            self._record_decision(f"[{task.id}] DECISION (auto): {decision} (options considered: {options or 'n/a'})")
            self._commit_main(f"[autopilot] auto decision for {task.id}")
            return "spec", decision, rep
        return "owner", diagnosis or decision, rep

    # ------------------------------------------------------------------ owner decisions (docs/NEEDS-YOU.md)
    def _needs_path(self) -> Path:
        return self.root / self.cfg.get("needs_you.path", "docs/NEEDS-YOU.md")

    def _write_needs_you(self):
        p = self._needs_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(decisions.render(self.state), encoding="utf-8")

    def _record_decision(self, line: str):
        p = self.ad / "DECISIONS.md"
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        sep = "" if not text or text.endswith("\n") else "\n"
        p.write_text(f"{text}{sep}- [{dt.date.today().isoformat()}] {line}\n", encoding="utf-8")

    def _dependants(self, tid: str) -> list[str]:
        out, grew = [tid], True
        while grew:
            grew = False
            for t in self.plan.all_tasks():
                if t.id not in out and any(d in out for d in t.depends_on):
                    out.append(t.id)
                    grew = True
        return out

    def needs_you(self, kind: str, title: str, question: str, *, task_id=None, phase_id=None,
                  checked: str = "", why: str = "", suggestion: str = "") -> str:
        fields = dict(title=title, question=question, checked=checked, why=why, suggestion=suggestion,
                      blocks=json.dumps(self._dependants(task_id) if task_id else []))
        cur = self.state.open_decision(task_id=task_id, kind=kind, phase_id=phase_id)
        if cur and all(cur[k] == v for k, v in fields.items()):
            return cur["id"]
        if cur:
            did = cur["id"]
            self.state.set_decision(did, **fields)
        else:
            did = self.state.add_decision(kind=kind, task_id=task_id, phase_id=phase_id, **fields)
        self._write_needs_you()
        self._commit_main(f"[autopilot] needs-you {did}: {title}")
        self.notify.send("needs_you", f"{did} {title}: {question}")
        return did

    def intake_answers(self):
        p = self._needs_path()
        if p.exists():
            for did, text in decisions.parse_answers(p.read_text(encoding="utf-8", errors="replace")).items():
                self.state.answer_decision(did, text)

    def apply_answers(self):
        for d in reversed(self.state.decisions("ANSWERED")):
            self._record_decision(f"[{d['id']}] {' '.join((d['question'] or '').split())} → {d['answer']}")
            if d["kind"] == "task":
                for tid in json.loads(d["blocks"] or "[]"):
                    row = self.state.task(tid)
                    if row and row["status"] == "blocked":
                        self.state.set_task(tid, status="pending", attempts=0, last_error=None, note=f"answered {d['id']}")
                    self.state.set_meta(f"unstick:{tid}", False)
            elif d["kind"] == "phase" and d["phase_id"]:
                self.state.set_phase(d["phase_id"], status="open")
            elif d["kind"] == "main":
                self.main_checked = None
            self.state.set_decision(d["id"], status="APPLIED")
            self._write_needs_you()
            self._commit_main(f"[autopilot] apply answer {d['id']}")

    # ------------------------------------------------------------------ main branch red
    def start_main_red(self):
        head = self.git.head()
        self.main_red, self.main_checked = True, head
        self.notify.send("main_red", f"checks on {self.main} fail and the fixer could not repair them; "
                                     "building a corrective phase first")
        self.add_corrective_phase([{
            "title": "Repair the failing checks on main", "risk": "high",
            "description": "The project's checks fail on the main branch. Find the root cause and fix it with the "
                           f"smallest correct change.\n\nFailing checks:\n{self.main_error[-3000:]}",
            "acceptance_criteria": ["All verify commands pass on the main branch"]}],
            "main branch red", once_key=f"mainred-{head[:12]}")

    def recheck_main(self):
        if not self.main_red:
            return
        head = self.git.head()
        if head == self.main_checked:
            return
        self.main_checked = head
        if main_gate(self.cfg).ok:
            self.main_red = False
            self.notify.send("main_fixed", "checks on main pass again")

    def _complete_task(self, task, phase, res, model, attempt, gate: GateResult, branch):
        files = self.git.staged_files()
        status = dict(self.state.status_map(), **{task.id: "done"})
        nxt = self.plan.next_ready(status, self.cfg.get("scheduling.phase_dependency", "soft"))
        cost = self.state.cost(task_id=task.id)
        self.docs.task_done(task, phase, res.report, model=model, attempt=attempt, cost=cost,
                            gate_warnings=gate.warnings, files=files, next_task=nxt.id if nxt else None)
        summary = str(res.report.get("summary", "")).strip()
        if phase.priority:
            self.docs.rca(task.id, task.title, res.report.get("rca"))
        self.git.commit_all(f"[autopilot] {task.id}: {task.title}\n\n{summary}\n\nmodel: {model}, attempt {attempt}")
        sha = self.git.merge(branch, self.main, f"[autopilot] merge {task.id}: {task.title}")
        self.git.delete_branch(branch)
        self._push()
        self.state.set_task(task.id, status="done", commit_sha=sha, last_error=None, finished_at=now())
        log.info("task %s done (%s, $%.2f)", task.id, model, cost)

    # ------------------------------------------------------------------ gated repair
    def _gated_change(self, kind: str, branch: str, prompt: str, model: str, message: str,
                      phase_checks: bool = False) -> tuple[bool, str]:
        base = self.git.start_branch(branch, self.main)
        res = self.session(kind, prompt, model)
        self.git.normalize_after_session(branch, base)
        if not res.ok:
            err = f"session failed: {res.error}"
        else:
            files = self.git.staged_files()
            problems = [f"modified protected file {f}" for f in files if f in protected_files(self.cfg)]
            problems += scan_secrets(self.git.staged_added_lines())
            problems += test_tamper(self.cfg, self.git)
            if problems:
                err = "\n".join(problems)
            else:
                gate = main_gate(self.cfg, phase=phase_checks)
                if gate.ok:
                    summary = str(res.report.get("summary", ""))
                    if kind == "fixer":
                        rca = res.report.get("rca") if isinstance(res.report.get("rca"), dict) else {}
                        self.docs.rca("fixer", "repair main branch", {"root_cause": res.report.get("root_cause"), **rca})
                    self.git.commit_all(f"{message}\n\n{summary}")
                    self.git.merge(branch, self.main, f"{message} (merge)")
                    self.git.delete_branch(branch)
                    self._push()
                    return True, summary
                err = gate.report()
        self.git.discard()
        self.git.checkout_main(self.main)
        self.git.delete_branch(branch)
        return False, err

    def ensure_main_green(self, phase_checks: bool = False) -> bool:
        gate = main_gate(self.cfg, phase=phase_checks)
        if gate.ok:
            return True
        errors = gate.report()
        self.notify.send("main_red", f"verification failing on {self.main} — starting fixer")
        for i in range(int(self.cfg.get("retries.max_fixer_attempts", 3))):
            prompt = self.ctx.fixer_prompt(errors, self.git.log_oneline())
            ok, detail = self._gated_change("fixer", "autopilot/fixer", prompt,
                                            self.cfg.get("models.fixer", "opus"),
                                            "[autopilot] fix: repair main branch", phase_checks)
            if ok:
                self.notify.send("main_fixed", detail[:300])
                return True
            errors = detail
        self.main_error = errors
        return False

    # ------------------------------------------------------------------ phases
    def close_finished_phases(self):
        for p in self.plan.phases:
            row = self.state.phase(p.id)
            statuses = [self.state.status_map().get(t.id, "pending") for t in p.tasks]
            active = any(s in ("pending", "running") for s in statuses)
            if row and row["status"] == "failed":  # waits for the owner (a `phase` decision reopens it)
                continue
            if row and row["status"] in ("done", "partial"):
                if not active:
                    continue
                self.state.set_phase(p.id, status="open")  # reopened by replan / unblock: closes again later
            if active:
                continue
            self.close_phase(p, "done" if all(s in ("done", "skipped") for s in statuses) else "partial")

    def close_phase(self, phase, status: str):
        log.info("closing phase %s (%s)", phase.id, status)
        gate = main_gate(self.cfg, phase=True)
        if not gate.ok:
            err = gate.report()
            if not phase.priority and self.add_corrective_phase([{  # corrective phases never spawn more of them
                    "title": f"Fix the failing checks for {phase.id}", "risk": "high",
                    "description": f"The checks that close phase {phase.id} fail. Find the root cause and fix it.\n\n"
                                   f"Failing checks:\n{err[-3000:]}",
                    "acceptance_criteria": ["All verify commands pass, including the phase checks"],
                    "verify": self.cfg.commands("phase_verify")}],
                    f"phase gate {phase.id}", once_key=f"phasefix-{phase.id}"):
                return  # phase stays open; it closes when its corrective phase is done
            self.state.set_phase(phase.id, status="failed")
            self.needs_you("phase", f"{phase.id} checks keep failing",
                           f"The checks that close phase {phase.id} still fail after a repair attempt. How should we proceed?",
                           phase_id=phase.id, checked="The failing checks and one corrective phase", why=err[-300:],
                           suggestion="Tell me what to change, or whether to skip these checks.")
            return
        note = self.deploy_phase(phase) if phase.deploy and any(
            self.state.task(t.id)["status"] == "done" for t in phase.tasks) else ""
        self.state.set_phase(phase.id, status=status, completed_at=now())
        self.docs.phase_done(phase, self.state, status, note)
        self._commit_main(f"[autopilot] close phase {phase.id} ({status})")
        self.notify.send("phase_done", f"{phase.id} {phase.title}: {status}. "
                                       f"{progress_line(self.plan, self.state.status_map())}. {note}")
        if phase.priority:  # corrective phases don't count toward review cadence
            return
        closed = self.state.phases_closed()
        audit_n = int(self.cfg.get("audit.every_n_phases", 0) or 0)
        replan_n = int(self.cfg.get("replan.every_n_phases", 0) or 0)
        if self.cfg.get("audit.enabled") and audit_n and closed % audit_n == 0:
            self.audit("periodic", phase.id)
        if self.cfg.get("replan.enabled") and replan_n and closed % replan_n == 0:
            self.replan(f"after {phase.id}")

    def deploy_phase(self, phase) -> str:
        notes = []
        ref = self.git.head()
        staging_ok = True
        if self.cfg.get("deploy.staging.enabled"):
            res = deploy(self.cfg, "staging", ref, phase.id, self.state.last_staging_ref(exclude=phase.id))
            staging_ok = res.ok
            if res.ok:
                self.git.tag(f"autopilot-staging-{phase.id}", ref)
                self.state.set_phase(phase.id, staging_ref=ref)
                self.notify.send("deploy_ok", f"staging {phase.id} {ref[:10]}")
            else:
                self.notify.send("deploy_failed", f"staging {phase.id}: {res.detail[:600]}")
                if f"deployfix-{phase.id}" in self.state.get_meta("once_keys", []):
                    log.warning("staging failed again after its corrective phase: %s", phase.id)
                    self.notify.send("deploy_failed", f"{phase.id}: staging failed again after its corrective phase")
                    self.needs_you("deploy", f"{phase.id} staging deploy keeps failing",
                                   "The staging deployment still fails after a repair attempt. How should we proceed?",
                                   phase_id=phase.id, checked="The deploy command and one corrective phase",
                                   why=res.detail[-300:], suggestion="Check the deploy command, credentials and server.")
                self.add_corrective_phase([{
                    "title": f"Fix staging deployment failure after {phase.id}", "risk": "high",
                    "description": "The staging deployment failed. Diagnose and fix the application-side cause "
                                   f"(build, config, migrations, startup).\n\nFailure:\n{res.detail[-3000:]}",
                    "acceptance_criteria": ["The deploy command succeeds", "The health check passes",
                                            "The root cause is covered by a test or a documented check"],
                }], f"deploy failure {phase.id}", once_key=f"deployfix-{phase.id}")
            notes.append(res.detail.splitlines()[0])
        if self.cfg.get("deploy.prod.enabled") and staging_ok:
            auto = self.cfg.get("deploy.prod.auto") and RISKS.index(phase.max_risk) <= RISKS.index(
                self.cfg.get("deploy.prod.max_auto_risk", "medium"))
            if auto:
                notes.append(self.deploy_prod(phase.id, ref))
            else:
                self.state.set_phase(phase.id, prod_status="awaiting_approval", prod_ref=ref)
                self.notify.send("approval_needed", f"{phase.id} ready for prod: run `autopilot approve {phase.id}`")
                notes.append("prod awaiting approval")
        return "; ".join(notes)

    def deploy_prod(self, phase_id: str, ref: str) -> str:
        res = deploy(self.cfg, "prod", ref, phase_id, self.state.last_prod_ref())
        self.state.set_phase(phase_id, prod_status="deployed" if res.ok else "failed", prod_ref=ref)
        if res.ok:
            self.git.tag(f"autopilot-prod-{phase_id}", ref)
        self.notify.send("deploy_ok" if res.ok else "deploy_failed", f"prod {phase_id}: {res.detail[:600]}")
        return res.detail.splitlines()[0]

    # ------------------------------------------------------------------ self-correction
    def add_corrective_phase(self, gaps: list[dict], label: str, once_key: str | None = None) -> str | None:
        if once_key:
            done = self.state.get_meta("once_keys", [])
            if once_key in done:
                return None
            self.state.set_meta("once_keys", done + [once_key])
        known = [int(m.group(1)) for k in self.plan.phase_by_id if (m := re.fullmatch(r"FIX(\d+)", k))]
        n = max(int(self.state.get_meta("fix_counter", 0)), *known, 0) + 1
        pid = f"FIX{n:03d}"
        tasks = []
        for i, g in enumerate(gaps, 1):
            risk = str(g.get("risk", "medium")).lower()
            desc = str(g.get("description", "")).strip()
            if g.get("related_task"):
                desc += f"\n\nRelated task: {g['related_task']} (see .agent/history)."
            if g.get("kind"):
                desc = f"[{g['kind']}] {desc}"
            tasks.append({
                "id": f"{pid}-T{i:02d}", "title": str(g.get("title") or f"Corrective task {i}")[:150],
                "risk": risk if risk in RISKS else "medium", "description": desc,
                "acceptance_criteria": [str(x) for x in (g.get("acceptance_criteria") or [])] or
                                       ["The problem described is fixed and covered by an automated test"],
                "files_in_scope": [str(x) for x in (g.get("files_in_scope") or [])],
                **({"verify": [str(x) for x in g["verify"]]} if g.get("verify") else {}),
            })
        if not tasks:
            return None
        phase = {"id": pid, "title": f"Corrective: {label}", "goal": f"Self-correction from {label}.",
                 "depends_on": [], "priority": True, "tasks": tasks}
        try:
            append_phase(self.ad / "plan.yaml", phase)
        except PlanError as e:
            log.warning("could not add corrective phase: %s", e)
            return None
        self.state.set_meta("fix_counter", n)
        self._commit_main(f"[autopilot] add corrective phase {pid} ({label})")
        self.reload_plan()
        return pid

    def audit(self, kind: str, phase_id: str | None = None) -> dict | None:
        """Read-only review of the whole implementation; actionable gaps become a priority FIX phase."""
        max_new = int(self.cfg.get("audit.max_new_tasks", 15))
        self.git.start_branch("autopilot/audit", self.main)
        try:
            res = self.session("audit", self.ctx.auditor_prompt(kind, max_new), self.cfg.get("models.auditor", "opus"),
                               phase=phase_id, read_only=True, label=f"audit {kind}")
        finally:  # read-only: drop anything it touched
            self.git.discard()
            self.git.checkout_main(self.main)
            self.git.delete_branch("autopilot/audit")
        if not res.ok or not res.report:
            log.warning("audit produced no usable report: %s", res.error[:300])
            return None
        report = dict(res.report)
        gaps = [g for g in (report.get("gaps") or []) if isinstance(g, dict) and g.get("title")][:max_new]
        new_phase = self.add_corrective_phase(gaps, f"{kind} audit") if gaps else None
        report["_new_phase"] = new_phase
        self.docs.audit(kind, report, phase_id, new_phase)
        self.docs.consume_followups()
        self._commit_main(f"[autopilot] {kind} audit: {len(gaps)} gaps")
        self.notify.send("audit", f"{kind} audit: {report.get('completion_pct', '?')}% complete, "
                                  f"{len(gaps)} corrective tasks ({new_phase or 'none'})")
        return report

    def replan(self, reason: str) -> bool:
        """Let a session rewrite the remaining plan + BRAIN.md; validated before it is accepted."""
        plan_path, brain_path = self.ad / "plan.yaml", self.ad / "BRAIN.md"
        before_plan = plan_path.read_text(encoding="utf-8")
        self.git.start_branch("autopilot/replan", self.main)
        try:
            res = self.session("replan", self.ctx.replanner_prompt(), self.cfg.get("models.replanner", "opus"))
            new_plan = plan_path.read_text(encoding="utf-8")
            new_brain = brain_path.read_text(encoding="utf-8") if brain_path.exists() else None
        finally:  # drop everything, then re-apply only the two allowed files on main
            self.git.discard()
            self.git.checkout_main(self.main)
            self.git.delete_branch("autopilot/replan")
        if not res.ok:
            return False
        done_ids = {r["id"] for r in self.state.tasks("done")}
        try:
            plan_path.write_text(new_plan, encoding="utf-8")
            candidate = Plan.load(plan_path)
            missing = done_ids - set(candidate.task_by_id)
            if missing:
                raise PlanError([f"replan removed completed tasks: {sorted(missing)}"])
            def frozen(t):  # the whole definition of a done task, except its position in the plan
                return {k: v for k, v in vars(t).items() if k not in ("order", "reopen")}
            changed = sorted(i for i in done_ids if i in self.plan.task_by_id
                             and frozen(self.plan.task_by_id[i]) != frozen(candidate.task_by_id[i]))
            if changed:
                raise PlanError([f"replan changed the definition of completed tasks: {changed}"])
        except PlanError as e:
            plan_path.write_text(before_plan, encoding="utf-8")
            log.warning("replan rejected: %s", e)
            self.notify.send("replan_rejected", str(e)[:400])
            return False
        if new_brain is not None:
            brain_path.write_text(new_brain, encoding="utf-8")
        self.docs.consume_followups()
        self._commit_main(f"[autopilot] replan ({reason}): {str(res.report.get('summary', ''))[:200]}")
        sync = self.reload_plan()
        self.notify.send("replan", f"{reason}: added {len(sync['added'])}, removed {len(sync['removed'])}, "
                                   f"reopened {len(sync['reopened'])}")
        return True

    # ------------------------------------------------------------------ reporting
    def write_report(self):
        try:
            from .report import build_report
            (self.ad / "REPORT.md").write_text(build_report(self.cfg, self.plan, self.state), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("report failed: %s", exc)
