# Reference

Facts to look up. For a first project, read the [tutorial](GUIDE.md). For one specific job, read the
[how-to guides](HOWTO.md). To learn why Autopilot works this way, read the [architecture](ARCHITECTURE.md).

**On this page:** [Commands](#commands) · [Environment variables](#environment-variables) · [Files](#files) ·
[Settings](#settings) · [Models](#models) · [Usage and budget](#usage-and-budget) · [Self-healing](#self-healing) ·
[Glossary](#glossary)

## Commands

Each command accepts `-C <folder>` to work on a project in a different folder.

| Command | Result |
|---|---|
| `autopilot` | Follows the active run in this folder. With no run, shows what you can do next |
| `autopilot quickstart` | Sets up `.agent/`, makes the tasks from `PLAN.md`, then checks your computer |
| `autopilot quickstart --idea "text"` | Claude writes `PLAN.md` from your idea first. The text can also be a file |
| `autopilot quickstart --plan-doc FILE` | Makes the tasks from a different plan file |
| `autopilot quickstart --run` | Also starts the run when the checks find no problem |
| `autopilot init [--stack X]` | Makes `.agent/` only. `quickstart` does this for you |
| `autopilot onboard [--plan-doc FILE]` | One session writes `BRAIN.md`, the commands and `plan.yaml`. With no file, it reads the repository |
| `autopilot validate` | Checks `project.yaml` and `plan.yaml` for errors |
| `autopilot doctor [--fix]` | Checks the Claude CLI, git, `gh`, the sandbox tools, the alerts, and the settings. `--fix` repairs what needs no person |
| `autopilot next [-n 15]` | Shows the next tasks in order, with their models |
| `autopilot run` | Builds until the completion audit passes |
| `autopilot watch` | Follows a run live. Ctrl+C stops the watch, not the run |
| `autopilot status` | Shows the progress, the cost, the blocked tasks, and the approvals |
| `autopilot stats` | Shows the numbers of a run as a Markdown table |
| `autopilot serve [--port 8765]` | Starts the status page without a run |
| `autopilot answer D-003 "text"` | Answers a question from `docs/NEEDS-YOU.md` |
| `autopilot unblock T1 T2` | Puts blocked tasks back in the queue |
| `autopilot skip T3` | Removes tasks from the queue |
| `autopilot approve P05` | Sends a phase to production |
| `autopilot stop` | Stops the run before its next session |
| `autopilot resume` | Removes the stop flag. It does not start a run |
| `autopilot review --kind periodic\|completion\|replan` | Starts an audit or a replan now |

**Options of `autopilot run`:**

| Option | Result |
|---|---|
| `--max-sessions N` | Stops after N sessions |
| `--clear-stop` | Removes the stop flag before the run starts |
| `--no-browser` | Starts the status page, but does not open the browser |
| `--no-page` | Does not start the status page |
| `-v` | Shows more log lines |

## Environment variables

| Variable | Result |
|---|---|
| `AUTOPILOT_TG_TOKEN`, `AUTOPILOT_TG_CHAT` | Telegram alerts. With `chat.enabled: true`, also Telegram commands |
| `AUTOPILOT_NTFY_TOPIC` | ntfy alerts |
| `AUTOPILOT_SLACK_WEBHOOK` | Slack alerts |
| `AUTOPILOT_WEBHOOK` | Alerts to a different web service |
| `AUTOPILOT_STATUS_TOKEN` | Lets the status page serve on an address that is not local |
| `AUTOPILOT_PLAIN=1` | Removes the pinned status row at the bottom of the terminal. `status` and the page still show the status line |
| `AUTOPILOT_NO_BROWSER=1` | Does not open the browser |
| `AUTOPILOT_NO_AUTOFIX=1` | Stops the automatic repairs of `doctor` |
| `AUTOPILOT_CLAUDE_BIN` | The path to the `claude` program |
| `ANTHROPIC_API_KEY` | Use an API key instead of a subscription. Also set `usage.billing: api` |

Your deploy commands get `AUTOPILOT_REF`, `AUTOPILOT_PHASE` and `AUTOPILOT_ENV`. The rollback command gets
`AUTOPILOT_PREV_REF`. The smoke command also gets `AUTOPILOT_URL`.

## Files

**In `.agent/`:**

| File | Content | In git |
|---|---|---|
| `project.yaml` | All settings | Yes |
| `plan.yaml` | The phases and the tasks | Yes |
| `BRAIN.md` | The architecture and the rules. Each session reads it | Yes |
| `DECISIONS.md` | The log of decisions | Yes |
| `HANDOFF.md` | What the last session did, and what is next | Yes |
| `FOLLOWUPS.md` | Problems that sessions found outside their task | Yes |
| `history/` | One file for each finished task and phase | Yes |
| `audits/` | The audit reports | Yes |
| `REPORT.md` | The live status | No |
| `run.json` | The journal of the active run | No |
| `state.db` | The progress, the sessions, and the cost | No |
| `logs/` | The log, the session logs, and the crash reports | No |
| `STOP` | The stop flag from `autopilot stop` | No |

**In `docs/` of your project:**

| File | Content |
|---|---|
| `NEEDS-YOU.md` | Questions for you |
| `RCA.md` | Each bug: the symptom, the root cause, the fix, and the prevention |
| `BACKLOG.md` | Your new ideas, one line each |
| `STATUS.md` | The plan as a checklist. Autopilot updates it at each commit |
| `adr/` | The design decisions for high-risk tasks |
| `research/` | Notes from research sessions |

`CHANGELOG.md` in the project root lists the changes.

## Settings

All settings are in `.agent/project.yaml`. The template has a comment for each setting.

| Section | Controls | Important keys (default) |
|---|---|---|
| `commands` | The commands that the checks run | `setup`, `build`, `lint`, `typecheck`, `test`, `phase_verify`, `smoke` |
| `gate` | The checks | `test_globs`, `ci_files`, `protected` |
| `agent` | The agent CLI | `backend` (`claude_cli`), `preset`, `max_turns` (200), `session_timeout_sec` (3600), `env`, `exclude_dynamic_prompt` (false) |
| `sandbox` | The network allowlist | `enabled` (false), `allowed_domains` |
| `models` | The model for each role | `ladder`, `fixer`, `auditor` (opus), `unstick` (sonnet) |
| `usage` | The 5-hour window | `billing` (subscription), `reserve_pct` (15), `opus_by_pct` (0) |
| `budget_usd` | Cost limits | `per_session` (8), `per_task` (20), `per_phase` (150), `daily` (200), `total` (5000) |
| `retries` | Attempts | `max_attempts_per_task` (3), `resume` (true) |
| `unstick` | The diagnosis of a blocked task | `enabled` (true), `after_attempts` (2) |
| `decide` | Design choices before risky tasks | `enabled` (true), `risks` (high, critical) |
| `research` | Web research for a task | `enabled` (true), `dir` (docs/research) |
| `functional` | The feature check at the end of each phase | `enabled` (true), `init` |
| `escalate` | An early move to a stronger model | `on_timeout`, `max_diff_lines` (300), `load_bearing` |
| `scheduling` | The order and parallel work | `phase_dependency` (soft), `parallel` (1) |
| `git` | Push and pull | `push` (false), `pull` (true), `mode` (direct or pr) |
| `intake` | Fix tasks from GitHub | `enabled` (false), `label` (autopilot), `poll_minutes` (30) |
| `deploy` | Staging and production | `cmd`, `health_url`, `rollback_cmd` |
| `notify`, `chat` | Alerts and Telegram commands | `events`, `chat.enabled` (false) |
| `needs_you` | The questions file | `path` (docs/NEEDS-YOU.md), `wait` (true) |
| `quality` | Model suggestions | `every` (20) |
| `replan` | Plan updates | `enabled` (true), `every_n_phases` (5) |

Autopilot supports these stacks: python, node, go, rust, java, docker, static, and generic. Each project type works
when you put its build and test commands in `commands`.

## Models

**The model for each attempt of a task:**

| Task risk | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| low | haiku | sonnet | opus |
| medium | sonnet | sonnet | opus |
| high, critical | opus | opus | opus |

A retry on the same model continues the failed session. A retry on a different model starts a new session.

**The model for each role:**

| Role | Model | Job |
|---|---|---|
| Fixer | sonnet, then opus | Repairs `main` when its checks fail |
| Unstick | sonnet | Finds the cause of a blocked task. It can search the web |
| Decide | opus | Compares 2 or 3 designs before a risky task |
| Research | sonnet | Writes web research notes for a task |
| Verifier | sonnet | Tries each feature at the end of a phase |
| Auditor, replanner, onboard | opus | Audits the app, updates the plan, writes the first plan |
| Triage | haiku | Makes a task from a GitHub issue, with no tools |

## Usage and budget

- **5-hour window:** Autopilot reads your real usage from Claude Code. This figure includes your own use. When only
  15% is left (`usage.reserve_pct`), the run pauses until the window resets. This keeps some usage for you.
- **Other agent CLIs:** they give no usage figure. Autopilot then counts its own cost against `usage.window_usd`.
- **Weekly limit:** you get one alert when the weekly limit passes 90%.
- **Usage limit:** the run sleeps until the reset, and sends an alert. This does not count as a failed attempt.
- **Cost limits:** the `budget_usd` limits apply to each session, task, phase and day, and to the total. When the
  daily limit is reached, the run sleeps until midnight.
- **Token report:** `autopilot status` and `.agent/REPORT.md` show the tokens and the cost for each model.
- **Model suggestions:** after each 20 finished tasks, Autopilot suggests a less expensive model where the data
  shows that it is safe. You make the change.

## Self-healing

A run stops only for a problem that needs a person. Each repair sends a `heal` alert.

| Problem | What Autopilot does |
|---|---|
| The code of a task fails its checks | Tries a stronger model, then a diagnosis, then asks you. It builds the other tasks |
| A tool is missing | Runs the setup again. If the tool is still missing, one repair session repairs the setup |
| The Claude CLI is broken, logged out, or offline | Installs the CLI again or waits, then tries again. This is not a failed attempt |
| The usage limit is reached | Sleeps until the window resets |
| The `autopilot` command is not on the PATH | Adds a launcher and corrects the PATH |
| The push to GitHub fails | Continues to build on your computer, and tries the push again at each commit |
| `main` is different from GitHub | Applies the local commits again on top of the GitHub commits |
| An old git lock file exists | Deletes the lock file and tries again |
| `plan.yaml` is damaged | Restores the last version that loads |
| `state.db` is damaged | Restores the backup from the start of the run |
| Autopilot stops with an error | Writes a crash report, then starts again from the saved state |

**These problems still need you:**

- Your Claude login. Run `claude`, and then type `/login`.
- A budget limit or a session limit that you set.
- A question in `docs/NEEDS-YOU.md`.
- A crash that occurs again and again. Send the report from `.agent/logs/crashes/`.

## Glossary

| Term | Meaning |
|---|---|
| Plan | `PLAN.md`, your description of the app. Autopilot makes `.agent/plan.yaml` from it |
| Phase | A group of tasks that gives one part of the app |
| Task | One unit of work. One session does one task |
| Session | One run of Claude Code with a new, empty context |
| Run | One `autopilot run`, from the start until the end or a stop |
| Checks | The build, lint, type, test, secret and test-tamper checks that Python runs after each task |
| Gate | The part of Autopilot that runs the checks |
| Blocked task | A task that failed all its attempts. The run continues with the other tasks |
| Fix task | A task that Autopilot adds to repair a failure, a gap, or a bug |
| Question | An entry in `docs/NEEDS-YOU.md` that only a person can answer |
| Completion audit | One session at the end of the plan that asks: is the app complete? |
| Usage window | The 5-hour usage limit of a Claude subscription |
