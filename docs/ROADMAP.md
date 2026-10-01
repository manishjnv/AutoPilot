# Autopilot roadmap (formerly AutoDev)

From the verified review and research on 2026-10-01. Line numbers refer to commit `1ead5af`. Nothing below is implemented yet.

## Objective
AutoDev owns a project from plan to finished app without a human in the loop. It:
- implements every phase of the plan or roadmap, and fixes bugs;
- updates the RCA log and the docs;
- decides the best approach and runs session start and end;
- proves the features work and does research when in doubt;
- tracks tokens and the 5-hour Claude window;
- uses Sonnet and Haiku wherever quality holds.

## Guiding principles (every item below must respect these)
1. **Features first.** Most tokens go to building features. Checks exist only to prove that a feature works.
2. **Light verification: one check per level.**
   - Per task: one gate.
   - Per phase: one functional check.
   - Per project: one completion audit.
   - No repeated audits, no best-of-N, no reviewer except on critical tasks (see V).
3. **Never wait for the owner.**
   - A stuck feature first tries to unstick itself: retry, then research competitors, the web and best practice, then decide.
   - If it is still stuck, it writes a decision request in plain words to `docs/NEEDS-YOU.md`, parks the feature and moves to the next one (see S).
   - The run never stops to wait for an answer.

## Coverage check: requirements vs today vs plan

| # | Requirement | Today | In plan |
|---|---|---|---|
| 1 | Implement all phases | ✅ mostly. The run continues until the completion audit passes | P3, L7 |
| 2 | Documents | ✅ mostly: history, DECISIONS, CHANGELOG, HANDOFF | L1 |
| 3 | Bug fixes | 🟡 partly: fixer, FIX phases. No regression-test rule, no outside intake | L1, L6 |
| 4 | Session start and end | 🟡 partly: a context pack per task, HANDOFF at the end | L5 |
| 5 | Prove features work | 🟡 partly: gate commands. Tests can be gamed, no functional check | P1, L4, V |
| 6 | Sonnet/Haiku without quality loss | 🟡 partly: a fixed risk ladder | U5-U8 |
| 7 | Update RCA | ❌ The fixer's `root_cause` is dropped | L1 |
| 8 | Decide best approach | ❌ Decisions are logged only after the code is written | L2, S1 |
| 9 | Research when in doubt | ❌ The prompt says "assume and move on" | L3, S1 |
| 10 | Tokens and 5-hour window | ❌ Records USD only; the rate-limit check misfires | U1-U4 |
| 11 | Feature focus, light verification | 🟡 Heavier than wanted: audits every 3 phases, up to 5 completion audits | V |
| 12 | Stuck feature → move to the next one | 🟡 partly: parks after 3 attempts, but exits on a stall and stops on a red phase gate | S1, S4, P3 |
| 13 | Decision tracker, research first | ❌ Blocked reasons are raw error text in REPORT.md | S1-S3 |

## R: Rename to Autopilot (do first, before other code changes)
Name: **Autopilot**. PyPI package: `dev-autopilot` (plain `autopilot` is taken). Command: `autopilot`.
- [ ] `pyproject.toml`: rename the package to `dev-autopilot` and the script to `autopilot = "autopilot.cli:main"`. Rename the `autodev/` package folder to `autopilot/`.
- [ ] Rename the branch prefix `autodev/` to `autopilot/`, the commit prefix `[autodev]` to `[autopilot]`, and the tags `autodev-*` to `autopilot-*`.
  - Crash recovery must still accept old `autodev/` branches (`_prepare_repo`).
- [ ] Rename the env vars `AUTODEV_*` to `AUTOPILOT_*`, keeping the old names as a fallback.
- [ ] Update the prompts, `CLAUDE.md.snippet`, README, Dockerfile and systemd unit (`autopilot@.service`).
- [ ] Keep the `.agent/` folder name, so existing projects need no migration.
- [ ] Leave `examples/todo-demo-run/` as a historical run, or regenerate it.
- [ ] Done when: the tests pass, `autopilot --version` works, and `grep -ri autodev` leaves only the fallbacks and the history.

