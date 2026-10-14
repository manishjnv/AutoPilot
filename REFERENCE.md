# Reference

Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.
It is for one developer, or for a person with an idea and a developer friend.

Words on this page: Claude Code (the coding agent that writes the code), the gate (the check after each step), a worktree (a separate copy of the project for one task), a subscription (a paid Claude plan), `plan.yaml` (the task list). Facts to look up. For a first project, read the [tutorial](GUIDE.md). For one specific job, read the
[how-to guides](HOWTO.md). To learn why Autopilot works this way, read the [architecture](ARCHITECTURE.md).

**On this page:** [Commands](#commands) · [Environment variables](#environment-variables) · [Files](#files) ·
[Settings](#settings) · [Proof features](#proof-features) · [Gate guards](#gate-guards) · [Models](#models) · [Usage and budget](#usage-and-budget) · [Self-healing](#self-healing) ·
[Dashboard colours](#dashboard-colours) · [Glossary](#glossary)

## Commands

Each command accepts `-C <folder>` to work on a project in a different folder. With no `-C`, a command uses the current folder. If the current folder is not a project, the command uses the project with the active run, or the last project that you used. It prints the project that it uses.

A read-only command (`status`, `watch`, `next`, `report`) first prints `project: <folder> (last used)`, or `(active)` when that project has the active run. A spending command (`start`, `run`, `answer`, `change`, `stop`, `skip`, `approve`, `budget`) asks `Build <folder>? [y/N]` in a terminal. With no terminal, it prints `name the project with -C <folder>` and exits with code 3. `--yes` or `-C` skips the question.

| Command | Result |
|---|---|
| `autopilot` | In a terminal, in a folder with no project: the guided start. It asks what to build and which folder, checks the login, makes the plan, and asks `1 start now, 2 not now`. Otherwise it follows the active run, or shows what you can do next |
| `python scripts/premerge.py [--ci]` | In a clone of Autopilot: the full suite on WSL (or Linux), then the test files changed on the branch on the host Python; `--ci` also runs `ci.yml` on the branch and prints each job. Exit 1 on any red step |
| `autopilot quickstart` | Sets up `.agent/`, makes the tasks from your plan, then checks your computer. It stops before the first session when the Claude login is missing. The plan is found by content (W35): every `.md`, `.txt` and `.rst` file outside `node_modules`, `.venv`, `venv`, `.git`, `.agent`, `dist` and `build` is scored by checkbox lines, numbered steps, headings with phase / milestone / sprint / step / task, and size (200 kB read per file). A clear winner (1.2x the next score) is used and printed: `plan found: docs/architecture.md (38 checkboxes, 12 phase headings)`. Close candidates give one question with the top three (Enter = the first; with no terminal the first is used and printed). With no candidate, a `PLAN.md` or `docs/PLAN.md` is used by name, else the idea path runs. The discovery pack of the first plan lists the top three candidates with their scores and first lines |
| `autopilot quickstart --idea "text"` | Claude writes `PLAN.md` from your idea first. The text can also be a file |
| `autopilot quickstart --plan-doc FILE` | Makes the tasks from a different plan file; it always wins over the found plan |
| `autopilot quickstart -C myapp --idea "text" --run` | Makes the folder `myapp`, writes the plan, makes the tasks, checks your computer, and starts the run |
| `autopilot init [--stack X]` | Makes `.agent/` only. `quickstart` does this for you. It also adds one short Autopilot block (`ap status`, `ap next`, `ap start`; no plan files, change the plan with `ap change`) to `CLAUDE.md` and to the rule file of each IDE it finds: `.cursor/` gets `.cursor/rules/autopilot.mdc`, `.kiro/` gets `.kiro/steering/autopilot.md`, `.vscode/` together with an existing `.github/` gets `.github/copilot-instructions.md` (`.vscode/` alone creates nothing), and `GEMINI.md` and `AGENTS.md` get the block at the end. The block has begin and end marker comments. A second `init` finds the marker and writes nothing. Your own text is never changed |
| `autopilot onboard [--plan-doc FILE]` | One session writes `BRAIN.md`, the commands and `plan.yaml`. With no file, it reads the repository. The session gets a discovery pack (git log, documents, stack files, one test run) and four rules: read first, mark existing work `status: done`, link documents, keep file names. New files outside `.agent/` and `CLAUDE.md` are named in a warning |
| `autopilot validate` | Checks `project.yaml` and `plan.yaml` for errors; prints how many phases can run side by side (`depends_on: []` on a phase that shares no file with the phases before it) and the shared file of each pair that cannot. Also prints the session environment (`session env: CLAUDE_CONFIG_DIR=<value or unset>, <n> passthrough`) and the runner (`runner: claude at <path>, config folder <CLAUDE_CONFIG_DIR or ~/.claude>`). A key written twice in one mapping of `project.yaml` or `plan.yaml` is an error: `duplicate key 'env' in agent: lines 86 and 112` |
| `autopilot doctor [--fix]` | Checks the runner (`runner: none chosen yet` when the project has none) and its login, git, `gh`, the sandbox tools, the alerts, the settings, and project dependencies that are not installed (a `WARN` with the install command). A missing login is a `FAIL`. `--fix` repairs what needs no person |
| `autopilot run` (and `start`, `quickstart`) preflight | Before the first session, Autopilot checks the project dependencies (`node_modules/`, a virtual environment, the Go and Cargo caches). If some are missing, it runs `commands.setup`. When `commands.setup` is empty, it runs the standard command (for example `npm ci`) and writes it into `commands.setup` of `project.yaml`. The comments in the file stay. A failed install prints the command and the end of its output, and the run does not start. If the system tool is not installed (for example `npm`), Autopilot never installs it. It prints `FAIL  <tool> is not installed. Install it with: <command>` and stops |
| `autopilot next [-n 15]` | Shows the next tasks in order, with their models |
| `autopilot run` | Builds until the completion audit passes |
| `autopilot start` | Starts or continues the build in the background. It is the same as `run --clear-stop --detach` |
| `autopilot watch` | Follows a run live. A large terminal window shows a dashboard. It has panels for the project, the tasks, the live output, the progress, the usage, the files, and the issues. A small window shows the scrolling view with a status panel at the bottom. Ctrl+C stops the watch, not the run. The `Waiting for:` line shows the last tool and its time, or the gate, for example `Gate: tests, 2m 40s`. The clock ticks every second. The spinner pauses after 30 seconds with no heartbeat. An old error shows its age and turns dim after the next good session. The Project panel shows the version and `Run N (since HH:MM)`. A window that is too small shows `Widen the window for the panels.`, and the panels start when the window grows. With `NO_COLOR`, the screen uses bold and dim only. `ap status` starts with the version line |
| `autopilot watch --scroll` | Shows the scrolling view in plain words, also in a large window |
| `autopilot watch --detail` | Shows each technical log line as it is |
| `autopilot mcp` | Runs an MCP server on `stdin` and `stdout`. Its tools are `ap_status`, `ap_next`, `ap_start`, `ap_stop` and `ap_answer`. Each tool runs the `ap` command of the same name and returns its text. `init` adds the server to `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, `.kilocode/mcp.json` and `.junie/mcp/mcp.json` when they exist |
| `ap verify [PHASE]` | Checks the signed receipt (`.agent/history/<phase>/receipt.json`) of each closed phase, offline. One line per phase: `P01 ok` or `P01 CHANGED: PROOF.md` (also `bad signature`, `<file> missing`). Exit 1 on any problem. The receipt holds the commit, a sha256 per phase file and an HMAC-SHA256 signature; the key is `~/.autopilot/receipt.key` (`AUTOPILOT_HOME` moves it), created once with mode 0600, never inside the project. The run writes the receipt when it closes a phase |
| `ap tour [--speed N] [--once]` | Replays a recorded run (`autopilot/templates/tour/events.jsonl`, shipped with the package) in the watch window at N times real time (default 10), then prints the proof (`PROOF.md`: outcome word and Not proven list) and the lines `Install: uv tool install dev-autopilot` and `Start: ap`. It needs no login, no key and no network, and writes no file. `--once` draws the last frame only and exits 0, for CI |
| `ap upgrade [--check] [--ref vX.Y.Z]` | Gets the newest release. Before `ap run` or `ap start` Autopilot does this by itself once a day, then starts the command again on the new version. After a short command it does it in the background, unless a build is active, `CI` is set, `upgrade.auto: false` is set or `AUTOPILOT_NO_AUTO_UPGRADE=1`; a git checkout only gets a hint. It checks the wheel against `SHA256SUMS` before it installs. `--check` only prints. A git checkout gets `git pull --ff-only`, and only when it has no changes |
| `ap install [--rights]` | Installs or repairs Autopilot for this user: `uv`, then the newest release. `--rights` shows the rights step, or the command that takes them. At the end it runs `ap setup` |
| `ap setup [--dry-run] [--runner NAME] [--yes] [--skip-login] [--skip-probe]` | Finds the AI you pay for and sets it up. The scan is read-only. It lists the runners on PATH with their logins, the token variables (names only), footprints such as `~/.claude`, `gh auth status`, uv, Python, Node, and git. It prints `found`, `will install` and `skipped` lines. A logged-in runner wins and nothing installs. An installed runner without a login stays, and its login command is printed. Otherwise it asks one question, "Which AI do you pay for?" The one clear signal is the default. `--runner`, `AUTOPILOT_RUNNER` or `--yes` answer it in advance. Then it installs that one CLI with the command of the runner table and checks the login. It writes `agent.backend` or `agent.preset` into `.agent/project.yaml` (in a project) and `~/.autopilot/runner`. A footprint never installs by itself. Exit codes: 0 OK, 1 a step failed, 2 bad usage, 3 a choice is needed. Code 3 means no terminal and no answer; it prints the line to run again. Each tool's output goes to `~/.autopilot/install.log`. The screen gets one sentence and one command when a step fails. The catalogue matches an exit code or error code first, a vendor error id second, and English keywords third. After the login check, setup sends the prompt `Reply with the single word ready.` through the runner in an empty temporary folder. The word `ready` within 60 seconds passes. A pass writes `verified: <date>` into `~/.autopilot/machine.json` and `agent.verified` in `project.yaml`. `--skip-probe` skips the prompt. `ap doctor --runner` sends it alone. With a terminal, setup runs the login of the runner. WSL, SSH, a container, a snap desktop, or a Linux machine with no display or `BROWSER` gets the headless login form. Setup prints each address and code as text in every case. The login stops at the vendor's own timeout, 15 minutes at most. Setup also checks git ownership, line endings, API keys (names only), clock skew over 3 minutes, free disk under 1 GB, git older than 2.30, a non-UTF-8 console, and a busy status-page port. |
| Repairs without a question | `ap setup` and `ap doctor --fix` run five repairs. They set git `safe.directory` and `core.autocrlf` for the project. They put the tool folder on the PATH of new terminals once, using `uv tool update-shell` or the user PATH on Windows. A marker in `~/.autopilot/machine.json` stops a second run. They print one line for a Windows Defender exclusion, which needs an administrator. They name two installs of one vendor CLI and the removal command for the other. `ap upgrade` copies an older `.agent/` to `.agent/backup-<version>/`, then migrates it and prints what changed |
| Errors in a running build | The vendor sends a 5xx answer or a timeout, or the host cannot be reached. Autopilot waits and runs the same session again. It spends no try and parks no task. Three such answers within 15 minutes cause a wait of 15 minutes. After the fourth wait, the next three answers end the run with "The service is down, try again in 15 minutes." and the outcome `STALLED`. A login that ran out stops the run with `FAILED`. It spends no try and prints the login command of the runner. The next start continues the task. A model that is not on the plan names the alias to use. The same parsed error from three different tasks, with no merged task between them, stops the run with `STALLED` and four lines: the sentence, what is done, what is not, and the next command |
| `ap setup --reset` | Forgets the finished steps in `~/.autopilot/setup.json`. A normal rerun prints each finished step as a `done` line and continues at the first open step. Setup records how it installed each tool (native, winget, brew, npm, pip, uv) in `~/.autopilot/machine.json`. `ap upgrade` and `ap uninstall --steps` use that record. `ap uninstall --steps` undoes the finished steps in reverse and keeps uv, Python and git |
| `ap move [TARGET] [--yes]` | Moves a project out of a folder that hurts: OneDrive, a redirected Documents folder, a network share, or `/mnt/<drive>` in WSL. It runs `git clone --local` to the target, copies `.agent/`, keeps the remotes, and adds the new path to the recent projects. The old folder stays, with a `MOVED.md` note that names the new path. The default target is `%LOCALAPPDATA%\dev\NAME` on Windows and `~/dev/NAME` elsewhere. `--yes` moves at once. With no terminal and no `--yes`, it only prints the command. `ap doctor --project` says if the folder is a bad place |
| `ap uninstall [--rights] [--all] [--dry-run]` | `--rights` removes the scheduled task or the `sudoers` file the installer created. `--all` also deletes `~/.autopilot` and then the package (uv tool or pip), after the command has ended; it keeps uv, Python, git, the AI CLI and each project's `.agent/`. `--dry-run` lists the steps |
| `ap` | The short name of `autopilot`. `ap status` is the same as `autopilot status` |
| `autopilot status` | Shows the progress, the cost, the blocked tasks, and the approvals. After a run ends it also shows `outcome: <word>` (see [Run outcome](#run-outcome)) |
| `autopilot stats` | Shows the numbers of a run as a Markdown table |
| `autopilot serve [--port 8765]` | Starts the status page without a run. The page shows the same dashboard as the terminal, and the full report below it |
| `autopilot answer` | Lists the open questions with their suggestions. In a terminal, it asks for a choice for each one. Type `1` or press Enter to use the suggested fix. Type `2` to skip the task. Type `3` to write your own words. With no terminal, it prints the usage and exits with a non-zero code |
| `autopilot answer D-003 "text"` | Answers a question from `docs/NEEDS-YOU.md`. Works while a run is active |
| `autopilot change "text"` | Changes the plan in plain words. It costs one replan session. It asks `1 start, 2 stop`, then `1 keep, 2 undo`. `--yes` asks nothing. During a run, the idea goes to `docs/BACKLOG.md`. Done tasks never change |
| `autopilot hint T1 "text"` | Gives advice to the next session of a task. Works while a run is active |
| `autopilot unblock T1 T2` | Puts blocked tasks back in the queue |
| `autopilot skip T3` | Removes tasks from the queue |
| `autopilot approve P05` | Sends a phase to production |
| `autopilot stop [--now]` | Stops the run before its next session and prints how long the current session has run. W39: `--now`, or a second `ap stop` within 60 seconds of the first, ends the task session at once: its process tree is ended by process ID or job object (on Linux and macOS SIGINT first, then 20 seconds for the session to finish), its files are committed on `autopilot/<task>`, the attempt is not counted, the task note reads `cut by the owner, resume` and the run ends STOPPED. A stop during the gate waits for the gate. The next `ap start` (after `ap resume`) puts the files back and tells the session `You were stopped by the owner; continue from the files on disk.` |
| `autopilot resume` | Removes the stop flag. It does not start a run |
| `ap budget <usd> [-C folder]` | W43: sets the cost cap `budget_usd.total` in `.agent/project.yaml` with a one-line edit; the comments stay. A running build reads the new cap before its next task. A value of 0 or less exits 1 |
| `autopilot review --kind periodic\|completion\|replan` | Starts an audit or a replan now |
| `autopilot audit` | Starts the completion audit now |
| `ap audit --history [--days N] [--home PATH]` | Reads `<home>/projects/*/*.jsonl` of Claude Code (default `~/.claude`, last 30 days) and prints one row per project: sessions, tokens, tool calls, repeats (the same Bash command failing 3 or more times in one session) and the cost of those retries at public API rates (unknown model = Sonnet), then `Retries cost about $X of $Y.` Prints `No Claude Code history found.` when the folder is missing. Needs no project and no network, writes no file, and never prints a prompt or a command |
| `ap audit --ladder` | W23: reads this project's `.agent/state.db` (read-only) and prints one row per model and risk: finished tasks, median minutes per task (the sum of the task's session durations), median attempts, retry share and cost per task. The model of a row is the model of the task's first attempt; the risk comes from `plan.yaml`. Then one `propose: models.ladder.<risk>: [...]` line for each risk whose ladder starts on a model that is slower than the next model up and not cheaper per task (within 10 percent counts as the same cost; each side needs 2 finished tasks; the model up is compared on the same risk, else on all its tasks). It changes nothing: copy the line into `project.yaml` yourself |
| `ap audit --signals [--days N]` | W29b: reads `unknown.jsonl` (see Unknown session errors) and the `quality` and `task_blocked` events of each project in the recent list (`~/.autopilot/recent`; each `.agent/state.db` opened read-only), last 30 days by default, and prints one plain table: the top 10 unknown wordings (count, cause, first 80 characters), blocked tasks by cause, gate failures of blocked tasks by kind (`no_change`, `protected`, `secret`, `kill`, `scope`, `reasons`, `growth`, `review`, `tests`, `other`) and retries by cause (the extra attempts of a blocked task count under its cause; those of a finished task count as `recovered`; each project is counted on its own, then summed). A missing file or project database gives one `skipped:` line. With no data at all it prints one line and exits 0. Needs no network and writes no file |
| `autopilot report --tokens` | Shows the tokens and the cost of each step type |

**Options of `autopilot run`:**

| Option | Result |
|---|---|
| `--max-sessions N` | Stops after N sessions |
| `--detach` | Starts the run as a separate process and returns. The run continues after the terminal or the Claude Code chat closes. Its output goes to `.agent/logs/detached.log`. `quickstart` also has this option |
| `--clear-stop` | Removes the stop flag before the run starts |
| `--no-browser` | Starts the status page, but does not open the browser |
| `--no-prod` | Runs everything, staging included, except the deploy to the production host. The phase then waits with `prod skipped (--no-prod)`; run `autopilot approve <phase>` later |
| `--no-page` | Does not start the status page. Otherwise the port it uses is written to `.agent/status.port` (digits and a newline), so an editor can find the page |
| `-v` | Shows more log lines |

## Versions and releases

`ap --version` prints the version and the short commit, or `installed` outside a git checkout. `python scripts/bump.py X.Y.Z` sets the version in `pyproject.toml`, the plugin and `autopilot/__init__.py`. It also moves the `CHANGELOG.md` Unreleased lines, sets `DEFAULT_REF` in both install scripts, then makes one commit and the tag `vX.Y.Z`. The Unreleased block of `CHANGELOG.md` starts with the line `**In plain words:**`. Each entry is one sentence of at most 25 words, with no config key and no file name. The script refuses the bump with `release notes rule: ...` when either rule fails. CI lints the Unreleased block with Vale. A push of that tag starts `release.yml`: it runs the tests, builds the wheel and attaches the wheel, the install scripts and `SHA256SUMS` to the GitHub release.

## Environment variables

| Variable | Result |
|---|---|
| `AUTOPILOT_TG_TOKEN`, `AUTOPILOT_TG_CHAT` | Telegram alerts. With `chat.enabled: true`, also Telegram commands |
| `AUTOPILOT_NTFY_TOPIC` | ntfy alerts; a bare topic is public; `ap validate` warns |
| `AUTOPILOT_SLACK_WEBHOOK` | Slack alerts |
| `AUTOPILOT_WEBHOOK` | Alerts to a different web service |
| `AUTOPILOT_STATUS_TOKEN` | Sets the token of the status page. Without it, each run makes a random token. A page on an address that is not local needs it |
| `AUTOPILOT_PLAIN=1` | Removes the pinned status row at the bottom of the terminal, and the color. `status` and the page still show the status line |
| `NO_COLOR=1` | Removes the color. Claude Code sets this value for its tools, so a window that a build opens from Claude Code ignores it. Use `AUTOPILOT_PLAIN=1` there |
| `AUTOPILOT_NO_BROWSER=1` | Does not open the browser |
| `AUTOPILOT_NO_AUTOFIX=1` | Stops every automatic install and repair |
| `AUTOPILOT_CLAUDE_BIN` | The path to the `claude` program. Autopilot also finds `claude` in `~/.local/bin` when the PATH is old |
| `ANTHROPIC_API_KEY` | Use an API key instead of a subscription. Also set `usage.billing: api` |

The checks and the deploy commands get no login, token or alert variables unless the step declares them (`deploy.env_pass` for deploy).
Your deploy commands get `AUTOPILOT_REF`, `AUTOPILOT_PHASE` and `AUTOPILOT_ENV`. The rollback command gets
`AUTOPILOT_PREV_REF`. The smoke command also gets `AUTOPILOT_URL`.

## Files

**In `.agent/`:**

| File | Content | In git |
|---|---|---|
| `project.yaml` | All settings | Yes |
| `plan.yaml` | The phases and the tasks. Ids use letters, digits, `_` and `-`, at most 40 characters | Yes |
| `BRAIN.md` | The architecture and the rules. Each session reads it | Yes |
| `DECISIONS.md` | The log of decisions | Yes |
| `HANDOFF.md` | What the last session did, and what is next | Yes |
| `FOLLOWUPS.md` | Problems that sessions found outside their task | Yes |
| `history/` | One file for each finished task and phase | Yes |
| `history/<phase>/PROOF.md` | The full evidence of the feature check of the phase, and a `## Not proven` list (criteria that no changed test mentions, tasks with no check command, features not checked, scope added) | Yes |
| `history/<phase>/proof.svg` | W9: the proof card of a closed phase, a 600x200 SVG with the project name, the phase, tasks merged of total, features verified, the cost and the date. No outcome word: the run has not ended when a phase closes | Yes |
| `history/<phase>/BADGE.md` | W9: the markdown image line `![Built by Autopilot](proof.svg)` for the phase folder and the repo-relative path `.agent/history/<phase>/proof.svg` to paste into the README | Yes |
| `audits/` | The audit reports | Yes |
| `REPORT.md` | The live status. A `Not verified` line counts the tasks with gate warnings and the features with no check | No |
| `status.token` | The random token of the status page, mode 0600. The page link ends with `?token=` and this value. New projects ignore it in git | No |
| `run.json` | The journal of the active run. At the end it has `word`, the outcome word. `pid` is the process of the run; `beat_at` is written every 30 seconds while the run lives, also during a long session. `status: running` with a `pid` that is gone shows as `DEAD since HH:MM` (time of `beat_at`, else `updated_at`) in `ap status`, `ap watch`, the end screen and the status page; the next command is `ap start`. A run.json without `pid` still shows ON. `heartbeat_at` is the time of the last runner event, written at most every 10 seconds. `current_at` is the time when the gate line or the start-check line was written. `version` is the Autopilot version of the run | No |
| `state.db` | The progress, the sessions, and the cost | No |
| `logs/` | The log, the session logs, and the crash reports. The log rotates at 10 MB and Autopilot keeps three old copies | No |
| `STOP` | The stop flag from `autopilot stop`; the first line `now` means `ap stop --now` | No |
| `inbox.jsonl` | Every line that you type to `ap` and its reply, append-only: `{t, id, text, kind}` for a typed line, `{t, id, reply, partial}` for a reply. The last reply line of an id has `partial: false` | No |
| `helper.lock` | Allows one helper model call at a time | No |

**Task key `status` in `plan.yaml`:** `status: done` says the work exists already (in the code or the git log). When the task is new, or still pending, Autopilot records it as done with the note `done before Autopilot`. It never changes a task that is running, blocked, skipped or done. If you remove the key later, the task stays done. `status: dropped` says the item left the plan document; Autopilot skips the task and keeps it in the file. Any other value is an error that names the task.

**Plan source sync:** `plan_source: FILE` in `plan.yaml` names your plan document, and `onboard --plan-doc` writes it. At each start and at each phase close, Autopilot compares the file with the text it planned from. When the file changed, one replan session gets only the diff, adds new items as tasks, updates changed ones, and drops removed ones. It prints `Plan source changed: 2 new, 1 changed, 0 dropped.`, and an interactive start waits for Enter.

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
| `gate` | The checks | `test_globs`, `ci_files`, `protected`, `new_file_reasons` (default `true` in new projects, off when the key is missing), `scope_always` (docs a task may change outside its scope, with no scope addition and no warning; default `REFERENCE.md`, `CHANGELOG.md`, `HOWTO.md`, `README.md`), `tests` (`changed` default, or `full`: which tests the gate runs per task; the phase close always runs the full command; a value other than these two is an error). Exception (W45): a change in `autopilot/templates/`, `autopilot/prompts/`, `autopilot/config.py` or `autopilot/schemas.py` runs the full test command. A change to `README.md`, `HOWTO.md`, `REFERENCE.md`, `GUIDE.md` or `ARCHITECTURE.md` adds each test file that names that doc. The review session reads the gate output and does not run tests |
| `context` | The task prompt | `scope_chars` (60000, W27): most characters of the `## Files in scope (current content)` block. It holds the text of each file that `files_in_scope` names exactly, in list order. A missing file is `(new file)`, globs are not expanded and `gate.scope_always` docs are left out. A file that does not fit gives its first 80 lines and its `def` / `class` lines with line numbers. |
| `agent` | The agent CLI | `backend` (unset = preflight detects the CLI, see below; else `claude_cli`), `preset`, `max_turns` (200), `session_timeout_sec` (3600), `env` (variables for the session, for example `CLAUDE_CONFIG_DIR`), `fallback` (default empty; see below), `user_config` (false) |
| `onboard` | The discovery pack of the `onboard` session | `test_timeout_sec` (300): time limit for the one test run that the pack records |
| `sandbox` | Where the agent runs: `mode` `off`, `allowlist` (Claude Code's own sandbox with the network allowlist) or `docker` (each session in `docker run --rm` with only the worktree at `/work`, its git folders (the shared one read-only) and a temp login folder mounted; never the home folder; secret variables pass by name only). A missing `mode` follows `enabled` | `mode`, `enabled` (false), `allowed_domains`, `image` (needed for `docker`; the image must have `claude` on PATH), `network` (`bridge`) |
| `models` | The model for each role | `ladder`, `fixer`, `auditor` (opus), `replanner` (sonnet; opus when a pending task's `files_in_scope` matches `escalate.load_bearing`), `unstick` (sonnet), `review` (opus), `helper` (haiku: the short answer to a typed question, at most 20 calls for each run) |
| `usage` | The 5-hour window | `billing` (subscription), `reserve_pct` (15), `opus_by_pct` (0) |
| `upgrade` | The update that runs by itself | `auto` (true): before `ap run` or `ap start`, once a day, a release install gets the newest release and starts the command again; `false` turns it off. `AUTOPILOT_NO_AUTO_UPGRADE=1` does the same for one shell |
| `budget_usd` | Cost limits | `per_session` (8), `per_task` (20), `per_phase` (150), `daily` (200), `total` (5000) |
| `profile` | How much checking each task gets | `lean` (new projects) or `full` (a missing key) |
| `retries` | Attempts | `max_attempts_per_task` (3), `resume` (true) |
| `unstick` | The diagnosis of a blocked task | `enabled` (true), `after_attempts` (2) |
| `audit` | The completion audit and the end-phase sessions | `timeout_sec` (1200: the audit, functional check and phase docs sessions stop after this; a stopped completion audit keeps its notes as a partial report, sends them to NEEDS-YOU with the event `audit: partial after <n> s`, and the run goes on), `max_new_tasks` (15) |
| `decide` | Design choices before risky tasks | `enabled` (true), `risks` (critical; a task with `needs_decision: true` always gets one; add `high` to decide for every high-risk task) |
| `review` | A read-only review of the diff before the merge | `enabled` (true), `scope` (critical; all = every task above low risk; new projects get all), `effort` (high) |
| `research` | Web research for a task | `enabled` (true), `dir` (docs/research) |
| `functional` | The feature check at the end of each phase | `enabled` (true), `init` |
| `escalate` | An early move to a stronger model | `on_timeout`, `max_diff_lines` (300), `max_diff_files` (5), `load_bearing`. W41: the two diff limits count code only (not test files, not `gate.scope_always` files, not `.agent/`). A failure whose problems are all growth, scope or lint stays on the same model, and the retry names the problem. With `gate.file_growth` on, the task prompt lists each scoped file within 40 lines of its growth limit (`autopilot/gate.py: 16 lines left of 400`). |
| `scheduling` | The order and parallel work | `phase_dependency` (soft), `parallel` (the template sets 1; unset = 3 with a test command in direct mode, else 1). Only `low` and `medium` first attempts join a batch. Two tasks that share a file never run together. A task with an empty `files_in_scope` runs alone. |
| `git` | Push and pull | `push` (false), `pull` (true), `mode` (direct or pr). With `mode: pr`, a task with gate warnings or a criterion without a test opens a draft pull request. The body lists them under `## Not proven` ("Nothing" for a clean task, which opens a ready PR). Autopilot marks the draft ready when CI is green, then merges. |
| `intake` | Fix tasks from GitHub | `enabled` (false), `label` (autopilot), `poll_minutes` (30) |
| `deploy` | Staging and production | `cmd`, `health_url`, `rollback_cmd`, `env_pass` (names of extra variables a deploy command needs) |
| `notify`, `chat` | Alerts and Telegram commands | `events` (an event name such as `budget_forecast` turns its push on), `chat.enabled` (false) |
| `needs_you` | The questions file | `path` (docs/NEEDS-YOU.md), `wait` (true) |
| `quality` | Model suggestions | `every` (20) |
| `replan` | Plan updates | `enabled` (true), `every_n_phases` (5) |

Sessions do not load your own Claude Code settings, plugins, hooks, or MCP servers. Your `CLAUDE.md` still loads,
and the project's own `.claude/settings.json` and `.mcp.json` also load. Thus a run acts the same on each computer.
Your own settings add cost and context to each session. To load them too, for example a proxy or an
`apiKeyHelper`, set `agent.user_config: true`.

Runner detection: this runs when the project's own `.agent/project.yaml` sets no `agent.backend`, `agent.command` or
`agent.preset`. Preflight (before `ap run` and `ap onboard`) detects the first installed, logged-in CLI in the order of
the runner table and writes it. The order is `claude`, `copilot`, `codex`, `agent`, `kiro-cli`. The program `agent` is
Cursor; its old name `cursor-agent` still counts. It prints `runner: <name> (found on PATH)`. For `claude` it writes
`backend: claude_cli`; for a different CLI, `backend: command` and the preset. When it finds no CLI, it prints one line
per runner with the install command for this system, then stops. It never names one runner first. A value that you set
is never changed. When no CLI is logged in, preflight uses the runner that `ap setup` chose on this computer.

Runner table (one source, `autopilot/doctor.py`): every runner fact lives in one table. Each row has the program name,
the install command per system, the login command, the read-only status command and the token variables (presence
only; a value is never read or shown).

| Runner | Program | Login command | Status check | Token variables | You pay for |
|---|---|---|---|---|---|
| `claude` | `claude` | `claude auth login` | `claude auth status` | `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` and the gateway variables | a paid Claude plan (Pro or Max) |
| `copilot` | `copilot` | `copilot login` | `gh auth status` | `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` | a paid GitHub Copilot plan |
| `codex` | `codex` | `codex login` | `codex login status` | `CODEX_API_KEY` | a ChatGPT plan |
| `cursor` | `agent` (`cursor-agent` before) | `agent login` | `agent status` | `CURSOR_API_KEY` | a Cursor plan |
| `kiro` | `kiro-cli` | `kiro-cli login` | `kiro-cli whoami` | `KIRO_API_KEY` | a Kiro plan or an AWS Builder ID |

Copilot in VS Code is not a command-line tool. Autopilot needs the Copilot CLI, which uses the same subscription.

Runner login: before the first session, preflight checks that the configured runner is logged in with its own
subscription. It uses the status check of the table, with a 20 second limit, and no prompt. A failed check prints the
one login command (for example `codex login`) and stops. Autopilot never opens a browser and never reads a credential
file. Runners that need an API key (`gemini`, `aider`, `opencode`) are not supported.

Python setup: preflight never runs a bare `pip install` on the system Python. When a `requirements*.txt` file has no
environment, preflight runs `python -m venv .venv`, then installs with the `.venv` Python. An active environment
(`VIRTUAL_ENV`) or a project environment (`.venv`, `venv`, `env`) is used as is. `commands.setup` stores these commands.

### Local model (`openai_compat`)

`agent.backend: openai_compat` sends each session to an OpenAI-compatible `/chat/completions` endpoint, such as Ollama or LM Studio. One non-streaming request per session. The model cannot run tools, so it writes each file as a fenced block and Autopilot writes the files into the worktree; the gate then runs the tests and the checks.

| Key | Default | Meaning |
|---|---|---|
| `agent.base_url` | `http://localhost:11434/v1` (Ollama) | The endpoint. `/chat/completions` is added to it. Loopback addresses skip the environment proxies. |
| `agent.model_map` | none | Maps the ladder names (`haiku`, `sonnet`, `opus`) to the model names of the server. A name not in the map is sent as is. |
| `agent.api_key_env` | none | The name of an environment variable with a Bearer token. Only the name is stored; the key is never logged. |

File block format: the info line of the fence is `path: <relative path>` (for example ```` ```path: src/app.py ````). Use forward slashes. A path that is absolute, has `..` or `.git`, or resolves outside the worktree refuses the whole answer, and nothing is written. A file that contains three backticks gets a block of four. The report is a ```` ```json ```` block after the files. `ap doctor` and `ap preflight` print an `endpoint` row: OK when the endpoint answers, WARN when it does not (never FAIL, so a run is not stopped).

Agent presets: with `agent.backend: command` and no `agent.command`, `agent.preset` selects a ready-made command.
`agent.model_map` gives the model option (`-m`, or `--model` for the `kiro`, `cursor`, `aider` and `copilot` presets). The `copilot` preset maps `haiku` to `claude-haiku-4.5` by itself; `sonnet` and `opus` use Copilot's default model until you map them.

| Preset | Runs | The prompt goes in |
|---|---|---|
| `codex` | `codex exec` | standard input |
| `gemini` | `gemini -p` | standard input |
| `opencode` | `opencode run` | standard input |
| `kiro` | `kiro-cli chat --no-interactive --trust-all-tools` | standard input |
| `cursor` | `agent -p --force --trust` | standard input |
| `aider` | `aider --message-file ... --yes-always --no-auto-commits` | a temporary file outside the project |
| `copilot` | `copilot -p ... --allow-all-tools --no-ask-user -s --add-dir ...` | a temporary file outside the project, named in the prompt |

`agent.fallback` (default empty = off) lists runner presets, for example `[codex, copilot]`. When a session ends on a
usage limit that resets in more than 30 minutes, Autopilot commits the work, writes `HANDOFF.md` (goal, done, next, failing
tests) and starts the first runner of the list on it. That runner needs its own subscription login. Later tasks use it
until the first runner's window resets.

An `agent.fallback` entry is a preset name, or `{claude_cli: {CLAUDE_CONFIG_DIR: <folder>}}`. The second form runs the same runner on a second Claude login. The switch happens between sessions. Each login keeps its own usage window. When both logins are at a limit, the run waits for the earlier reset. `ap doctor` shows one login row for each folder. `ap validate` prints the fallback chain. To set it up, read the [how-to](HOWTO.md#use-a-second-claude-login-at-a-usage-limit).

In your own `agent.command`, `{prompt_file}` gives the path of a temporary file with the prompt, and `{model_flag}`
gives the model option. The prompt also goes in on standard input. The `kiro` and `cursor` presets approve all tools,
so run them in a virtual machine or a container.

When the `gh` CLI is logged in, each commit of Autopilot uses your GitHub no-reply address as the author and the
committer. Your git settings do not change.

Autopilot supports these stacks: python, node, go, rust, java, docker, static, and generic. Each project type works
when you put its build and test commands in `commands`.

### Docker mode

`sandbox.mode: docker` runs each Claude Code session in a plain container, not in Claude Code's own sandbox. Build the
image once from the repository root, then name it in the project:

```
docker build -t autopilot -f deploy/Dockerfile .
```

```yaml
sandbox:
  mode: docker
  image: autopilot       # needs `claude` on PATH (deploy/Dockerfile has it)
  network: bridge        # the default; the API host must be reachable
```

- `sandbox.mode`: `off`, `allowlist` (the same as `sandbox.enabled: true`) or `docker`. A missing mode follows `enabled`.
- `sandbox.image`: the image name. Required for `docker`; the config check refuses a missing name.
- `sandbox.network`: `bridge` (the default) gives the container open egress unless `sandbox.enabled: true` also turns on the allowlist.
- `ap doctor` prints `docker: found <version>` in this mode (`docker: <version> (Docker Desktop)` with Docker Desktop), or `FAIL` when the `docker` command is missing.
- Docker mode needs the `claude_cli` backend. It works with Docker Desktop on Windows, and on Linux, macOS and WSL2. `allowlist` is not supported on native Windows.
- On Windows, Autopilot copies the login from `CLAUDE_CONFIG_DIR` of the session environment, else from `%USERPROFILE%\.claude`, into a temp folder. The container mounts that folder at `/claude`.
- On macOS the login sits in the Keychain, not in `~/.claude/.credentials.json`, so set `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` for docker mode there.

### Lean profile

Set `profile` to `lean` or `full` in `.agent/project.yaml`; new projects start with `lean`.
Under `lean`, a task writes one smoke test for each criterion. In every profile the task gate runs only the tests of the changed modules (`gate.tests: changed`, the default); `gate.tests: full` runs the full command per task.
`lean` allows one retry, then parks the task in "Questions for you"; it also turns off the periodic and the completion audit, and the phase check runs no variations.
`lean` cuts `BRAIN.md` to 6000 characters and the decisions to 2000, and `autopilot audit` runs the audit on demand.
`autopilot report --tokens` shows the tokens and the cost of each step type; the total equals the state total.
The trade-off: a regression shows at phase close, not for each task, and the merged-result gate keeps `main` green.

## Gate guards

The gate runs these guards on each task before the checks. A guard that finds a problem fails the attempt.

| Guard | Finds |
|---|---|
| Deleted test | A test file that the change deletes |
| Renamed test | A test file that moves to a path that is not a test path |
| Fewer tests | A test file with fewer test functions than before |
| Fewer assertions | A test file with fewer assertions than before |
| Skip marker | A new skip or focus marker in a test |
| Collection hook | A new hook in `conftest.py` that changes which tests run |
| CI file | An added, changed or deleted CI pipeline file (`gate.ci_files`) |
| Test settings | A removed test setting, or an added `--ignore`, `--deselect` or `-k` in a test setting file |
| Protected file | A change to the plan, the settings, the questions file, the backlog, or a path in `gate.protected` |
| Secret scan | An added line that looks like a key, a token, or a password. When the flagged file is a test file, the problem adds the rule: build a fake secret from pieces, for example `'sk-' + 'a' * 24` |
| Empty change | No changed files, unless the task has `allow_no_changes: true` |
| Kill by name | A Bash or PowerShell tool call in the Claude Code session log that runs `taskkill`, `pkill`, `killall` or `Stop-Process`, also behind `sudo`, `env`, `cmd /c` or `powershell -c` (up to 5 named). Text in the agent's messages, `kill <pid>`, `taskkill /PID <n>` and `Stop-Process -Id <n>` do not count: they stop one process by its number. Every Claude Code session also gets the deny rules `Bash(taskkill:*)`, `Bash(pkill:*)`, `Bash(killall:*)` and `Bash(Stop-Process:*)`, even when `agent.disallowed_tools` sets its own list. Logs of `command` backends are not checked |
| Child processes on timeout | Windows: every command and session runs in a job object (kill on close); a timeout calls TerminateJobObject, then `taskkill /F /T`. If the job cannot be created, one warning is logged and only `taskkill /T` runs. POSIX: the process group is killed |
| Red main | Every new commit on main (run start, a docs/receipt/needs-you commit, a pull) is tested once with `commands.test`, before the next task starts; task merges are not tested again. The result is cached by commit. A red main sends a `main_red` event naming the failing test, runs the fixer and a corrective phase once, and if main is still red when no task can run, the run ends with `main is red: <test>` and the word FAILED |
| `failing_before` | The task report may list `failing_before`: tests the agent saw fail before its change. Each name is looked up in main's test result (the same once-per-commit result as above). A name that passes on main fails the attempt with `failing_before lists tests that pass on main: <names>`. A name that fails on main, on a normal task, puts the task back to pending without counting the attempt, and main is checked and repaired first. A fix task, or a project with no finished task yet, keeps going |
| New file | An added file with no reason in the report field `new_files`. Test files (`gate.test_globs`) and files in `.agent/` need no reason. A move or a rename needs no reason. The problem quotes the rule, and the retry prompt gets it. This guard runs when `gate.new_file_reasons` is `true`. It is `true` in new projects and off when the key is missing |

**Kept diff after a scope or test failure.** When an attempt fails the gate only on `outside files_in_scope` or `scope_additions` lines, or only on a failed test command, Autopilot keeps the branch and its changes. The retry prompt says "The diff is kept" and asks the session to add the scope reasons or fix the failing tests, not to start over. A protected-file change, a secret, a kill by name, a test-tamper finding, a review finding, a timed-out or stuck session, an escalation to a stronger model, an unstick session and a park still reset the code to the state before the attempt.

A task with `allow_test_changes: true` gets the test guards as warnings, not as failures. The paths of test files
come from `gate.test_globs`.

### Phase docs session

When a phase closes, one docs session may edit `README.md`, the RCA log, `docs/DEVELOPING.md`, `HOWTO.md` and files under `docs/`. Python then checks the result: the scope, the secret scan, and the project test command (`commands.test`, the full suite). A change to any other file, a secret, or a red test drops the whole result. The run records the event `<phase>: result dropped (tests: <first failing line>)` and main stays as it was. A project with no test command commits the result after the scope and secret checks. The session edits the section that already covers a change; a result that adds a second `#` or `##` heading with the same text as one in the same file (a second `## Safety`) is dropped with the event `<phase>: result dropped (duplicate heading in README.md: ## Safety)`. Repeated `###` headings, headings in code blocks and duplicates already on main do not count. The log line `docs session for <phase>: <file>:<line> matched <pattern> and was redacted` names each redacted line. It never shows the value.

## Models

**The model for each attempt of a task:**

| Task risk | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| low | sonnet | sonnet | opus |
| medium | sonnet | sonnet | opus |
| high | sonnet | opus | opus |
| critical | opus | opus | opus |

This is the template ladder of a new project (`models.ladder`; `critical` lists two steps and the last one repeats).
It follows the run of 2026-10-13: Haiku took 20 to 28 minutes per task and Sonnet 5 to 7 at the same cost with no
retry; Opus took 25 to 47 minutes and 2 of 5 tasks were retried. The review of every task is the guard. A project
whose `project.yaml` has no `models.ladder` keeps these values too. `ap audit --ladder` measures your own runs.

A retry on the same model continues the failed session. A retry on a different model starts a new session.

When the Claude CLI prints its final `result` event, Autopilot waits 10 seconds for the process to exit. Then it stops the process tree, and the session counts as finished. The log line is `session ended at its final answer; its child processes were stopped`.

**The model for each role:**

| Role | Model | Job |
|---|---|---|
| Fixer | sonnet, then opus | Repairs `main` when its checks fail |
| Unstick | sonnet | Finds the cause of a blocked task. It can search the web |
| Decide | opus | Compares 2 or 3 designs before a critical task or a task with `needs_decision: true` (`decide.risks`) |
| Research | sonnet | Writes web research notes for a task |
| Verifier | sonnet | Tries each feature at the end of a phase, then tries one variation to break it |
| Auditor, onboard | opus | Audits the app, writes the first plan |
| Plan update (replanner) | sonnet; opus when a pending task touches a load-bearing path | Updates the plan |
| Triage | haiku | Makes a task from a GitHub issue, with no tools |

## Usage and budget

- **5-hour window:** Autopilot reads your real usage from Claude Code. This figure includes your own use. When only
  15% is left (`usage.reserve_pct`), the run pauses until the window resets. This keeps some usage for you.
- **Other agent CLIs:** they give no usage figure. Autopilot then counts its own cost against `usage.window_usd`.
- **Weekly limit:** you get one alert when the weekly limit passes 90%.
- **Usage limit:** the run sleeps until the reset, and sends an alert. This does not count as a failed attempt.
- **Cost limits:** the `budget_usd` limits apply to each session, task, phase and day, and to the total. When the
  daily limit is reached, the run sleeps until midnight.
- **Budget forecast (W43):** after each task, Autopilot projects the end cost: the spend so far plus, for each
  task still to run, the median cost of the finished tasks of the same risk (of all finished tasks when that risk
  has none). When the projection passes `budget_usd.total`, one `budget_forecast` event per run says
  `$18.40 spent, about $35 at the end, cap $20` (add `budget_forecast` to `notify.events` to get it on your phone).
- **Total cap:** with `usage.billing: api` the run stops at `budget_usd.total` (word BUDGET_STOP). With a
  subscription the cap is soft: the active task finishes, then one NEEDS-YOU question (kind `budget`) asks
  "Raise the cost cap to $X (the forecast) or stop?" and the run waits like any open question (it ends BLOCKED when
  `needs_you.wait` is false). Answer with a number to raise the cap, or with words and no number to stop
  (BUDGET_STOP). `ap budget <usd>` also raises it and closes the question; when the spend passes the new cap, the
  run asks again.
- **Token report:** `autopilot status` and `.agent/REPORT.md` show the tokens and the cost for each model.
- **Model suggestions:** after each 20 finished tasks, Autopilot suggests a less expensive model where the data
  shows that it is safe. You make the change.

## Run outcome

Each run ends with one word. Autopilot writes the word to the state (meta key `outcome`, empty while a run is
active), to a `run_end` event (`<word> <outcome text>`), to the log (`outcome: <word>`) and to `run.json` (`word`).
The word is the first word of the `run_done`, `fatal` and `budget` alert text. The window title and the live page
show it after `Done`, for example `Done VERIFIED`. `ap status` shows `outcome: <word>`.

| Word | Meaning |
|---|---|
| `VERIFIED` | The plan is complete and no task is parked |
| `BLOCKED` | One or more tasks are parked, or a decision waits for your answer |
| `STOPPED` | You stopped the run by hand: Ctrl+C, `ap stop` or the `.agent/STOP` file. `ap watch` shows the word after `Stopped` |
| `BUDGET_STOP` | A limit that you set stopped the run: a budget cap, the session limit or a usage-window wait |
| `STALLED` | Work remains that cannot start, the service was down, or the same error came from three tasks |
| `FAILED` | A fatal condition: a config error, a plan that does not load, an expired login, or a repeated crash |


## Tour recording

`examples/tour/events.jsonl` is a recorded run (`ap tour` plays the copy in `autopilot/templates/tour/`; keep the two equal): one JSON object per line, with `t` rising. `scripts/make_tour.py`
builds it from `examples/self-build` (history files and `features.json`); run it again to get the same file.
The script scrubs paths, addresses and `@`, so the file holds no local data. It has more than 40 events, with no user path, mail address or secret.

| Key | Meaning |
|---|---|
| `t` | Seconds from the start of the run (number, rising) |
| `kind` | `run_start`, `phase_start`, `task_start`, `session`, `criterion`, `files`, `gate`, `task_done`, `phase_done`, `feature`, `run_end` |
| `message` | Plain text, up to 300 characters |
| `task_id` | The task id, or an empty string |
| `state` | `running`, `checking`, `done` or `failed` |
| `usage` | Object with `cost_usd` on `task_done`, `phase_done` and `run_end`; empty otherwise |

`examples/tour/PROOF.md` is the proof that goes with it: the outcome word and the Not proven list.

## Proof features

### Not proven list

Each phase writes `history/<phase>/PROOF.md` with a `## Not proven` section. It lists each acceptance criterion that
no changed test mentions, with its task id. A criterion is covered when a three-word window of its text
appears in the task's changed test files. Those files come from the `## Files changed` list of the
task's history file. Tasks with no verify are listed only when the project has no test command. When every criterion
has a test, the section holds one sentence that says so. Read this list to see what a green build did not check.

### Fresh-context review

A fresh session reviews each finished task before it merges. Set `review.scope` in `project.yaml` (see
[Settings](#settings)). With `scope: all`, every task above low risk gets a review, and a finding blocks the merge.
With `scope: critical`, or no key, only critical tasks get one. That is the code default, so old projects keep today's
behavior. `ap init` writes `scope: all`. Any other value is an error with a plain message. The reviewer sees only the
task spec (with the acceptance criteria), the diff and the gate's test output. It sees nothing from the build session.

**Review list (W40).** The findings of a failed review are kept for the task as a numbered list, and the retry prompt shows them under `Fix exactly these review findings, nothing else:`. The next review gets the same list and reports `fixed` or `open` for each number (`listed`). The task fails only when a listed finding is still open or a new defect breaks an acceptance criterion; any other new defect goes in `followups`, is appended to `.agent/FOLLOWUPS.md` as `review: ...`, and the task merges. When a medium task's change passes 8 files or 250 lines (tests and `gate.scope_always` files excluded), the failed review adds a `split signal` line and the retry stays on the same model.

**Feature contracts (W36).** A page in `features/` (committed, at the repository root) is the contract of a matured feature. It has five sections: `## What it does`, `## Rules`, `## Files`, `## Tests that guard it` (exact test names) and `## Changes` (dated lines). When a task's `files_in_scope` names a file of a page's `## Files` list (a glob in the scope matches too), the task prompt gets the page under `## Feature contracts (keep them, or say why in the report)`, capped at 8000 characters. Today: `features/watch-screen.md` (`ap watch`) and `features/gate.md` (the gate guards and the kept diff). The gate guards each contract as committed at HEAD (W36b): a diff that deletes a test named under `## Tests that guard it` fails with `contract <id>: test <name> removed`, fewer tests in a named file with `contract <id>: test count dropped in <file>: a -> b`, a deleted page with `contract <id>: page deleted`. These fail even with `allow_test_changes`, unless the task report has `contracts: [{"id": "<id>", "status": "changed", "why": "..."}]` with a non-empty `why` (`kept` lifts nothing). A renamed test file counts as deleted. A task that edits `features/<id>.md` must add a dated line (`- YYYY-MM-DD: ...`) under its `## Changes`, else `contract <id>: page changed without a new dated line under ## Changes`.

### Signed receipt

When a phase closes, Autopilot writes `history/<phase>/receipt.json` next to `PROOF.md`. The receipt holds a hash of
each phase file and a signature. The key is `~/.autopilot/receipt.key`. Autopilot makes it on first use, with mode
0600. It lives in your home folder (`AUTOPILOT_HOME` moves it), so it is never in the repository and never committed.
`ap verify` checks every closed phase offline (see [Commands](#commands)). An untouched phase prints `<phase> ok` and
exits 0. An edited file prints `<phase> CHANGED: ...` and exits 1. A different key gives `bad signature`. With no
receipt, it prints `no receipt found` and exits 1.

### Draft pull request

Set `git.mode: pr` in `project.yaml` and each task opens a pull request. If the gate gave a warning, or an acceptance
criterion has no test, the PR opens as a draft. Its body lists each item under `## Not proven`. A clean task opens a
ready PR, and the list says "Nothing." When CI is green, Autopilot marks a draft ready and merges it; the list stays
in the body. `git.mode: direct` works as before. See [Settings](#settings).

### Proof card and badge

When a phase closes, Autopilot writes two files next to `PHASE.md` in `.agent/history/<phase>/`. `proof.svg` is a
600x200 card. It shows the project name, the phase, tasks merged of total, verified features, the cost and
the date. It holds no absolute path, and it stays valid XML when a phase title has `<` or `&`. `BADGE.md` holds one
markdown image line, `![Built by Autopilot](proof.svg)`, and the repo-relative path
`.agent/history/<phase>/proof.svg`. Paste that path into your README to show the badge. The signed receipt covers both
files.

### Stop hook in the plugin

The Claude Code plugin (`plugin/`) adds a Stop hook in `plugin/hooks/hooks.json`. When Claude tries to stop,
`plugin/scripts/seal.py` runs two checks in the project folder. It runs the project test command (`commands.test` in
`.agent/project.yaml`, else `python -m pytest -q` when there is a `tests/` folder, else `npm test` when `package.json`
has a test script). It also checks each test file against HEAD: a test file with fewer lines than at HEAD fails. A
failure prints `{"decision": "block", ...}` and Claude keeps working. The test command has a 300 s limit. The hook
has a 330 s timeout in `hooks.json`, so the script's own timeout message prints first. The hook blocks at most 5 times
in one session. The count is kept in `autopilot-seal-<session>.count` in the temp folder. Turn the hook off with
`/plugin disable autopilot`. The hook runs only in projects that `ap init`, `ap quickstart` or a run registered on this computer. Autopilot's own sessions never load the plugin, so the hook never runs inside a build.
See [HOWTO](HOWTO.md#stop-hook-in-the-plugin).

### Routine

`examples/routine/prompt.md` is the prompt of a Claude Code Routine, a scheduled cloud run that runs one Autopilot
build with your laptop off. It sets `scheduling.max_sessions_per_run: 3` by a local edit of `.agent/project.yaml`, and
it tells the run not to commit that edit. Follow the steps in
[HOWTO](HOWTO.md#run-with-the-laptop-off-claude-code-routines). This path is not run live yet. Its commands are checked
by `tests/test_routine.py`, not by a live run.

## VS Code extension

`vscode/` holds a thin extension (not published yet). Commands `autopilot.start`, `autopilot.answer` and `autopilot.stop` send `ap start`, `ap answer` and `ap stop` to a terminal named Autopilot. The `autopilotStatus` view in the Explorer shows the status page of the run; it reads the port from `.agent/status.port` (default 8765) and the token from `.agent/status.token`, and says to run `ap` first when nothing answers. See `vscode/README.md`.

## Self-healing

A run stops only for a problem that needs a person. Each repair sends a `heal` alert.

| Problem | What Autopilot does |
|---|---|
| A newer release exists | Before `ap run` or `ap start`, once a day, a release install gets it and starts the same command again on the new version. The line names the way back: `ap upgrade --ref vX.Y.Z` |
| The code of a task fails its checks | Moves the task up `models.ladder` to a stronger model, then starts a diagnosis, then asks you. It builds the other tasks |
| `main` fails its checks | A fixer session repairs `main` before new work. It gets three attempts by default (`retries.max_fixer_attempts`) |
| A tool is missing | Runs the setup again. If the tool is still missing, one repair session repairs the setup. A run gets one repair session |
| The Claude CLI cannot start | Installs the CLI again the way you installed it, once, then runs the same session again. This is not a failed attempt. An npm install gets `npm i -g @anthropic-ai/claude-code`. A native install gets the installer from claude.ai. For a winget install, Autopilot shows `winget upgrade Anthropic.ClaudeCode` and does not run it |
| Claude is not logged in, or the network is unreachable | Waits 1, 5, 15, 30, then 60 minutes between tries, and runs the same session again. This is not a failed attempt. A login message tells you to run `claude`, then `/login`. A 5xx answer or a timeout follows the rules in "Errors in a running build" |
| The login ran out during a run | Checks the login again. If it failed, the run stops with `FAILED` and prints the login command. No try is spent, and the next start continues the task |
| The usage limit is reached | Sleeps until the window resets, for all billing types. The pause before the limit (`usage.reserve_pct`) is for a subscription only |
| The `autopilot` command is not on the PATH | Adds a launcher and corrects the PATH |
| The push to GitHub fails | Tries the push again after 30 seconds. Then it continues to build on your computer, and tries the push again at each commit |
| `main` is different from GitHub | Applies the local commits again on top of the GitHub commits |
| An old git lock file exists | Deletes the lock file and tries again |
| `plan.yaml` is damaged | Restores the last version that loads, from the last 30 commits on `main` that changed it |
| `state.db` is damaged | Restores the backup. Autopilot makes a backup at each run start |
| Autopilot stops with an error | Writes a crash report, then starts again from the saved state. It restarts 10 times at most. The same crash three times on one task parks that task |

**Unknown session errors (W29):** a failed task session whose error text matches no detector (usage limit, login,
network) and no line of the install error catalogue adds one JSON line to `unknown.jsonl` in `~/.autopilot`
(`AUTOPILOT_HOME` moves it). Fields: `date`, `cause` (`scope`, `tests`, `environment`, `limit`, `infra` or
`unknown`), `text` (secret values and token shapes replaced by `***REDACTED[...]***`, at most 2000 characters),
`count`, `runner`, `version` (the `ap` version), `project` (the folder name only, never a path) and `action`
(`retried`, `parked` or `healed`). The same wording (the first 200 characters) on the same day raises `count` on
that day's line. A known wording writes nothing. The file stays on your computer. `ap audit --signals` reads it.

**These problems still need you:**

- Your Claude login. Run `claude auth login`. Before the first session, `quickstart` and `run` stop when the login
  is missing. An API key or a gateway needs no login.
- A budget limit or a session limit that you set.
- A question in `docs/NEEDS-YOU.md`.
- A crash that occurs again and again. Send the report from `.agent/logs/crashes/`.

## Dashboard colours

`ap watch` and the status page use one colour for one meaning. A plain fact stays white. The test
`test_every_colour_has_one_meaning_and_only_the_headline_is_bold` fails when a colour gets a second meaning.

| Colour | Meaning | Where it appears |
|---|---|---|
| Green | Done or OK | Login `Pro` or `Max`, Status `Complete`, progress bar fill, Files added, lines added, Git and Checks `OK`, Size `This run (N tasks)` +N lines, Phase ✓, Live `The task is complete`, `✓ VERIFIED` at the end |
| Cyan | Running now | Status `In progress`, Phase ▶, Live test run, the state word in the title and the bar, the spinner while it turns, the running task row (cyan fill, bold) while the run is live |
| Yellow | Warning | Login `not checked`, Time over 2x the median task time, Risk `high`, Tries 2 or more, Try on the last try, Questions, Warnings, Retries, Last commit age over 10 minutes with a running task, usage bar over 75 percent, `stale`, `⏸ no change 45s`, Live note, Live wait over 60 s (dim), `⏸ BLOCKED`, `⏸ STOPPED` and `⏸ BUDGET_STOP` at the end |
| Red | Blocked or failed | Login check failed, Status `Blocked`, Risk `crit`, Error text, Blocked count, Files deleted, lines deleted, Git and Checks failure text, usage bar over 90 percent, Phase ✗, Live error line, `✗ FAILED` and `✗ DEAD` at the end |
| Magenta | Cost and usage | `Resets`, usage bars, Cost |
| Blue | Model name | Now model, Detail model, usage model names |
| Grey (dim) | Label, border, pending or zero | Labels, borders, Status `Pending`, Phase ○, Risk `low`, `waiting`, empty Error, zero counts, Live step verbs |
| Bright white | A value the eye lands on | Key counts, the next step |
| Bold | The one headline | The Now card title |

The running indicator sits before the state word in the title, in the bottom bar and in the Now panel title. It turns
only while the data file changes. After 30 s with no change it stops and shows `⏸ no change 45s` in yellow. When the
run ended it shows `✗ stopped 12:50` in red. A console without UTF-8 gets `|/-\`, `||` and `x`. The browser page
shows the same ring, paused when the data is stale. No other part of the window moves.

## Glossary

| Term | Meaning |
|---|---|
| Plan | `PLAN.md`, your description of the app. Autopilot makes `.agent/plan.yaml` from it |
| Phase | A group of tasks that gives one part of the app |
| Task | One unit of work. One session does one task |
| Digest | The short summary in the alert at the end of a run or at a stop. It shows the built tasks, the blocked tasks, and the questions for you |
| Session | One run of Claude Code with a new, empty context |
| Run | One `autopilot run`, from the start until the end or a stop |
| Checks | The build, lint, type, test, secret and test-tamper checks that Python runs after each task |
| Gate | The part of Autopilot that runs the checks |
| Blocked task | A task that failed all its attempts. The run continues with the other tasks |
| Fix task | A task that Autopilot adds to repair a failure, a gap, or a bug |
| Question | An entry in `docs/NEEDS-YOU.md` that only a person can answer |
| Completion audit | One session at the end of the plan that asks: is the app complete? It gets the last gate output on main (at most 6000 characters and the test counts) and does not run the suite again. The functional check and the phase docs session get the same block |
| Usage window | The 5-hour usage limit of a Claude subscription |

**Task time (W42).** The Time column of the dashboard is the sum of the task's session durations (a running session counts to now), not the wall clock from its first session to the merge. When the wall span is more than 2x that work, the row's data carries `took 24m (3 tries, first 15:12)` (hover text in the web view). The Size panel label `This run (N tasks)` counts the tasks merged since the run start.
