# AutoDev: autonomous development agent

AutoDev runs **hundreds of Claude Code sessions back-to-back, without you**, to take any project from a phased plan
to a finished, deployed app. Each session implements one task. A plain Python orchestrator owns everything else:
the plan, state, git, verification, documentation, deployment, self-review and self-correction.

```
autodev init            # adds a .agent/ contract to any repo (stack auto-detected)
autodev onboard --plan-doc docs/PLAN.md   # AI converts your plan into phases/tasks + BRAIN.md
autodev run             # runs until the app is complete
```

## How it works

```
┌─────────────────────────── orchestrator loop (deterministic Python) ───────────────────────────┐
│ next ready task (deps + phase order, corrective phases first)                                  │
│   └─ fresh session on branch autodev/<task>   ← context pack: BRAIN + DECISIONS + HANDOFF + spec│
│        └─ gate run by the orchestrator: build · lint · typecheck · test · secret scan · scope  │
│             pass → docs (history, decisions, changelog, handoff) → commit → merge to main       │
│             fail → reset, retry with the error output on the next model in the ladder          │
│             N fails → park as BLOCKED, move on (never stop the run for one task)               │
│ phase finished → phase gate (+phase_verify) → staging deploy → health/smoke → rollback on fail │
│                  → prod (auto for low-risk phases, else queued for `autodev approve`)           │
│ every N phases → AUDIT: read-only review of the whole codebase vs the plan                     │
│                  → gaps/bugs/regressions become a priority FIX phase  (self-correction)         │
│                → REPLAN: rewrite stale pending tasks, reopen blocked ones, refresh BRAIN.md     │
│ plan exhausted → COMPLETION AUDIT: "is the app actually done?" gaps → new tasks → loop again    │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Concern | How AutoDev handles it |
|---|---|
| Context rot over 100+ sessions | One task per fresh session. Memory lives in files: `BRAIN.md`, `DECISIONS.md`, `HANDOFF.md`, `history/` |
| "Done" that isn't done | The orchestrator runs the checks itself; empty diffs, protected-file edits and secrets all fail |
| One failure freezing the run | Retry, then escalate the model, then park as blocked; independent work continues (`phase_dependency: soft`) |
| Main branch breaks | A fixer session repairs it (gated) before any more work runs |
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
| `autodev init [--stack X]` | Create `.agent/`, `.gitignore` entries and a `CLAUDE.md` pointer |
| `autodev onboard --plan-doc PLAN.md` | AI session writes BRAIN.md, real commands and plan.yaml |
| `autodev validate` | Schema, dependency and cycle check; warns about weak acceptance criteria |
| `autodev next -n 20` | Preview the execution order and models |
| `autodev run [--max-sessions N]` | Autonomous run until the completion audit passes |
| `autodev status` | Progress, cost, blocked tasks with reasons, pending approvals |
| `autodev unblock T1 T2` / `skip T3` | Clear the blocked queue whenever you like (edit the task spec first) |
| `autodev approve P05` | Deploy a queued phase to prod |
| `autodev review --kind periodic\|completion\|replan` | Force a review now |
| `autodev stop` / `resume` | Graceful stop before the next session |

All commands take `-C <project path>`.

## Running unattended on a VPS

1. Use an **API key or LiteLLM gateway** (`ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`) for unattended runs. Check
   Anthropic's current terms before automating a consumer subscription.
2. Run inside a sandbox, because sessions use `bypassPermissions`: `deploy/Dockerfile`, or a dedicated VM user
   through `deploy/autodev@.service`. Keep prod secrets out of the agent's environment; the deploy commands should
   read them from CI or the server.
3. Notifications: set `AUTODEV_TG_TOKEN`/`AUTODEV_TG_CHAT` (Telegram), `AUTODEV_SLACK_WEBHOOK`, `AUTODEV_NTFY_TOPIC`
   or `AUTODEV_WEBHOOK`.
4. Your only job is to look at the blocked queue and approvals when notified.

## Writing plans that run well autonomously
- Keep each task to one session (~1–3 files of real logic) and give it 2–5 **testable** acceptance criteria.
- Put the real invariants in BRAIN.md: auth model, tenant isolation, API contracts.
- Put slow end-to-end checks in `commands.phase_verify`, not in the per-task gate.
- Treat `blocked` as a signal that the spec was unclear. Fix the spec, then run `autodev unblock`.

## Development
```
pip install -e '.[dev]' && pytest -q      # end-to-end tests with a scripted fake agent, no API calls
```