## P1: Fix bugs
- [ ] **Windows support.** `orchestrator.py:13` `import fcntl` stops the tool and its tests from loading on Windows. Use a portable lock, and make the 2 tests that use POSIX shell commands cross-platform.
- [ ] **Git isolation hardening.** Every session's changes, including audit and replan sessions, must pass the gate before they reach `main`.
- [ ] **Test-tamper guard.** Fail the gate when test files are deleted, the test count drops, or test config or scripts change.
- [ ] **Rate-limit misfire.** `claude_cli.py:75` runs the regex over the agent's own text, so "rate limiter" or "quota" counts as a rate limit. Replace it with U3.
- [ ] **Least-privilege environment.** Pass agent sessions only the environment variables they need.
- [ ] **Small fixes.**
  - `tasks.cost` is never written.
  - `completion_rounds` never resets.
  - A `partial` phase never re-closes after its tasks are reopened (`orchestrator.py:367`).
  - The budget floor of `max(0.5, …)` can overshoot the caps.
  - On timeout, kill the whole process tree.
  - Widen the secret scan to cover more token formats.
  - Replan checks only that done-task IDs still exist, so their content can be rewritten. Reject any change to a done task (`orchestrator.py:509`).
  - The backend catches only `FileNotFoundError`. A Windows `OSError` (WinError 193) crashes the run (`claude_cli.py:51`).
  - The `deployfix-<phase>` once-key silently drops a second staging failure in the same phase (`orchestrator.py:408`). Add an S2 entry instead.

## S: Stuck features and the decision tracker (never wait for the owner)
- [ ] **S1 Unstick ladder.** Bounded, at most about 2 extra sessions per stuck task.
  1. The gate fails: retry with the error on the next model in the ladder (exists today).
  2. It fails again: one **unstick session** (Sonnet, web plus read-only) sorts the cause into one of three:
     - **Technical bug:** one more retry with its diagnosis.
     - **Unclear spec or product choice:** check competitors, docs and best practice (L3), pick an option, write it as an ADR (L2), and retry once with that decision.
     - **Needs the owner** (an account, credentials, a paid service, a legal or business call, or taste with no clear best practice): go straight to S2.
  3. Still stuck: S2, park the task, and move to the next feature.
- [ ] **S2 `docs/NEEDS-YOU.md` tracker.** One entry per decision, in plain words and newest first. The agent writes it; the owner answers. Example entry:

  ```
  ## D-003 · P04-T02 Payment webhooks · OPEN
  - Question: Which payment provider should we use?
  - What I checked: Stripe and Razorpay docs; 2 similar apps (both use Stripe).
  - Why I couldn't decide: needs your business account; fees depend on your country.
  - My suggestion: Stripe (most used, best docs).
  - Blocked until answered: P04-T02, P04-T03 (everything else continues)
  - Your answer:
  ```

- [ ] **S3 Answer intake, no restart needed.**
  - The owner fills in "Your answer", or runs `autodev answer D-003 "use Stripe"` (later also from Telegram, P5).
  - On its next loop the orchestrator adds the answer to the task spec, logs it in `DECISIONS.md`, marks the entry ANSWERED and unblocks the task and its dependants.
- [ ] **S4 Never stop to wait.**
  - Tasks that depend on a parked task wait; all other work continues (soft mode, exists today).
  - When only waiting work is left, send **one** digest notification ("3 decisions need you, see NEEDS-YOU.md"). Then poll the tracker every 15 minutes (configurable) instead of exiting as "stalled".
  - A red phase gate also leads to S2 plus a corrective task, never a fatal stop (P3).

## V: Verification budget (enough to prove a feature works, no more)
- [ ] **Per task:** one gate (build, lint, typecheck, test) plus the test-tamper guard. The task's acceptance criteria must have tests. No extra reviewer.
- [ ] **Per phase:** one functional check (L4) that runs the phase's user journeys once. **This replaces periodic audits.**
- [ ] **Per project:** one completion audit when the plan is finished, at most 2 rounds (today it allows 5).
- [ ] **A reviewer session only for `critical` tasks** (auth, payments, migrations). Best-of-N is dropped.
- [ ] **New defaults:** `audit.every_n_phases: 0`, `audit.max_completion_rounds: 2`. The deploy health check and smoke tests stay; they are cheap and deterministic.
- [ ] **Track the verification share** of tokens (gate fixes, audit and verify sessions vs build sessions) in the run summary, with a warning when it exceeds 20%.

