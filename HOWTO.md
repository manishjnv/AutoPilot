# How-to guides

Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.
It is for one developer, or for a person with an idea and a developer friend.

Words in the guides: Claude Code (the coding agent that writes the code), the gate (the check after each step), a worktree (a separate copy of the project for one task), a subscription (a paid Claude plan). Each guide does one job. For your first project, start with the [tutorial](GUIDE.md). To look up a command or a
setting, use the [reference](REFERENCE.md). The guides use `ap`, the short name of `autopilot`.

| Job | Guide |
|---|---|
| Daily use | [Answer a question](#answer-a-question-from-autopilot) · [Give advice to a task](#give-advice-to-a-task) · [Stop and continue a run](#stop-and-continue-a-run) · [Repair a blocked task](#repair-a-blocked-task) · [Add features after a run](#add-features-after-a-run) |
| Audits | [Start an audit now](#start-an-audit-now) |
| Projects | [Change the plan in plain words](#change-the-plan-in-plain-words) · [Use a project that already exists](#use-a-project-that-already-exists) · [Write a plan that runs well](#write-a-plan-that-runs-well) |
| Tasks | [Get a design choice or research before a task](#get-a-design-choice-or-research-before-a-task) |
| Install | [Start from inside Claude Code](#start-from-inside-claude-code) · [Install with one script](#install-with-one-script) · [Update or remove Autopilot](#update-or-remove-autopilot) · [What the script does](#what-the-script-does) · [Install from a clone to change the code](#install-from-a-clone-to-change-the-code) |
| Alerts | [Get alerts on your phone](#get-alerts-on-your-phone) · [Control a run from Telegram](#control-a-run-from-telegram) |
| GitHub | [Make fix tasks from GitHub issues and CI](#make-fix-tasks-from-github-issues-and-ci) · [Merge each task through a pull request](#merge-each-task-through-a-pull-request) |
| Servers | [Run Autopilot on a server](#run-autopilot-on-a-server) · [Run with the laptop off](#run-with-the-laptop-off-claude-code-routines) · [Open the status page from a different computer](#open-the-status-page-from-a-different-computer) · [Limit network access](#limit-network-access) |
| Accounts and agents | [Limit the usage and the cost](#limit-the-usage-and-the-cost-of-a-run) · [Use an API key](#use-an-api-key-instead-of-a-subscription) · [Use a different agent CLI](#use-a-different-agent-cli) · [Share Autopilot](#share-autopilot-with-a-different-person) |
| Autopilot itself | [Run the smoke test](#run-the-smoke-test) · [Test a change to a prompt](#test-a-change-to-a-prompt) · [Run the tests of Autopilot](#run-the-tests-of-autopilot) |

## Answer a question from Autopilot

Autopilot writes a question in `docs/NEEDS-YOU.md` only when a person must decide. Examples are a login, a paid
account, or a business decision. The run builds the other tasks while it waits.

1. In a terminal, list the open questions with their suggestions, and answer each one:

   ```powershell
   ap answer
   ```

   Autopilot asks for each answer. An empty line skips a question.
2. To answer one question directly, find its ID in `docs/NEEDS-YOU.md`, for example `D-001`. Then send the answer:

   ```powershell
   ap answer D-001 "use Stripe"
   ```

You can answer while the run continues. With no terminal, `ap answer` prints its usage and exits with a
non-zero code. When no run is active, you can also write your answer after "Your answer:" in the file, and then
commit the file.

## Give advice to a task

Use a hint when you know something that helps a task, for example the library to use or the cause of a failure.

1. Find the ID of the task with `ap status`, for example `P04-T02`.
2. Send the hint:

   ```powershell
   ap hint P04-T02 "use the sqlite backend, not postgres"
   ```

Each later session of the task gets the hint, also a retry. Autopilot keeps the last 5 hints for each task, with a
maximum of 2000 characters each. A hint does not change the rules or the checks. If the task is blocked, run
`ap unblock P04-T02` to use the hint.

## Stop and continue a run

1. Stop the run:

   ```powershell
   ap stop
   ```

   The run stops before its next session. It does not stop a session that is in progress.
2. Continue the run in the background:

   ```powershell
   ap start
   ```

   The build continues after you close the terminal. To follow it, run `ap watch`.

> [!NOTE]
> A plain `ap run` stops again at once while the stop flag exists. Use `ap start` or `ap run --clear-stop`, or
> run `ap resume` first.

## Repair a blocked task

A blocked task failed all its attempts. Usually, the task description is not clear.

1. Find the reason:

   ```powershell
   ap status
   ```

2. Correct the task description or its acceptance criteria in `.agent/plan.yaml`.
3. Put the task back in the queue:

   ```powershell
   ap unblock P04-T02
   ```

To remove the task from the plan, use `ap skip P04-T02`.

## Add features after a run

1. Open `docs/BACKLOG.md`.
2. Write each idea on a new line that starts with a hyphen, for example `- dark mode`.
3. Start a run:

   ```powershell
   ap run
   ```

One replan session adds the new ideas to the plan. It ignores ideas that the plan already has.

## Start an audit now

1. Start the audit that you need:

   ```powershell
   ap review --kind completion
   ```

   Use `periodic` for a check of the work so far, `completion` for a check of the full app, or `replan` for a plan
   update.
2. Read the result in the terminal. An audit that finds gaps adds fix tasks to the plan.

## Change the plan in plain words

1. Send the change:

   ```powershell
   ap change "add a dark mode"
   ```

2. Autopilot says that the change costs one replan session. Type `1` to start, or `2` to stop.
3. Read the tasks that Autopilot added, changed, and removed.
4. Type `1` to keep the result, or `2` to undo it.

Autopilot never changes a done task. With no terminal, add `--yes`. It then starts and keeps the result with no
questions.

When a run is active, Autopilot writes the idea to `docs/BACKLOG.md`. The run takes it at its next replan.

## Install the dependencies of a project

You do not install the project dependencies by hand. Before a run, Autopilot looks for them. If `node_modules/` or a virtual environment is missing, it installs them with no question. It uses `commands.setup` from `.agent/project.yaml`. If that setting is empty, it runs the standard command (for example `npm ci` or `uv sync`) and writes the command into `commands.setup`. The next run installs nothing.

Autopilot never installs a system tool such as Node, Go or `uv`. If one is missing, it prints the exact command, for example `FAIL  npm is not installed. Install it with: sudo apt install nodejs npm`. Run that command yourself, then start again.

## Use a project that already exists

1. Go to the folder of the project.
2. Type `ap`.
3. Read the one-screen summary: what is done, what is open, what comes next.
4. Press Enter. The run starts.

What this means for you:

- Work that exists in the code or in the git log stays done. Autopilot does not redo it.
- Autopilot writes no new plan file and no notes file. `BRAIN.md` links to your documents.
- Your file names stay as they are.

`ap` reads the git log, the README, `PLAN`, `ROADMAP`, `TODO` and `NOTES` files, `docs/`, `.kiro/`, `.cursor/` and
`.github/`.

### If you want to control each step

1. Make the tasks from your plan or roadmap:

   ```powershell
   ap quickstart --plan-doc ROADMAP.md
   ```

   If you have no plan document, use `ap onboard` and then `ap doctor`. The onboard session reads the
   repository and the README, and then writes a plan.
2. Show the tasks in order, and read `.agent/plan.yaml` and `.agent/BRAIN.md`:

   ```powershell
   ap next
   ```

3. Start the run with `ap run`.
4. Follow the run with `ap status`.

## Get a design choice or research before a task

1. Open `.agent/plan.yaml` and find the task.
2. To compare 2 or 3 designs before the work, add `needs_decision: true`. The choice goes to `docs/adr/`.
3. To get web research first, add `research:` with a list of topics. The notes go to `docs/research/`.

Tasks with the risk `high` or `critical` get the design choice by default (`decide.risks`).

## Write a plan that runs well

- Keep each task small enough for one session: approximately 1 to 3 files of real logic.
- Give each task 2 to 5 acceptance criteria that a test can check.
- Write the rules that must not change in `.agent/BRAIN.md`. Examples are the auth model, the data isolation, and the
  API contracts.
- Put slow end-to-end tests in `commands.phase_verify`. Autopilot runs them once for each phase, not for each task.
- Set the risk of auth, payment, crypto and migration tasks to `high` or `critical`.
- Use `critical` for the most important tasks. A separate session reviews each `critical` change before the merge.

## Get alerts on your phone

Set one or more of these environment variables before you start the run:

| Service | Environment variables |
|---|---|
| Telegram | `AUTOPILOT_TG_TOKEN` (the bot token) and `AUTOPILOT_TG_CHAT` (your chat ID) |
| ntfy | `AUTOPILOT_NTFY_TOPIC` |
| Slack | `AUTOPILOT_SLACK_WEBHOOK` |
| A different service | `AUTOPILOT_WEBHOOK` |

To select which events send an alert, edit `notify.events` in `.agent/project.yaml`.

## Control a run from Telegram

1. Set up Telegram alerts. See [Get alerts on your phone](#get-alerts-on-your-phone). Set `AUTOPILOT_TG_CHAT` to your
   own user ID.
2. In `.agent/project.yaml`, set `chat.enabled: true`.
3. Send a command to the bot in your private chat with it:

   | Command | Result |
   |---|---|
   | `status` | Shows the progress |
   | `answer D-003 use Stripe` | Answers a question |
   | `approve P05` | Sends a phase to production |
   | `unblock P04-T02` | Puts a blocked task back in the queue |
   | `hint P04-T02 use the sqlite backend` | Gives advice to a task |

> [!IMPORTANT]
> Use one bot for each project. Two runs that read the same bot take messages from each other. Autopilot ignores
> messages from groups and from other chats.

## Make fix tasks from GitHub issues and CI

1. Log in to the GitHub CLI with `gh auth login`.
2. In `.agent/project.yaml`, set `intake.enabled: true`.
3. Add the label `autopilot` to each issue that Autopilot must repair.

The run checks GitHub when it starts, and then every 30 minutes (`intake.poll_minutes`).

| Source | Result |
|---|---|
| An open issue with the `autopilot` label | A triage session writes a fix task. Autopilot comments on the issue, and closes it when the fix is on `main` |
| A failed CI run on `main` | One fix task with the end of the log |
| A question, a feature request, or text that gives orders to the agent | Declined with a comment. Put features in `docs/BACKLOG.md` |

On GitHub, only people with triage access can add a label. The coding session gets only the rewritten task, never
the text of the issue.

## Merge each task through a pull request

1. Log in to the GitHub CLI with `gh auth login`.
2. In `.agent/project.yaml`, set `git.push: true` and `git.mode: pr`.

Each task then opens a pull request. Autopilot merges it when the CI checks pass. If the CI fails, or gives no
result after `git.pr_timeout_min` minutes (default 30), Autopilot closes the pull request. That is a failed attempt.
Tasks then run one at a time.

## Keep a backup on GitHub after every task without touching main

1. Create a work branch and switch to it: `git switch -c autopilot/work`.
2. In `.agent/project.yaml`, set `main_branch: autopilot/work`, `git.push: true` and `git.mode: direct`.
3. When the run is done, open one pull request from `autopilot/work` to `main` and merge it yourself.

Each task is pushed to GitHub as soon as it passes, and `main` stays as it was until you merge. For a pull request per
task instead, set `git.mode: pr` (see the section above).

## Run Autopilot on a server

This path has not run on a real server yet.

> [!WARNING]
> Run Autopilot in a sandbox on a server. Claude Code sessions run without permission prompts.

1. On the server, run this command from an Autopilot checkout:

   ```bash
   sudo deploy/install.sh <name> <git-url>
   ```

   The script builds the Docker image, makes the `autopilot` user, clones the project to `/srv/autopilot/<name>`,
   and installs the systemd unit. It does not start the run.
2. Log in with your Claude subscription. The comments in `deploy/autopilot@.service` show how. To use an API key, see
   [Use an API key](#use-an-api-key-instead-of-a-subscription).
3. Put your secrets in `/etc/autopilot/<name>.env`. This file has mode 600.
4. Start the run:

   ```bash
   sudo systemctl enable --now autopilot@<name>
   ```

5. Read the log:

   ```bash
   journalctl -u autopilot@<name> -f
   ```

> [!CAUTION]
> Do not give production secrets to the agent. Your deploy commands must read them from CI or from the server.

## Run with the laptop off (Claude Code Routines)

This path has not been run live yet (written 2026-10-13). The prompt is tested for its commands only.

A Claude Code Routine is a scheduled cloud run. Anthropic's cloud starts a Claude Code session on a schedule. The session
clones your repository, runs one Autopilot build, pushes the branches it made, and stops. Your laptop can be off.

1. Connect the repository in your Claude Code Routines settings. Use the repository that holds `.agent/`.
2. Open `examples/routine/prompt.md` in this repository. Paste its whole text as the prompt of the routine.
3. Set the schedule, for example once each night. Each run starts a new build from the plan in the repository.
4. Set the budget in `.agent/project.yaml` before the first run:
   - `budget_usd.per_session` and `budget_usd.total` cap the cost. A run stops when a cap is spent.
   - `scheduling.max_sessions_per_run` caps the number of sessions. The prompt sets it to 3 for its run.
5. Start the routine once by hand. Wait for it to end.
6. Read the result in the next `ap status`. The line `outcome: <word>` shows how the run ended, for example
   `VERIFIED` or `BUDGET_STOP`. The branches are on the remote for you to review.

> [!CAUTION]
> The routine has no one to answer a question. A task that needs you parks and waits for your next run.
> Do not give production secrets to the routine. Keep deploy keys out of the cloud run.

Check these first when you run it for the first time:

- Does `uv` exist in the routine's environment? The prompt installs `ap` with `uv tool install dev-autopilot`.
- Can the routine's session log in to Claude Code? Without a login, no task can run.
- Can the routine push to the remote? Without push rights, the branches stay in the cloud copy only.
- Does `ap status` show an `outcome:` line after the run? If not, read the log in the routine's output.

## Open the status page from a different computer

The status page shows task errors and open questions. By default, it is available only on the computer that runs
Autopilot.

1. On your computer, open an SSH tunnel to the server:

   ```bash
   ssh -L 8765:127.0.0.1:8765 your-vps
   ```

2. Open `http://127.0.0.1:8765/` in your browser.

To serve the page on a different address, set `AUTOPILOT_STATUS_TOKEN`. Then open `http://host:8765/?token=...`.
Keep this address private.

## Limit network access

This guide needs Linux, WSL2, or macOS. On Linux, it also needs `bubblewrap` and `socat`. The Docker image has both.

1. In `.agent/project.yaml`, add:

   ```yaml
   sandbox:
     enabled: true
     allowed_domains: [pypi.org, files.pythonhosted.org, github.com]
   ```

2. Start a run.

Shell commands in a session can then connect only to these domains. Other effects:

- Coding, audit and decide sessions cannot use web search or web fetch.
- Research sessions can use the web, but cannot read the repository.
- Autopilot does not load the MCP servers of the project.
- The checks and the deploy commands of Autopilot run outside the sandbox.

## Limit the usage and the cost of a run

1. Open `.agent/project.yaml`.
2. To keep a part of each 5-hour window for your own work, set `usage.reserve_pct`. The default is 15.
3. To start the Opus sessions only early in a window, set `usage.opus_by_pct`, for example `50`.
4. Set the cost limits in `budget_usd`: `per_session`, `per_task`, `per_phase`, `daily` and `total`.
5. Keep `agent.user_config: false`. Your own plugins, hooks and MCP servers add cost and context to each session.

When the run reaches the reserve, it pauses until the window resets. When it reaches the `daily` limit, it sleeps
until the next day. When it reaches the `total` limit, it stops. The `usage` keys apply to a subscription only.

## Use a local model

Use a model on your own computer (Ollama or LM Studio) for low-risk tasks. Nothing leaves the machine and it costs nothing.

1. Start the server, for example `ollama serve`, and pull a coding model: `ollama pull qwen2.5-coder:7b`.
2. In `.agent/project.yaml`, set:

   ```yaml
   agent:
     backend: openai_compat
     base_url: http://localhost:11434/v1
     model_map:
       haiku: qwen2.5-coder:7b
   ```

3. Send only low-risk tasks to it. The `low` tier of `models.ladder` is `[haiku, sonnet, opus]`, so the first attempt of a low-risk task uses `haiku`, which the map sends to the local model. Higher tiers keep the Claude models.
4. Run `ap doctor`. The `endpoint` row says whether the server answers.

> [!NOTE]
> The local model cannot run tools or tests. It writes files and a report only. The gate runs the tests and the checks
> after each task, so a weak model fails the gate instead of passing it. Keep it on small tasks.

## Use an API key instead of a subscription

Not needed on your PC. For a server only.

1. Set `ANTHROPIC_API_KEY` in the environment of the run.
2. In `.agent/project.yaml`, set `usage.billing: api`.

With `billing: api`, Autopilot does not use the 5-hour window. Only the `budget_usd` limits apply.

To send the requests through a gateway such as LiteLLM or OpenRouter, set `agent.env.ANTHROPIC_BASE_URL`.

## What `ap` does in a folder

Open a project folder and type `ap`. The result depends on the folder:

- **Empty folder:** `ap` asks for your idea.
- **Folder with code and no `.agent/`:** `ap` reads the code and the documents, shows what is done and what is open, and asks to start.
- **Autopilot project:** `ap` continues the build.

## Limits and supported agent CLIs

Autopilot starts a CLI agent for each session. It does not drive a chat panel in an IDE, so you watch the build in
your IDE or terminal.

- **Supported CLI runners:** Claude Code, the Copilot CLI (`copilot`), `codex`, Cursor (`agent`) and `kiro-cli`. Autopilot
  uses the one that is installed and logged in. To choose one, run `ap setup`, or set `agent.backend` in `.agent/project.yaml`.
  The `gemini` and `aider` presets need an API key and are not supported.
- **Not supported:** Replit has no CLI that Autopilot can call. The Kiro and Cursor chat panels have none either.
  Use the `kiro-cli` or `agent` CLI instead. Copilot in VS Code is not a command-line tool. Autopilot needs the
  Copilot CLI, which uses the same subscription.
- **Approve-all presets:** `kiro` (`--trust-all-tools`), `cursor` (`--force`), `copilot` (`--allow-all-tools`) and `gemini` (`yolo`) approve every tool,
  not only the worktree. They never ran live. See [SECURITY.md](SECURITY.md).
- **Where you watch:** run `ap watch` in the terminal of your IDE, or open the status page in your browser.
- **After the run:** the code is on `main`. Also read `CHANGELOG.md`, `docs/RCA.md` and `docs/NEEDS-YOU.md`.
- **Presets:** Codex, Gemini, and OpenCode work through presets. They have less testing than Claude Code.
- **Start from a chat:** see [Start from inside Claude Code](#start-from-inside-claude-code). To see each command, see [What the script does](#what-the-script-does).

## Use a different agent CLI

Which agent CLI runs: when `.agent/project.yaml` has no `agent.backend`, preflight finds the first installed,
logged-in CLI on PATH (`claude`, `copilot`, `codex`, `agent`, `kiro-cli`) and writes it into the file. If none is
logged in, run `ap setup`: it finds the AI you pay for, installs its CLI, and writes the file. To choose a CLI yourself,
do these steps:

1. In `.agent/project.yaml`, set `agent.backend: command`.
2. Set `agent.preset` to `codex`, `copilot`, `gemini`, `opencode`, `kiro`, `cursor` or `aider`. For a different CLI, write the command in `agent.command`.
3. Optional: map the model names to the models of that CLI in `agent.model_map`.

> [!NOTE]
> These presets have less testing than Claude Code. They also run without permission prompts, so use a sandbox.

## Share Autopilot with a different person

1. Send the link to the repository: <https://github.com/manishjnv/AutoPilot>. The MIT license lets them use, change
   and share it.
2. The other person does [steps 1 and 2 of the tutorial](GUIDE.md#step-1-install-autopilot) on their computer,
   with their own Claude login.

Autopilot never shares your login. To continue a project, the other person clones it and runs `ap run`. The
`.agent/` folder has the plan and the history. The state database starts empty.

## Run the smoke test

The smoke test is a 3-task plan that checks Autopilot from start to end with real Claude Code sessions. See
[examples/smoke](examples/smoke/README.md).

## Test a change to a prompt

The tests of Autopilot use a fake agent that does not read the files in `autopilot/prompts/`. Only a real run
shows the effect of a prompt change.

> [!WARNING]
> Start each run by hand. Each run uses your Claude usage window. Do not add these runs to CI or to a schedule.

1. Do steps 1 and 2 of the [smoke test](examples/smoke/README.md).
2. Make sure that each phase in `.agent/plan.yaml` has a `features:` entry. Without it, no feature check runs.
3. Copy the project folder. The two runs then use the same plan.
4. In the first folder, start a run with the prompts before the change:

   ```bash
   ap run --max-sessions 10
   ```

5. Change the prompt. Then start the same run in the copy.
6. Compare the two runs:

   | Measure | Where |
   |---|---|
   | Tasks done, and tasks that passed on the first try | `ap stats` |
   | Faults that the feature checks found | `FAIL` in `.agent/history/<phase>/PROOF.md` |
   | Faults that the audit found | `.agent/audits/` |

7. Write the two results in the change note of the prompt change.

## Use Autopilot from your IDE chat

1. Run `ap init` in the project folder.
2. `ap init` adds the `autopilot` server to each of these files that exists: `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, `.kilocode/mcp.json` and `.junie/mcp/mcp.json`. It keeps your other servers.
3. For `~/.gemini/settings.json`, `~/.kiro/settings/mcp.json`, `~/.codeium/windsurf/mcp_config.json` and `claude_desktop_config.json`, add this line under `mcpServers` yourself:

   ```json
   "autopilot": {"command": "ap", "args": ["mcp"]}
   ```

4. Ask your IDE chat for the status of the build. The chat calls `ap_status`.

## Stop a run and still get a word

Press Ctrl+C during `ap start`, or run `ap stop`. The run stops and stores the outcome word STOPPED, so `ap status` and the notification name an end for every run. While a run is stopped, the bottom bar of `ap watch` shows that word after "Stopped." See [Run outcome](REFERENCE.md#run-outcome).

## Local models

Run low-risk tasks on a model on your own computer (Ollama or LM Studio). Nothing leaves the machine and it costs nothing.

1. Start the server and pull a coding model, for example `ollama pull qwen2.5-coder:7b`.
2. In `.agent/project.yaml`, set `agent.backend: openai_compat`. Optionally set `agent.base_url` (default
   `http://localhost:11434/v1`) and `agent.model_map` (for example `haiku: qwen2.5-coder:7b`).
3. Run `ap doctor`. The `endpoint` row says whether the server answers. It warns and never fails when the server is down.

The model cannot run tools. It writes each file as a fenced block and Autopilot writes the files into the worktree.
A path outside the worktree is refused. The gate then runs the tests and the checks, so a weak model fails the gate.
See [Use a local model](HOWTO.md#use-a-local-model).

## VS Code extension

A thin side panel for VS Code. It lives in `vscode/`. It has no chat participant.

1. Run `Autopilot: Start`, `Autopilot: Answer` or `Autopilot: Stop` from the command palette. Each one sends `ap start`, `ap answer` or `ap stop` to a terminal named Autopilot. The terminal is reused when it is open.
2. Open the Autopilot view in the Explorer side bar. It shows the status page of the run.
3. The view reads the port from `.agent/status.port`. `ap start` writes that file with the port the status page uses, and new projects ignore it in git. When nothing answers, the view says to run `ap` first.

Build it with `cd vscode`, `npm install` and `npx tsc --noEmit`. See [vscode/README.md](vscode/README.md). This repository does not publish the extension.

## Stop hook in the plugin

The Claude Code plugin adds a Stop hook. Claude cannot say "done" while the tests fail.

- The hook runs your test command: `commands.test` in `.agent/project.yaml`, else `python -m pytest -q` or `npm test`.
- If the tests fail, the hook blocks the stop and gives Claude a plain reason.
- If a test file has fewer lines than at HEAD, the hook blocks the stop too.
- On a clean repository the hook prints nothing and exits 0.
- One session gets at most five blocks. The sixth stop goes through.

Install the plugin from `.claude-plugin/marketplace.json`. The hook is `plugin/hooks/hooks.json`; the script is
`plugin/scripts/seal.py`.

## Start from inside Claude Code

You can start a build from a Claude Code chat in the terminal, in VS Code, or in the desktop app. The build uses
the same Claude plan as the chat. This does not work in cloud sessions.

**Option 1: paste a prompt.** Copy this prompt into Claude Code:

```text
Install Autopilot and start a build for me. Show me each command before you run it.
1. Check that git, uv and claude are installed, and that `claude auth status` shows a login.
   If one is missing, show me the tutorial https://github.com/manishjnv/AutoPilot/blob/main/GUIDE.md and stop.
2. If `ap --version` fails, install it: uv tool install git+https://github.com/manishjnv/AutoPilot
   If the shell then does not find ap, use the folder that `uv tool dir --bin` shows.
3. Ask me what to build and in which folder. Refuse my home folder and the root of a drive.
4. Tell me that the build runs for hours on my Claude plan, then wait for my "go".
5. Run: ap quickstart -C "<folder>" --idea "<my idea>" --run --detach
6. After one minute, show me the last 20 lines of <folder>/.agent/logs/detached.log.
7. Tell me to follow the build with: ap watch -C "<folder>"
```

**Option 2: install the plugin.** It adds the `/autopilot` command. In Claude Code, type:

```text
/plugin marketplace add manishjnv/AutoPilot
/plugin install autopilot@autopilot
```

Then type `/autopilot` and your idea. `/autopilot status`, `/autopilot answer` and `/autopilot stop` control the
run. If a different command has the same name, use the full name `/autopilot:autopilot`. The plugin adds a Stop hook. When Claude Code tries to stop, the hook runs the project test command. It blocks the stop if the tests fail or a test file lost lines (at most 5 times in one session). Turn it off with `/plugin disable autopilot`. Autopilot's own sessions do not load plugins (`--setting-sources`), so the hook never runs inside a build. The slash command only runs `autopilot` commands, and it asks before it installs Autopilot.

Both options start the build with `--detach`. The build is a separate process, so it continues after you close the
chat. Stop it with `ap stop -C "<folder>"`.

## Install with one script

The script installs uv, Python and Autopilot for your user, then it runs `ap setup`. That command finds the AI you pay
for, asks one question when it cannot tell, installs that one CLI, and checks its login. It shows each step before the
step starts. A second run is safe: the script skips a program that is already there. The output of each tool goes to
`~/.autopilot/install.log`; the screen shows one sentence and one command when a step fails.

> [!WARNING]
> Compare the checksum before you run the script. The script downloads and runs the installer of uv, and `ap setup`
> downloads and runs the installer of the one AI CLI you chose.

1. Open the [newest release](https://github.com/manishjnv/AutoPilot/releases/latest). Its assets hold `install.sh`,
   `install.ps1` and `SHA256SUMS`. Download the script for your shell and `SHA256SUMS`.
2. Compare the hash of the script with its line in `SHA256SUMS`. Upper case and lower case letters are equal.

   | System | Command |
   |---|---|
   | Windows (PowerShell) | `(Get-FileHash install.ps1 -Algorithm SHA256).Hash` |
   | Linux, WSL | `sha256sum install.sh` |
   | macOS | `shasum -a 256 install.sh` |

   A file from a checkout at a different commit hashes differently: the sums match only the files of that release.
3. To see the steps with no change to your computer, do a dry run:

   | System | Command |
   |---|---|
   | Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun` |
   | Windows (CMD) | `install.cmd -DryRun` |
   | macOS, Linux, WSL, Git Bash | `bash install.sh --dry-run` |

4. Run the same command without the dry-run option. Options: `--skip-login`, `--runner NAME`, `--yes` (PowerShell:
   `-SkipLogin`, `-Runner NAME`, `-Yes`). `--runner` answers the one question in advance.
5. Run `ap`. If the terminal does not find it, open a new terminal.

Run the script with `bash`, not `sh`: it uses bash features, such as `set -o pipefail`, that `sh` on Debian and
Ubuntu does not have. The one-line form in the [README](README.md#install) uses `bash` for this reason. Under Git Bash
the script hands over to `install.ps1`, because the Windows `curl` cannot run the Linux installers.

| Fact | Detail |
|---|---|
| Administrator rights | None. `ap install --rights` sets up the no-prompt path for system tools once |
| Python | If no Python 3.10 or newer is found, the script runs `uv python install 3.12` for you only. It is the one system install a run makes |
| `ap` on PATH | The script checks that `ap` runs after the install. At the end it prints ``Open a project folder and type `ap`.`` |
| git | The script does not install git. If git is missing, it says so and continues; a project that uses git needs it |
| The AI runner | `ap setup` installs one of: Claude Code, the Copilot CLI, Codex, Cursor, Kiro. Copilot in VS Code is not a command-line tool. Autopilot needs the Copilot CLI, which uses the same subscription |
| Login | Nothing logs in for you. `ap setup` prints the login command of your runner, for example `copilot login` |
| A failed step | The screen shows what failed, one sentence, and one command. The full text is in `~/.autopilot/install.log` |
| Remove Autopilot | `uv tool uninstall dev-autopilot` |

## Update or remove Autopilot

Autopilot updates itself. Once a day, after a short command such as `ap status`, it looks for a newer release. When
there is one, it prints `updating ap 0.4.0 -> v0.5.0 in the background`, and the update runs after the command has
ended. It never updates during a build, in CI, or in a git checkout. To turn it off, set `upgrade.auto: false` in
`.agent/project.yaml` or the variable `AUTOPILOT_NO_AUTO_UPGRADE=1`.

To update now, run `ap upgrade`. It gets the newest release and checks the file against `SHA256SUMS`.
`ap upgrade --check` only prints the version. For a repair, or for a second machine, run `ap install`. The install
script replaces an Autopilot that is older than the script itself.

To remove Autopilot, run:

```powershell
ap uninstall --all
```

It removes the rights the installer took, the folder `~/.autopilot`, and then the package itself (after the command
has ended, because the program cannot delete itself while it runs). `ap uninstall --all --dry-run` lists the steps.
It keeps uv, Python, git, your AI CLI with its login, and the `.agent/` folder of each project. Delete `.agent/` to
start a project clean. Without `ap`, run `uv tool uninstall dev-autopilot` (or `pip uninstall dev-autopilot`).

## Install from a clone to change the code

Use this route only if you change Autopilot itself. For normal use, see the [tutorial](GUIDE.md).

1. Clone the repository:

   ```bash
   git clone https://github.com/manishjnv/AutoPilot
   ```

2. Install it in editable mode, with the test tools:

   ```bash
   cd AutoPilot
   pip install -e '.[dev]'
   ```

## Run the tests of Autopilot

Do the steps in [Install from a clone to change the code](#install-from-a-clone-to-change-the-code). Then run:

```bash
pytest -q -n auto
```

`-n auto` runs one worker per CPU core; the suite takes about a minute on Linux. The tests use a fake agent and
make no API calls. CI runs them on Ubuntu and Windows.

## Before a merge

Run `python scripts/premerge.py` before you merge a branch of Autopilot.

- On Windows, it runs the full suite on WSL. Then it runs the test files that changed on the branch on the Windows Python.
- On Linux, it runs the suite once.
- With `--ci`, it also starts the CI workflow on the branch and prints the result of each job.

The command exits 1 when a step is red. `tests/test_hygiene.py` also finds three traps that pass on WSL and fail in CI.

## What the script does

The install script runs these commands. Use them when the script fails, or when you want to see each command.

1. **Windows (PowerShell):**

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # uv installs Python if needed
   # Open a new terminal. Then:
   uv tool install dev-autopilot            # or: uv tool install git+https://github.com/manishjnv/AutoPilot@v0.4.0
   ap setup                                 # names the AI you pay for, installs its CLI, prints its login command
   ap doctor
   ```

2. **macOS, Linux, WSL:**

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh      # uv installs Python if needed
   # Open a new terminal. Then:
   uv tool install dev-autopilot            # or: uv tool install git+https://github.com/manishjnv/AutoPilot@v0.4.0
   ap setup                                 # names the AI you pay for, installs its CLI, prints its login command
   ap doctor
   ```
