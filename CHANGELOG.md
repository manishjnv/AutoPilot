# Changelog

Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.
It is for one developer, or for a person with an idea and a developer friend.

Words in the entries: Claude Code (the coding agent that writes the code), the gate (the check after each step), a worktree (a separate copy of the project for one task), a subscription (a paid Claude plan), `plan.yaml` (the task list). Format: Keep a Changelog. One line per roadmap item, under Unreleased.
Bump rule: patch = a fix, minor = a roadmap item, major = a `plan.yaml` or `project.yaml` format change (with a migration note).
Release: run `python scripts/bump.py X.Y.Z`, then push the commit and the tag.

## [Unreleased]

- Q15: a project in OneDrive, a redirected Documents folder, on a network share or under `/mnt/<drive>` gets one sentence and one command in `ap setup`, a run start and `ap doctor --project`; new `ap move <target>` clones the project (`git clone --local`), copies `.agent/`, keeps the remotes, adds the new path to the recent projects and leaves a `MOVED.md` note in the old folder; `--yes` moves at once, with no terminal it only prints the command.
- Q21: `ap setup` adds eight pre-install lines (`found` / `fixed` / `skipped`): git dubious ownership (safe directory added), `core.autocrlf` on Windows (off for the project, `.gitattributes` written when missing), an API key in the environment (name only), clock skew over 3 minutes, under 1 GB free, git older than 2.30, a console that is not UTF-8, and a busy status-page port (the next free port is taken and named).
- Q13: the login address and code always print as text; WSL, SSH, a container, a snap desktop or a machine with no browser runs the headless login (`copilot login --device-code`, `codex login --device-auth`), a desktop opens the browser and prints the address too; `ap setup` offers the login for every runner.
- Q11: `ap setup` ends with one test prompt through the runner ("Reply with the single word ready."); a pass writes `verified: <date>` to `~/.autopilot/machine.json` and `project.yaml`, a fail prints one plain sentence and the next command; `--skip-probe` turns it off; `ap doctor --runner` runs it alone.
- Q14: each install error matches by exit code or error code first, a vendor error id second, and short keywords third; a German or French Windows message still gets its sentence because the hex code carries the match.
- CI: tests run in parallel (`pytest -n auto`, `pytest-xdist` in the dev extras), pip cache, docs-only pushes skip CI, a newer push cancels the queued run; the Release job builds without a second test run; `uv` installs the package in CI; the Windows 3.10 row runs nightly and on request, not on every push. Push to release went from about 35 minutes to about 10.

## [0.5.1] - 2026-10-12

- Fix: `install.ps1` under PowerShell 5.1 parses the archive address (single quotes); two Windows-only test fixes. The v0.5.0 release assets carry the old script; this release replaces them.
- Release tooling: `scripts/bump.py X.Y.Z` commits and pushes the bump; `--tag` tags only when CI is green on that commit; both steps use the GitHub noreply identity.

## [0.5.0] - 2026-10-12

- T1: the install scripts and the code move as one unit: `MIN_VERSION` in both scripts equals the package version, a script from `main` installs the archive of `main` (no git needed), a release copy tries PyPI first; an Autopilot older than the script is replaced, never trusted.
- T2: `ap` updates itself once a day after a short command, in a process that starts after `ap` has ended; never during a build, in CI, in a git checkout, or with `upgrade.auto: false` / `AUTOPILOT_NO_AUTO_UPGRADE=1`.
- T3: `ap uninstall --all` removes the rights, `~/.autopilot` and the package; `--dry-run` lists the steps.