## P2: Reliability
- [ ] Retry by continuing the failed session with `--resume <session_id>`; the ID is already stored and never used.
- [ ] Log with `--output-format stream-json --verbose`. Add stuck detection that aborts after 4 identical actions and feeds S1.
- [ ] Pass `--json-schema` so that `structured_output` is populated instead of being regex-parsed.
- [ ] Use `--max-turns`. Consider `--bare` (needs an API key) and `--permission-mode dontAsk` with an allowlist.

## P3: Autonomy
- [ ] When a phase gate fails or `main` is red, queue a corrective task plus an S2 entry instead of raising a fatal `Stop` (`orchestrator.py:122,377`).
- [ ] Run independent tasks in parallel in git worktrees.
- [ ] Add `LEARNINGS.md`: when a task passes after failing, record what fixed it, and read it in every session.

## L: Lifecycle (own the project like a senior dev)
- [ ] **L1 RCA, docs and bug fixes.**
  - Every fixer or FIX task returns structured `{symptom, root_cause, fix (file:line), prevention}`.
  - The orchestrator appends that to `docs/RCA.md` and rejects an incomplete entry.
  - A FIX task must add a regression test that fails before the fix and passes after it.
  - Every merged commit gets a short `docs/changes/<date>-<task>.md`: what, why, files, how to verify, rollback.
- [ ] **L2 Decide best approach.**
  - Only for `risk: high|critical`, `needs_decision: true`, or S1's spec branch.
  - One read-only decide session (Opus, high effort) writes 2-3 options scored against criteria to `docs/adr/NNNN-title.md` (MADR template).
  - The implementer gets that ADR. `DECISIONS.md` stays as the index.
- [ ] **L3 Research when in doubt.**
  - A separate `claude -p` session with only WebSearch, WebFetch and Read allowed (Sonnet, medium effort). It covers competitors, best practice and library docs, and writes `docs/research/<topic>.md` with sources.
  - Coding sessions read only that summary, never raw web text (prompt-injection guard).
  - Triggers: S1, a plan field `research: [topics]`, or an unknown library.
- [ ] **L4 One functional check per phase.** This follows Anthropic's "Effective harnesses for long-running agents" post.
  - `features.json` lists user-visible features with a `passes` flag. Only the orchestrator sets it.
  - At phase end, one verifier session starts the app (`init.sh`) and runs each feature's journey once: Playwright MCP headless for UI, API calls for back ends.
  - A failing feature becomes a fix task. If that fix also fails, it goes to S2.
- [ ] **L5 Session start and end.**
  - Start of every task: `git log -20`, the progress file, and a fast `init.sh` smoke test. If it is red, run the fixer first.
  - Run start: write a journal (`.agent/run.json`) so a crash resumes cleanly.
  - Run end: write a session summary of what was done, commits, open NEEDS-YOU items, the next action, and the per-model token footer from U2.
- [ ] **L6 Bug intake.**
  - Poll `gh issue list --label autodev` and failing CI runs, and dedupe them.
  - A Haiku triage step turns each into a FIX task. Issue text is untrusted and never goes straight into a coding prompt.
  - Comment the result back on the issue.
- [ ] **L7 Roadmap sync.**
  - `plan.yaml` is the source of truth. After each task, regenerate the status checklist in `docs/STATUS.md`.
  - New ideas go into `docs/BACKLOG.md`. The replanner dedupes them against the plan, imports them as phases and logs the import in `DECISIONS.md`.

## U: Usage and models (track tokens, respect the window, route cheaply)
Facts verified on 2026-10-01:
- `claude -p` **still draws from the subscription's 5-hour and weekly limits**. The June 15 change to a separate credit is paused (support.claude.com/articles/15036540). Billing mode belongs in config, because this policy may change.
- Prices per MTok: Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, Haiku 4.5 $1/$5. **Opus is only 2x Sonnet**, so the biggest savings come from cache hits and fewer retries.
- Caches are per model, so moving one task up the ladder (haiku→sonnet→opus) restarts with an empty cache each time.
- `total_cost_usd` is an estimate. `modelUsage` includes subagents, and `usage` does not. A `--resume` run reports cumulative totals, so store the difference from the previous run.

