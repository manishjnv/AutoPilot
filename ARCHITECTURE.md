# Autopilot architecture

One idea: **the model writes code, plain Python decides what is kept.**

## 1. Who does what

```mermaid
flowchart LR
    you["You<br/>write the plan"] --> orch
    orch["Orchestrator, plain Python<br/>plan, git, checks, docs, budget"]
    orch -->|one job + context files| ai["Claude Code session<br/>fresh every time"]
    ai -->|code changes + report| orch
    orch --> gate{"Gate"}
    gate -->|pass| main["main branch"]
    gate -->|fail| orch
    orch -->|questions only you can answer| you
```

| Actor | Owns |
|---|---|
| **Orchestrator** | Plan, progress, all git, running the checks, docs, deploys, model choice, budget |
| **Claude Code session** | One job: write the code for one task, or one review |
| **You** | The plan. Later: answers in `docs/NEEDS-YOU.md`, production approvals |

## 2. Life of one task

```mermaid
flowchart TD
    pick["Pick the next ready task"] --> branch["New branch"]
    branch --> session["Fresh session:<br/>task + BRAIN + decisions + handoff"]
    session --> gate{"Gate"}
    gate -->|pass| docs["Write history, changelog, handoff"]
    docs --> merge["Commit, merge to main"]
    gate -->|fail| reset["Throw the work away"]
    reset --> ladder["Go up the retry ladder"]
```

## 3. The gate

Run by the orchestrator after every task. The agent's own "done" is never trusted.

| Check | Catches | Result |
|---|---|---|
| Build, lint, typecheck, tests | Any command you configured is red | Fail |
| Test-tamper guard | A test deleted, skipped or emptied; weakened test settings; a changed CI file | Fail |
| Secret scan | An added line that looks like a key, token or password | Fail |
| Protected files | Edits to the plan, the config or the questions file | Fail |
| Empty diff | Nothing was changed | Fail |
| Scope | Changes outside the task's files | Warning |

## 4. When a task fails

```mermaid
flowchart LR
    a1["Attempt 1"] -->|fail| a2["Attempt 2<br/>stronger model, or the<br/>same session resumed"]
    a2 -->|fail| diag["Diagnosis session<br/>read-only, may search the web"]
    diag --> a3["One more attempt<br/>with the diagnosis"]
    a3 -->|fail| park["Park the task,<br/>ask in NEEDS-YOU.md"]
    park --> go["Keep building<br/>everything else"]
```

The run never stops for one task.

## 5. When a phase or the plan finishes

```mermaid
flowchart LR
    phase["Phase tasks done"] --> check["Feature check:<br/>start the app,<br/>walk its user journeys"]
    check -->|a feature fails| fix["Fix tasks"]
    check -->|all work| next["Next phase"]
    next -->|no phases left| audit{"Completion audit:<br/>is the app really done?"}
    audit -->|gaps| more["New tasks"]
    audit -->|yes| done["Finished"]
```

## 6. Models: cheap first, strong when needed

| Task risk | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| Low | Haiku | Sonnet | Opus |
| Medium | Sonnet | Sonnet | Opus |
| High, critical | Opus | Opus | Opus |

A failed task moves up, never down. Real token share in the first project:

```mermaid
pie title Tokens by model
    "Haiku" : 50
    "Sonnet" : 37
    "Opus" : 13
```

## 7. Self-healing

| Problem | What happens |
|---|---|
| Usage or rate limit | Sleeps until the window resets |
| Claude CLI, login or network down | Waits and reruns the same session |
| A tool is missing | Reruns setup, then one repair session |
| `main` goes red | A fixer session repairs it before more work |
| Push fails or `main` diverged | Keeps building locally, retries, tells you once |
| Plan or state file broken | Restores the last good copy |
| Autopilot crashes | Restarts from saved state |

Limits and outages never count as a failed attempt.

## 8. Memory lives in files

| File | Holds |
|---|---|
| `.agent/plan.yaml` | Phases and tasks |
| `.agent/BRAIN.md` | Architecture and rules. Every session reads it |
| `.agent/DECISIONS.md` | Decision log |
| `.agent/HANDOFF.md` | What the last session did |
| `.agent/history/` | A record per task |
| `.agent/state.db` | Progress, sessions, cost |
| `docs/NEEDS-YOU.md` | Questions for you |

No session depends on a long chat. After a crash or a reboot, the run continues from these files.

## 9. Trust boundary

- Sessions may not commit, push or switch branches. Git belongs to the orchestrator.
- Git hooks are off for every orchestrator git call, and `.git/config` is put back after each session.
- Sessions and checks get only an allowlist of environment variables, not your whole environment.
- Research sessions read the web but get no shell.
- Sessions run without permission prompts, so run the whole thing in a sandbox on a server. A Dockerfile and a
  systemd unit are in `deploy/`.

## 10. Code map

| File | Job |
|---|---|
| `cli.py` | All commands |
| `orchestrator.py` | The main loop |
| `plan.py` | Loads the plan, picks the next task |
| `gate.py` | The checks |
| `gitops.py` | All git commands |
| `context.py` | Builds each session's prompt from the files |
| `state.py` | SQLite state |
| `docs.py` | Writes history, changelog, handoff, RCA |
| `decisions.py` | `docs/NEEDS-YOU.md` |
| `report.py` | Status report and the live page |
| `notify.py` | Telegram, Slack, ntfy, webhook |
| `deploy.py` | Deploy, health check, rollback |
| `doctor.py` | Machine checks and safe fixes |
| `backends/` | Runs Claude Code, or another agent CLI |
| `prompts/` | Prompt text for each kind of session |

Details and every setting: [GUIDE.md](GUIDE.md).