- Q6: `ap setup` prints one environment line each (`found`, `fixed`, `skipped`) for `~/.local/bin` off PATH (fixed in the profile or the user PATH), proxies, a corporate CA, offline, ARM and 32-bit Windows, a space or non-ASCII home, OneDrive or a network share, a read-only home, root or sudo, a conda or pyenv shim, an old uv, two Autopilots, WSL 1 and `/mnt` projects, a Windows CLI seen from WSL, two copies of a CLI, a token over a stored login, a missing git identity (set from `gh api user`), Windows long paths, leftover CLI folders.
- Q10: a command outside a project says `this folder is no project, using the last one used: <path>`; `ap doctor` names the install source (editable checkout, uv tool, pip); `python -m autopilot --version` says `autopilot`, not `__main__`.
- Q8: `tests/test_setup.py`, `tests/test_install_errors.py` and `tests/test_install_scripts.py` run every runner as a fake script on a temporary PATH; the install workflow has four jobs (Linux, macOS, Windows PowerShell, Git Bash) and each real install names the runner.
- Q7: the README has one install line per shell (PowerShell, bash, CMD) and the `pip install dev-autopilot && ap setup` line; HOWTO points the checksum check at the `SHA256SUMS` asset of the release; REFERENCE documents `ap setup`, the runner table and the exit codes; `.gitattributes` fixes the line endings of `*.ps1` and `*.cmd`.
- Q5: thin install scripts: four steps (pre-check with a reachability probe, uv, Python, the package), then `ap setup`; Git Bash hands over to `install.ps1` with the same options; a Schannel curl that fails with 35 retries once with `--ssl-no-revoke`; new `install.cmd` for CMD; the scripts install no runner.
- Q4: install errors in plain words: every install step is captured, the raw text goes to `~/.autopilot/install.log` (token values scrubbed), the screen gets what failed, one sentence and one command; a catalogue of 20 lines (Schannel revocation, no host, timeout, 403, 404, disk full, permission, not on PATH, old Node, Store Python, execution policy, each runner's logged-out and no-plan wording); exit codes 0 ok, 1 failed, 2 usage, 3 choice needed.
- Q3: `ap setup` scans the machine (read-only), prints `found`, `will install` and `skipped` lines, asks one question at most ("Which AI do you pay for?", with a default from a login, a token or a footprint), installs that one CLI, checks its login and writes the choice; `--dry-run`, `--runner`, `--yes`, `--skip-login`, `AUTOPILOT_RUNNER`; exit 3 when a choice is needed and there is no terminal; `ap install` runs it last.
- Q2: `agent.preset: copilot` runs the GitHub Copilot CLI (prompt in a temp file named in `-p`, `--allow-all-tools --no-ask-user -s --add-dir`); the login check counts a token variable or `gh auth status`; `haiku` maps to `claude-haiku-4.5`; a premium-request limit message counts as a usage limit (flags from the docs of 2026-10-12, not run live: Q9).
- Q1: one runner table in `doctor.py` (claude, copilot, codex, cursor as `agent`, kiro) feeds detection, the login check, `ap doctor` and the missing-runner message, which now lists every runner with its install command instead of "Install Claude Code".

## [0.4.0] - 2026-10-12

- O10: `profile: lean` is the default for new projects after the clean measure (39.5 percent fewer tokens per task, every task done); an old `project.yaml` without the key stays `full`.
- O11: a docs session at each phase close writes the app's `docs/RCA.md`, README feature sections and `docs/DEVELOPING.md`.
- O1: `scope_additions` count from attempt 2 only, at most 3 files, and each one is recorded in the task history, `PROOF.md` and the dashboard.
- N8: the Windows rights step runs from `%ProgramData%\Autopilot` with an administrator-only ACL; `ap uninstall --rights` removes it.
- N12: `high` first attempts join a parallel batch when their `files_in_scope` are disjoint; a colliding task is held, not the whole batch.
- J13: terminal window v2: all phases shown, no wrapped row, data age and `stale`, no value in two panels, task time over every attempt, ETA with its basis, colour map v2, a running indicator.
- J14: a repeated final report is not stuck; the own fix runs once before a question; questions are short with a default choice; `ap watch` survives a crash restart.
- J15: every public document opens with three plain sentences: what Autopilot is, what you do, what you get.
- N5.2: `ap upgrade` and `ap install`; release notes start with a heading.
- N5.3: the release workflow publishes to PyPI with trusted publishing (`uv tool install dev-autopilot` once the owner registers the project).
- N5.4: the install scripts take no administrator rights; the first `ap` run logs you in to Claude by itself.
- N5.5: a plan with no owner or critical task starts without a question (`ap --ask` keeps it); the first run opens the status page once; the plugin installs `ap` when missing; `IDEA.md` is read as the idea.
- N11: `agent.fallback` hands a task to the next runner at a usage limit with a long reset, with `HANDOFF.md` as the prompt.
- O4: import-boundary rule with a baseline (`import-linter`, `dependency-cruiser`) when BRAIN.md names layers.
- O9: one `[consolidate]` task at a phase close when duplicates, oversize files or layer violations grew.
- K: an ADR before each infra phase (one per phase); `ap run --no-prod`; the credential recheck before each deploy step.
- N1: when two documents disagree on a task, the git log and the code win, then the newest document; the summary names the conflict.
- Fixes: the self-build's `.agent/` moved to `examples/self-build/`; a fresh clone starts clean; ten tests from session 30 corrected (RCA 2026-10-12).

## [0.3.0] - 2026-10-12

- P10 pull-back fixes: venv install, presets security note, context imports, copilot file rule, git discard lock retry, doctor package row, parked-task test.
- J14: short questions, own fix first, repeated report is not stuck, a cut session keeps its diff.
- N5.1: `scripts/bump.py`, this changelog, release workflow, install scripts pinned to a tag, `ap --version` with commit.
- N8: one consent at install start, then zero questions: the installer lists what it installs and the rights it takes; one UAC prompt (scheduled task `Autopilot-Setup`) or one sudo (`/etc/sudoers.d/autopilot`); a later run installs a missing system tool through those rights; `ap doctor` lists them; `ap uninstall --rights` removes them.
- N9: `ap mcp`, a stdlib MCP server with `ap_status`, `ap_next`, `ap_start`, `ap_stop`, `ap_answer`; `ap init` registers it in the project MCP files.
- N10: login preflight per runner, subscription login only; a failed check prints the one login command and stops; API-key runners are listed as not supported.
- N12: parallel tasks on by default (3 with a test command in direct mode), collision avoidance by `files_in_scope`, batch of 1 under 25 percent of the usage window, worktree setup time logged.
- N13: plan source sync at start and at every phase close; new roadmap items become tasks with no command; `status: dropped`.
- O1: `files_in_scope` is a hard gate; `scope_additions` in the report; `ap validate` warns on an empty scope.
- O2: `ruff check .` alone (flake8 only when ruff is absent); file-growth budget (400 lines or 25 percent per task) against `.agent/quality_baseline.json`.
- O3: a new file the task declares passes; a dependency manifest change needs `new_deps` on the task or in the report.
- O5: contract-first task rule in the planner prompts.
- O6: helper index (`autopilot/repomap.py`) in every task prompt: reuse before you write.
- O7: a review verdict is required (one retry, then fail); the checklist gains placement and reuse.
- O8: a parallel merge is gated on the merged result; a red suite after a batch reverts the last merged task.
- O10: lean profile on by default (one smoke test per criterion, changed-module tests per task, one retry, audits off, smaller prompt); `ap report --tokens`; `ap audit`.
- J13: terminal window v2, sixteen rows (all phases, no wrapped row, real data with age and `stale`, no duplicates, honest task time and ETA with its basis, project rows, risk and tries, rate, file lines, issue reasons, step times, one meaning per colour, one headline, the bottom bar).
- J12.9: the README says where the envguard numbers come from.
- O11: one documentation session per closed phase writes the app's `docs/RCA.md` (retried tasks), a README section per feature and `docs/DEVELOPING.md`; it may touch only those files and `docs/`.
- O1 (session 27): scope additions count from attempt 2, at most 3, exact file paths, and are recorded in the task history, PROOF.md and the dashboard.
- N8 (session 27): the Windows task script lives in `%ProgramData%\Autopilot`, writable by Administrators only; the queue is checked before it is written; `ap uninstall --rights` removes the folder.
- The first self-build state moved from the tracked root `.agent/` to `examples/self-build/`; a fresh clone starts clean.
- Measure run (session 27): the lean profile saved 19 to 28 percent tokens per task (rule: 40), the parallel default formed no batch on a plan with mostly `high` tasks; by the owner's rules the template is back to `profile: full` and `parallel: 1`, both one line away.
- Fixes the measure run forced: a new manifest with a reason needs no `new_deps`; the template leaves `retries.max_attempts_per_task` to the profile; the python preset setup line runs under cmd.exe; the task report schema names `scope_additions` and `new_deps`; test data with `example`, `fake` or `dummy` inside the value passes every secret pattern; the docs session redacts a secret-looking line instead of dropping the phase docs.
- 2026-10-11 **P01-T01** plan.yaml `status: done` marks finished work — Added optional task key `status` (only `done`) to plan.py with validation naming the task id. sync_plan records done tasks as done (note 'done before Autopilot') when the row is new or pending, and ne
- 2026-10-11 **P01-T02** Discovery pack for onboarding — Added discovery_pack(root, cfg) in autopilot/context.py: git log, document tree with plan-file heads, stack files and one capped test run (timeout from onboard.test_timeout_sec, default 300), all capp
- 2026-10-11 **P01-T03** Onboarding prompt: four adopt rules and the pack — onboard.md now carries a {{discovery}} section and the four adopt rules; cmd_onboard builds discovery_pack and passes it to render, and after the session warns with the names of new untracked files ou
- 2026-10-11 **P02-T01** Detect missing project dependencies and the standard install command — Added missing_deps, system_tool_hint and a 'dependencies' WARN doctor row to autopilot/doctor.py; new tests/test_deps.py covers every lock file, both OS hints and the doctor row. test_deps.py and test
- 2026-10-11 **P02-T02** Preflight installs project dependencies — Preflight now installs missing project dependencies before a run: it uses commands.setup, or the standard command written back into project.yaml with a comment-preserving text edit. A missing system t
- 2026-10-11 **P03-T01** Presets for kiro, cursor and aider — Added kiro, cursor and aider presets to PRESETS in autopilot/backends/command.py, following the ADR. The model option is --model for these three (_MODEL_OPT), and a {prompt_file} placeholder lets aide
- 2026-10-11 **P03-T02** Detect the installed and logged-in runner — Added detect_runner(env=None) to autopilot/doctor.py: a RUNNERS table (claude, kiro-cli, cursor-agent, codex, gemini, aider) checked in order with shutil.which on env PATH; a non-empty documented key 
- 2026-10-11 **P03-T03** Preflight writes the detected runner to project.yaml — preflight(cfg) now reads the raw project.yaml. When it sets no backend, command or preset, preflight calls detect_runner and writes backend/preset as a comment-keeping text edit that is parse-checked 
- 2026-10-11 **P05-T01** Install scripts: Python when missing, `ap` on PATH, one final line — install.sh and install.ps1 now run `uv python install 3.12` only when no Python >= 3.10 is found (command printed in dry-run), check that `ap` is on PATH after the install, and end with exactly: Open 
- 2026-10-11 **P05-T02** README: one install line per system and honest limits — README.md now shows one Windows install line and one macOS/Linux/WSL line (`| bash`), then "Open a project folder and type `ap`.", plus an honest-limits section naming Replit, the Kiro and Cursor chat
- 2026-10-11 **P06-T01** Autopilot block in IDE rule files and CLAUDE.md — cmd_init now calls write_ide_rules(): it appends or creates one marked Autopilot block in Cursor (.mdc with alwaysApply), Kiro steering, Copilot instructions, GEMINI.md and AGENTS.md when the IDE mark
- 2026-10-11 **P04-T01** One-screen adopt summary: done, open, next — Added adopt_summary(root) in autopilot/report.py: from plan.yaml, or the state DB when it exists, it prints done/open counts, per-phase progress, the next ready task and open owner-only tasks, in at m
- 2026-10-11 **P04-T02** Plain `ap`: adopt a project that has code and no .agent/ — Plain `ap` in a terminal now decides the case from the folder. An empty folder or one with only dotfiles gets the idea prompt. A folder with code and no .agent/project.yaml is adopted: preflight, quie
- 2026-10-11 **P07-T01** New-file rule and reasons in the commit message — Added the NEW_FILE_RULE constant to gate.py and the same text, word for word, as a bullet in system.md. task.md now asks for an optional `new_files` [{path, reason}] report field, and the task report 
- 2026-10-11 **P07-T02** Gate: a new file with no reason gets a retry with the rule quoted — I added missing_reasons(cfg, git, report) to gate.py. A file added in the staged diff (except test files, .agent/ and renames) with no non-empty new_files reason produces one gate problem that quotes 
- 2026-10-11 **P08-T01** `ap init --stack` keeps every block after `commands:` — Fixed the cmd_init commands-block regex in cli.py: removed the re.S flag, match one line with [^\n]*, and substitute through a lambda. Two regression tests in tests/test_presets.py cover the template 
- 2026-10-11 **P08-T02** Config error lists all presets; an existing CLAUDE.md gets the `ap` lines — The command-backend config error now lists every name in backends.command.PRESETS, so kiro, cursor and aider appear. An existing CLAUDE.md with the old Autopilot heading but no `ap status` gets the tw
- 2026-10-11 **P09-T01** Template turns the new-file guard on; old project.yaml stays off — The project.yaml template now sets gate.new_file_reasons to true, so `ap init` (with or without --stack) writes it on, with the reworded comment kept. config.defaults() is built from the template, so 

## [0.2.0] - 2026-10-11

- Section N self-build merged (N1 to N7).

## [0.1.0]

- First public version.