Items:
- [ ] **U1 Token ledger.** Per session, store `modelUsage` for each model (input, output, cache read and cache write tokens, costUSD) plus `num_turns`, `duration_ms`, `session_id` and the session kind. Show totals per task, phase, day, model and kind.
- [ ] **U2 Token footer.** Every run summary ends with total tokens split per model with percentages, plus the verification share from V.
- [ ] **U3 Window-aware pacing.**
  - Detect `billing: subscription|api`.
  - Detect a limit hit with the regex `You've hit your (session|weekly|Opus|Sonnet) limit · resets (.+)` on the result or stderr. Sleep until the reset time plus 2 minutes (5 hours if parsing fails).
  - A limit hit is not a task failure.
- [ ] **U4 Window budget.**
  - Keep a local ledger keyed to the window start, and reserve a configurable 15-20% of the window for the owner.
  - Schedule Opus-heavy work (decide, completion audit) early in a window.
- [ ] **U5 Role-based routing** (each model is a floor, escalated by signals):

  | Role | Model | Effort |
  |---|---|---|
  | onboard / plan, replan, completion audit, decide (ADR) | Opus | high |
  | implement low | Haiku | low → Sonnet on the first gate failure |
  | implement medium, tests, fixer try 1, unstick session | Sonnet | medium |
  | implement high | Opus | medium |
  | implement critical, critical reviewer | Opus | high |
  | research, phase functional check | Sonnet | medium |
  | docs, RCA, changelog, NEEDS-YOU text | Sonnet (Haiku for the changelog) | low |
  | exploration inside a session | custom `Explore` subagent with `model: haiku` | low |
  | log and failure triage, issue intake | Haiku → Sonnet if unclear | low |

- [ ] **U6 Signal-based escalation.**
  - Escalate on: the same failure class twice, a diff over ~300 lines or 5 files, load-bearing paths, or a timeout or loop.
  - Never route a task down to a cheaper model after it failed on a stronger one.
- [ ] **U7 Cache hygiene.** Keep `system.md` and the context-pack prefix byte-stable, keep one model per role, and set `CLAUDE_CODE_PROMPT_CACHE_TTL=1h` where it pays off.
- [ ] **U8 Quality telemetry.**
  - Log one line per task: `model · risk · attempts · reworked Y/N · tokens`.
  - Every ~20 tasks, suggest ladder changes from the data.

## P4: Git sync (local, GitHub and the VPS)
- [ ] Make GitHub the single source of truth. Fetch and run `pull --ff-only` at run start and before each task. If history has diverged, stop and notify.
- [ ] A failed push must stop and notify; today it only logs a warning (`orchestrator._push`).
- [ ] Stop force-pushing all tags (`gitops.py:122`). Push only the autodev tags.
- [ ] Optional PR mode: push each task branch, open a PR, and merge when CI is green.

## P5: Features
- [ ] Two-way Telegram/Slack: answer NEEDS-YOU items, plus `approve P05` and `unblock T3`, from chat.
- [ ] A live status page.
- [ ] Sandbox network egress allowlist.

## Deploy model (no new deploy code needed)
AutoDev already runs `deploy.<env>.cmd`, the health check, smoke tests and rollback. The deploy logic itself belongs in each project as a script or a GitHub Action:
`local --push--> GitHub <--pull/push-- AutoDev VPS`, and on a tag or merge, `GitHub Actions --> prod VPS`.
Prod secrets live in GitHub or on the prod server, never on the agent VPS.

## Suggested build order
0. R: rename to Autopilot.
1. P1, plus the V default changes, which are config-only.
2. S1-S4 and the P3 removal of fatal stops (never wait for the owner).
3. U3 and U1 (the window and the ledger).
4. L1 and L5.
5. P2.
6. L2, L3 and L4.
7. U5-U7.
8. P3 worktrees and LEARNINGS.
9. P4.
10. L6 and L7.
11. P5 and U8.

## Open question
**Subscription terms:** secondary reports say Pro/Max login is meant for Claude Code and Claude.ai. Before running unattended on a VPS, read the current Consumer Terms or use an API key.
