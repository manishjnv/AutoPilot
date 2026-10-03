# How-to guides

Each guide does one job. For your first project, start with the [tutorial](GUIDE.md). To look up a command or a
setting, use the [reference](REFERENCE.md).

| Job | Guide |
|---|---|
| Daily use | [Answer a question](#answer-a-question-from-autopilot) · [Give advice to a task](#give-advice-to-a-task) · [Stop and continue a run](#stop-and-continue-a-run) · [Repair a blocked task](#repair-a-blocked-task) · [Add features after a run](#add-features-after-a-run) |
| Projects | [Change the plan in plain words](#change-the-plan-in-plain-words) · [Use a project that already exists](#use-a-project-that-already-exists) · [Write a plan that runs well](#write-a-plan-that-runs-well) |
| Install | [Start from inside Claude Code](#start-from-inside-claude-code) · [Install with one script](#install-with-one-script) · [Update or remove Autopilot](#update-or-remove-autopilot) · [Install from a clone to change the code](#install-from-a-clone-to-change-the-code) |
| Alerts | [Get alerts on your phone](#get-alerts-on-your-phone) · [Control a run from Telegram](#control-a-run-from-telegram) |
| GitHub | [Make fix tasks from GitHub issues and CI](#make-fix-tasks-from-github-issues-and-ci) |
| Servers | [Run Autopilot on a server](#run-autopilot-on-a-server) · [Open the status page from a different computer](#open-the-status-page-from-a-different-computer) · [Limit network access](#limit-network-access) |
| Accounts and agents | [Use an API key](#use-an-api-key-instead-of-a-subscription) · [Use a different agent CLI](#use-a-different-agent-cli) · [Share Autopilot](#share-autopilot-with-a-different-person) |
| Autopilot itself | [Run the smoke test](#run-the-smoke-test) · [Test a change to a prompt](#test-a-change-to-a-prompt) · [Run the tests of Autopilot](#run-the-tests-of-autopilot) |

## Answer a question from Autopilot

Autopilot writes a question in `docs/NEEDS-YOU.md` only when a person must decide. Examples are a login, a paid
account, or a business decision. The run builds the other tasks while it waits.

1. In a terminal, list the open questions with their suggestions, and answer each one:

   ```powershell
   autopilot answer
   ```

   Autopilot asks for each answer. An empty line skips a question.
2. To answer one question directly, find its ID in `docs/NEEDS-YOU.md`, for example `D-001`. Then send the answer:

   ```powershell
   autopilot answer D-001 "use Stripe"
   ```

You can answer while the run continues. With no terminal, `autopilot answer` prints its usage and exits with a
non-zero code. When no run is active, you can also write your answer after "Your answer:" in the file, and then
commit the file.

## Give advice to a task

Use a hint when you know something that helps a task, for example the library to use or the cause of a failure.

1. Find the ID of the task with `autopilot status`, for example `P04-T02`.
2. Send the hint:

   ```powershell
   autopilot hint P04-T02 "use the sqlite backend, not postgres"
   ```

Each later session of the task gets the hint, also a retry. Autopilot keeps the last 5 hints for each task, with a
maximum of 2000 characters each. A hint does not change the rules or the checks. If the task is blocked, run
`autopilot unblock P04-T02` to use the hint.

## Stop and continue a run

1. Stop the run:

   ```powershell
   autopilot stop
   ```

   The run stops before its next session. It does not stop a session that is in progress.
2. Continue the run:

   ```powershell
   autopilot run --clear-stop
   ```

> [!NOTE]
> A plain `autopilot run` stops again at once while the stop flag exists. Use `--clear-stop`, or run
> `autopilot resume` first.

## Repair a blocked task

A blocked task failed all its attempts. Usually, the task description is not clear.

1. Find the reason:

   ```powershell
   autopilot status
   ```

2. Correct the task description or its acceptance criteria in `.agent/plan.yaml`.
3. Put the task back in the queue:

   ```powershell
   autopilot unblock P04-T02
   ```

To remove the task from the plan, use `autopilot skip P04-T02`.

## Add features after a run

1. Open `docs/BACKLOG.md`.
2. Write each idea on a new line that starts with a hyphen, for example `- dark mode`.
3. Start a run:

   ```powershell
   autopilot run
   ```

One replan session adds the new ideas to the plan. It ignores ideas that the plan already has.

## Change the plan in plain words

1. Send the change:

   ```powershell
   autopilot change "add a dark mode"
   ```

2. Autopilot says that the change costs one replan session. Type `1` to start, or `2` to stop.
3. Read the tasks that Autopilot added, changed, and removed.
4. Type `1` to keep the result, or `2` to undo it.

Autopilot never changes a done task. With no terminal, add `--yes`. It then starts and keeps the result with no
questions.

When a run is active, Autopilot writes the idea to `docs/BACKLOG.md`. The run takes it at its next replan.

## Use a project that already exists

1. Go to the folder of the project.
2. Make the tasks from your plan or roadmap:

   ```powershell
   autopilot quickstart --plan-doc ROADMAP.md
   ```

   If you have no plan document, use `autopilot onboard` and then `autopilot doctor`. The onboard session reads the
   repository and the README, and then writes a plan.
3. Show the tasks in order, and read `.agent/plan.yaml` and `.agent/BRAIN.md`:

   ```powershell
   autopilot next
   ```

4. Start the run with `autopilot run`.

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

## Run Autopilot on a server

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

## Use an API key instead of a subscription

1. Set `ANTHROPIC_API_KEY` in the environment of the run.
2. In `.agent/project.yaml`, set `usage.billing: api`.

With `billing: api`, Autopilot does not use the 5-hour window. Only the `budget_usd` limits apply.

To send the requests through a gateway such as LiteLLM or OpenRouter, set `agent.env.ANTHROPIC_BASE_URL`.

## Use a different agent CLI

1. In `.agent/project.yaml`, set `agent.backend: command`.
2. Set `agent.preset` to `codex`, `gemini` or `opencode`. For a different CLI, write the command in `agent.command`.
3. Optional: map the model names to the models of that CLI in `agent.model_map`.

> [!NOTE]
> These presets have less testing than Claude Code. They also run without permission prompts, so use a sandbox.

## Share Autopilot with a different person

1. Send the link to the repository: <https://github.com/manishjnv/AutoPilot>. The MIT license lets them use, change
   and share it.
2. The other person does [steps 1 to 3 of the tutorial](GUIDE.md#step-1-install-three-programs) on their computer,
   with their own Claude login.

Autopilot never shares your login. To continue a project, the other person clones it and runs `autopilot run`. The
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
   autopilot run --max-sessions 10
   ```

5. Change the prompt. Then start the same run in the copy.
6. Compare the two runs:

   | Measure | Where |
   |---|---|
   | Tasks done, and tasks that passed on the first try | `autopilot stats` |
   | Faults that the feature checks found | `FAIL` in `.agent/history/<phase>/PROOF.md` |
   | Faults that the audit found | `.agent/audits/` |

7. Write the two results in the change note of the prompt change.

## Start from inside Claude Code

You can start a build from a Claude Code chat in the terminal, in VS Code, or in the desktop app. The build uses
the same Claude plan as the chat. This does not work in cloud sessions.

**Option 1: paste a prompt.** Copy this prompt into Claude Code:

```text
Install Autopilot and start a build for me. Show me each command before you run it.
1. Check that git, uv and claude are installed, and that `claude auth status` shows a login.
   If one is missing, show me the tutorial https://github.com/manishjnv/AutoPilot/blob/main/GUIDE.md and stop.
2. If `autopilot --version` fails, install it: uv tool install git+https://github.com/manishjnv/AutoPilot
   If the shell then does not find autopilot, use the folder that `uv tool dir --bin` shows.
3. Ask me what to build and in which folder. Refuse my home folder and the root of a drive.
4. Tell me that the build runs for hours on my Claude plan, then wait for my "go".
5. Run: autopilot quickstart -C "<folder>" --idea "<my idea>" --run --detach
6. After one minute, show me the last 20 lines of <folder>/.agent/logs/detached.log.
7. Tell me to follow the build with: autopilot watch -C "<folder>"
```

**Option 2: install the plugin.** It adds the `/autopilot` command. In Claude Code, type:

```text
/plugin marketplace add manishjnv/AutoPilot
/plugin install autopilot@autopilot
```

Then type `/autopilot` and your idea. `/autopilot status`, `/autopilot answer` and `/autopilot stop` control the
run. If a different command has the same name, use the full name `/autopilot:autopilot`. The plugin has no hooks. It only runs `autopilot` commands, and it asks before it installs Autopilot.

Both options start the build with `--detach`. The build is a separate process, so it continues after you close the
chat. Stop it with `autopilot stop -C "<folder>"`.

## Install with one script

The script installs git, uv, Claude Code and Autopilot, and then it checks the login. It shows each step before
the step starts. A second run is safe: the script skips a program that is already there.

> [!WARNING]
> Compare the checksum before you run the script. The script downloads and runs the installers of uv and Claude Code.

1. Download the script. The address has a fixed commit, thus the file cannot change.

   - **Windows (PowerShell):**

     ```powershell
     irm https://raw.githubusercontent.com/manishjnv/AutoPilot/d49382e72e814a8589137e29cee475f8fa1bb37b/install.ps1 -OutFile install.ps1
     (Get-FileHash install.ps1 -Algorithm SHA256).Hash
     ```

   - **macOS, Linux, WSL:**

     ```bash
     curl -fsSLO https://raw.githubusercontent.com/manishjnv/AutoPilot/d49382e72e814a8589137e29cee475f8fa1bb37b/install.sh
     sha256sum install.sh
     ```

2. Compare the result with this table. Upper case and lower case letters are equal. On macOS, use
   `shasum -a 256 install.sh`.

   | File | SHA-256 |
   |---|---|
   | `install.ps1` | `6e2a2cec709da55050764c705bb895ab0916c0a076d4d21a937100bc9d12e89b` |
   | `install.sh` | `9a6af03b8cb93debc364f438c3c9f4559e005b25cdda721534e526728516b858` |

3. To see the steps with no change to your computer, do a dry run:

   | System | Command |
   |---|---|
   | Windows | `powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun` |
   | macOS, Linux, WSL | `bash install.sh --dry-run` |

4. Run the same command without the dry-run option.
5. Open a new terminal. Then run `autopilot`.

| Fact | Detail |
|---|---|
| Administrator rights | Only on Windows, and only if `winget` installs git |
| git on macOS and Linux | The script does not use `sudo`. If git is missing, it shows the command and stops |
| Login | The script does not log in for you. It shows `claude auth login` if the login is missing |
| Remove Autopilot | `uv tool uninstall dev-autopilot` |

## Update or remove Autopilot

To install a newer version, run:

```powershell
uv tool install --reinstall git+https://github.com/manishjnv/AutoPilot
```

To remove Autopilot, run:

```powershell
uv tool uninstall dev-autopilot
```

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
pytest -q
```

The tests use a fake agent and make no API calls. CI runs them on Ubuntu and Windows.
