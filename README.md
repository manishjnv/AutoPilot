# Autopilot: autonomous development agent

Autopilot runs **hundreds of Claude Code sessions back-to-back, without you**, to take any project from a phased plan
to a finished, deployed app. Each session implements one task. A plain Python orchestrator owns everything else:
the plan, state, git, verification, documentation, deployment, self-review and self-correction.

> Formerly **AutoDev**. Existing projects keep working: the `.agent/` folder is unchanged and the old `AUTODEV_*` environment variables are still read.

```
autopilot init            # adds a .agent/ contract to any repo (stack auto-detected)
autopilot onboard --plan-doc docs/PLAN.md   # AI converts your plan into phases/tasks + BRAIN.md
autopilot run             # runs until the app is complete
```

## How it works

```
┌─────────────────────────── orchestrator loop (deterministic Python) ───────────────────────────┐
│ next ready task (deps + phase order, corrective phases first)                                  │
│   └─ fresh session on branch autopilot/<task> ← context pack: BRAIN + DECISIONS + HANDOFF + spec│
│        └─ gate run by the orchestrator: build · lint · typecheck · test · secret scan · scope  │
│             pass → docs (history, decisions, changelog, handoff) → commit → merge to main       │
│             fail → reset, retry with the error output on the next model in the ladder          │
│                    (same model → the retry resumes the failed session: context + cache kept)   │
│             N fails → park as BLOCKED, move on (never stop the run for one task)               │
│ phase finished → phase gate (+phase_verify) → staging deploy → health/smoke → rollback on fail │
│                  → prod (auto for low-risk phases, else queued for `autopilot approve`)         │
│ every N phases → AUDIT: read-only review of the whole codebase vs the plan                     │
│                  → gaps/bugs/regressions become a priority FIX phase  (self-correction)         │
│                → REPLAN: rewrite stale pending tasks, reopen blocked ones, refresh BRAIN.md     │
│ plan exhausted → COMPLETION AUDIT: "is the app actually done?" gaps → new tasks → loop again    │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Concern | How Autopilot handles it |
|---|---|
| Context rot over 100+ sessions | One task per fresh session. Memory lives in files: `BRAIN.md`, `DECISIONS.md`, `HANDOFF.md`, `history/` |
| "Done" that isn't done | The orchestrator runs the checks itself; empty diffs, protected-file edits and secrets all fail |
| One failure freezing the run | Retry, then escalate the model, then park as blocked; independent work continues (`phase_dependency: soft`) |
| Main branch breaks | A fixer session repairs it (gated) before any more work runs |
| Risky design choices made blind | High/critical tasks first get a read-only decide session that scores 2-3 options; the choice is written as an ADR in `docs/adr/` and the implementer must follow it |
| Plan drift | The replanner rewrites remaining tasks against the real code; it's validated and can't touch done tasks |
| Missed integration or quality gaps | Periodic and completion audits create corrective tasks automatically |
| Deploy failures | Health check and smoke tests, automatic rollback to the last good ref, plus a corrective task |
| Rate limits | Exponential backoff that doesn't count as a failed attempt |
| Cost | Caps per session, task, phase, day and total; daily cap sleeps until midnight |
| Crashes and reboots | SQLite state; `running` tasks reset; partial branches discarded; resumes where it stopped |
| Session docs | Written by the orchestrator (not left to the model): per-task history, decision log, changelog, handoff, phase summary, audit reports |

## The project contract (same for every project type)

```
.agent/
  project.yaml    # stack, verify/deploy commands, model ladder, budgets, cadence  (see template, fully commented)
  plan.yaml       # phases → tasks (id, risk, description, acceptance_criteria, files_in_scope, depends_on)
  BRAIN.md        # architecture, conventions, invariants — read by every session
  DECISIONS.md    # append-only decision log (written from session reports)
  HANDOFF.md      # what the last session did + what's next
  FOLLOWUPS.md    # out-of-scope issues sessions noticed → consumed by audit/replan
  history/<phase>/<task>.md, PHASE.md     # audit trail
  audits/*.md     # audit reports
  REPORT.md       # live status (ignored by git)
  state.db        # progress, sessions, costs (ignored by git)
```

Stack presets include python, node, go, rust, java, docker, static and generic. Any project works as long as you
put its build and test commands in `commands:`.

### Risk tier → model ladder
Attempt *n* uses `ladder[risk][n]`. By default: low `haiku→sonnet→opus`, medium `sonnet→sonnet→opus`, high/critical `opus`.
Mark auth, payments, tenant isolation, crypto and migrations as `high`/`critical`.
To route through LiteLLM/OpenRouter, set `agent.env.ANTHROPIC_BASE_URL`. To use a different agent CLI entirely,
set `agent.backend: command`.

## Commands

| Command | Purpose |
|---|---|
| `autopilot init [--stack X]` | Create `.agent/`, `.gitignore` entries and a `CLAUDE.md` pointer |
| `autopilot onboard --plan-doc PLAN.md` | AI session writes BRAIN.md, real commands and plan.yaml |
| `autopilot validate` | Schema, dependency and cycle check; warns about weak acceptance criteria |
| `autopilot next -n 20` | Preview the execution order and models |
| `autopilot run [--max-sessions N]` | Autonomous run until the completion audit passes |
| `autopilot status` | Progress, cost, blocked tasks with reasons, pending approvals |
| `autopilot unblock T1 T2` / `skip T3` | Clear the blocked queue whenever you like (edit the task spec first) |
| `autopilot answer D-003 "text"` | Answer a decision from `docs/NEEDS-YOU.md` (works while a run is active) |
| `autopilot approve P05` | Deploy a queued phase to prod |
| `autopilot review --kind periodic\|completion\|replan` | Force a review now |
| `autopilot stop` / `resume` | Graceful stop before the next session |

All commands take `-C <project path>`.

**Needs you.** A stuck task first gets one read-only diagnosis session (it may search the web) and one more attempt.
Only what truly needs you (credentials, a paid account, a business or legal call) is written in plain words to
`docs/NEEDS-YOU.md`; that feature is parked and everything else keeps being built. Answer with `autopilot answer`, or
write your answer after "Your answer:" in the file and commit it while no run is active. The run never stops for a red
check either: a failing main or phase gate becomes a corrective phase first.

## Usage, pacing and the RCA log
- Every session's tokens (input, output, cache read/write) and cost are stored per model. `.agent/REPORT.md` (and `autopilot status`) has a **Tokens** section with per-model and per-kind totals and the verification share (fixer, audit and unstick sessions); above 20% it warns that checks use more than intended. The `run_done` notification ends with a one-line token footer.
- When the CLI reports a usage limit with a reset time, the run sleeps until the window reopens (plus two minutes) and notifies you; that wait is never a task attempt and never counts toward the 30-in-a-row stop.
- Corrective (FIX) tasks must add a regression test (bugs) and report a root cause. Entries land in `docs/RCA.md` (symptom, root cause, fix, prevention), committed with the fix; main-branch repairs add a lenient entry.
- `.agent/run.json` is the live run journal; `REPORT.md` has a **This run** section with the next action.

## Running unattended on a VPS

1. Use an **API key or LiteLLM gateway** (`ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`) for unattended runs. Check
   Anthropic's current terms before automating a consumer subscription.
2. Run inside a sandbox, because sessions use `bypassPermissions`. `deploy/autopilot@.service` runs the
   `deploy/Dockerfile` image (`docker build -t autopilot -f deploy/Dockerfile .`) once per project: checkout at
   `/srv/autopilot/<name>` (its own tree, so it never touches other apps on a shared server), secrets in
   `/etc/autopilot/<name>.env` (mode 600). Start with `sudo systemctl enable --now autopilot@<name>` and follow
   with `journalctl -u autopilot@<name> -f`. Claude Code is pinned in the image (`CLAUDE_CODE_VERSION`); bump it
   deliberately. Keep prod secrets out of the agent's environment; the deploy commands should read them from CI or
   the server.
3. Notifications: set `AUTOPILOT_TG_TOKEN`/`AUTOPILOT_TG_CHAT` (Telegram), `AUTOPILOT_SLACK_WEBHOOK`, `AUTOPILOT_NTFY_TOPIC`
   or `AUTOPILOT_WEBHOOK`.
4. Your only job is to answer `docs/NEEDS-YOU.md` and approve prod deploys when notified.

## Writing plans that run well autonomously
- Keep each task to one session (~1–3 files of real logic) and give it 2–5 **testable** acceptance criteria.
- Put the real invariants in BRAIN.md: auth model, tenant isolation, API contracts.
- Put slow end-to-end checks in `commands.phase_verify`, not in the per-task gate.
- Treat `blocked` as a signal that the spec was unclear. Fix the spec, then run `autopilot unblock`.

## Development
```
pip install -e '.[dev]' && pytest -q      # end-to-end tests with a scripted fake agent, no API calls
```
Linux and macOS today. Windows support is roadmap step P1.
