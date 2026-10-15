# Changelog

Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.
It is for one developer, or for a person with an idea and a developer friend.

Words in the entries: Claude Code (the coding agent that writes the code), the gate (the check after each step), a worktree (a separate copy of the project for one task), a subscription (a paid Claude plan), `plan.yaml` (the task list). Format: Keep a Changelog. One line per roadmap item, under Unreleased.
Bump rule: patch = a fix, minor = a roadmap item, major = a `plan.yaml` or `project.yaml` format change (with a migration note).
Release: run `python scripts/bump.py X.Y.Z`, then push the commit and the tag.

## [Unreleased]

## [0.9.1] - 2026-10-15

**In plain words:** six fixes from the first run on a half-built project. A leftover stop file is named, not obeyed. A commit by someone else on an Autopilot branch is kept. A long test run shows its elapsed time. A second Claude Code session cannot edit the checkout while a run holds it. A broken test database gets one question, not three code attempts. The stop reason says who stopped and when.

- A stop file left by an earlier run no longer ends a fresh run; the start names it and how to clear it.
- The stop line now says which word the stop file holds and when it was written.
- A commit someone else makes on an Autopilot branch during a run is kept under a new branch name, never reset away.
- A long project command, such as the full test run, shows its elapsed time and an estimate on every screen.
- While a run holds the checkout, the plugin refuses edits and git moves from another Claude Code session, and the setup commands refuse too.
- When the main check fails on the environment, such as a database that is down, Autopilot runs setup, asks you once, and starts no fixer.
- The stop reason on every screen says which stop was sent, from where, and when.

## [0.9.0] - 2026-10-15

**In plain words:** this version closes the findings of the 2026-10-14 security review. It spends every usage bar and credit you have. A project you already started is read first, your files stay, and one git command undoes all its work. Autopilot stays unattended: no prompt and no question. The documents explain the admin right in plain words, and the code validates everything the model writes.

- A new page, COMPARE.md, explains why Autopilot helps even when you already write skills for the model.
- A production approval is now recorded with who gave it and when, and a coding session cannot approve its own deploy.
- Every push checks the documents for long sentences, long table cells and page length, and the two big pages start with a finder table.
- Each release now carries a signed proof of where it was built, and the updater refuses a download that fails that proof.
- The watch screen and the status page show every usage bar of your login, and a full model bar gives way to the next model.
- Autopilot suggests which login or credit to spend next, switches on its own when you allow it, and warns three days before a credit expires.
- A retry moves to a stronger model only when that model has room, and the same failure twice parks a task.
- A task moves to the login where it fits, and a model that answers with a limit is skipped until it resets.
- The review model can follow the risk tier, and side sessions can run on a free command-line tool.
- One AI box on the watch screen and the status page shows every login, model and credit with a state word and the next switch.
- When every login is out, the run waits for the earliest refill and resumes by itself, and one line on the screen says when.
- Low and medium tasks can run on your API credit through the Cline command-line tool, and the credit counts down on the screen.
- Each release also carries the table of supported AI programs as a signed file, with the date the vendor docs were checked.
- The security and how-to documents now explain the admin right that lets a build install system tools without a password.
- The plugin stop check no longer runs commands in folders that Autopilot did not set up on this computer.
- A task or phase name with unsafe characters is now refused, so it cannot delete a folder outside the build area.
- Test and deploy commands no longer receive your login, token or alert variables unless a step asks for them.
- A folder with code is read first: the empty template plan cannot run, and the start commands adopt the project instead.
- A tag marks the project before the first run, so one git command undoes everything Autopilot did.
- A deleted file needs a reason in the report, and a failed attempt keeps the files you added during the run.
- A project on Mercurial, Subversion, Perforce or Jujutsu gets one line that says where the undo history lives.
- A temporary journal file can no longer break a git step on Windows.
- A new project switches logins and credits between tasks by itself; set it to suggest to only see the advice.
- A staged file with shell characters in its name can no longer run a command in the check, and uninstall steps run without a shell.
- The log now rotates at 10 MB, and a stuck git command stops after five minutes instead of hanging.
- The status page needs a random link code, and key or credential files never go into a commit.
- Alerts, session logs and crash reports no longer carry secret values, and `ap validate` warns about a public alert channel.
- The `ap` command now starts in about half the time, because the network code loads only when a step needs it.
- The pre-merge check now also runs the changed tests on the newest Python, and the test lint finds two more host traps.
- Four more features have written contracts, so their tests cannot be removed without a reason: the outcome word, the receipt, install and setup, and upgrade.
- A new report option builds a cleaned problem report from your last run, and sends it only if you ask.
- `ap doctor` prints one checklist format in all three modes, with the same exit codes and an optional JSON output.
- The usage window figures follow the login the run is on now and name it, and each login learns its own window size.

## [0.8.0] - 2026-10-14

**In plain words:** Autopilot now learns from its own runs and wastes less time. A run shows what it waits for, a stop is quick, and nothing is lost when a task fails. It also guards your project better: a broken main branch is found at once, and important features cannot shrink unnoticed.

**Update by itself, before the work**
- `ap run` and `ap start` look for a newer release once a day. They install it first, then start the same command on the new version. No question. A run that is active, a checkout and `upgrade.auto: false` are left alone.
- Every update line names the way back: `ap upgrade --ref v<old>`.
- `ap upgrade` on a git checkout says `is the latest` when nothing changed.

**See what happens**
- The watch screen tells you what the run waits for, and its clock ticks every second.
- A run whose process is gone shows DEAD, not ON.
- The task time counts only the time the task really worked.
- A card at the top shows the task in work: its steps, an end-time range and what changed so far.
- At the end, the screen names the outcome and lists what is still open, with the command to run.
- A run that you stop by hand ends with the word STOPPED.

**Stop and steer**
- `ap stop --now` ends the current session within 30 seconds and keeps its work.
- You can type into a running build: a command runs at once, and a question gets a short answer.
- A command such as `ap start` never builds another folder's project without asking you first.
- The cost is forecast early, and on a subscription the run asks you before it stops at the cost limit.
- A second Claude login can take over when the first one reaches its usage limit.

**Less waste**
- A task that fails only on its scope or its tests keeps its work for the next try.
- A retry fixes exactly the review's list, and new small findings become follow-ups.
- A retry moves to a stronger model only for hard work, not for a long file list.
- High-risk tasks no longer get an extra planning session; only critical tasks do.
- A session ends at its final answer, so it no longer waits for its own background tests.
- The tests run once for each task, and the full suite runs when a phase ends.
- The end checks get the last test result and do not run the tests again.
- Each task gets the text of its files in its prompt, so it reads less.

**Safer builds**
- A broken main branch is found before the next task starts.
- A session can stop only its own processes, never all of them by name.
- Matured features have written contracts, and a task cannot remove their tests without a reason.
- A doc update that would break a test is dropped, so main stays green.
- A key written twice in the project settings is an error, not a silent loss.
- Docker mode now works on Windows with Docker Desktop.

**Learn from every run**
- Unknown errors are counted, and `ap audit --signals` shows what to fix next.
- `ap audit --ladder` shows which model is fast and cheap for each kind of task.
- Plans run parts side by side when their files do not overlap.
- Autopilot finds your plan file by its content, whatever its name.
- `scripts/premerge.py` runs the tests on Linux and Windows before a merge.
- Release notes must be in simple words before a release can be made.

## [0.7.1] - 2026-10-13

- A session that fails with "Can't reach the API server" (a DNS or connection outage) is an infrastructure fault again: the run waits and retries, no try is spent, no task is parked.

## [0.7.0] - 2026-10-13

**In plain words:** this version shows you what a build proved and what it did not. Every run ends with one word.
Every phase gets a signed record and a proof card. You can watch a recorded run before you install anything. Claude
Code gets a safety hook, and other AI tools and local models can run the build. Autopilot built all of this on its own
code: 22 tasks, no task blocked, in one overnight run.

- **One word at the end.** A run ends with VERIFIED, BLOCKED, BUDGET_STOP, STALLED or FAILED. The word is in the
  status, the watch window and the message you get. A run you stop with Ctrl+C says BUDGET_STOP.
- **What is not proven.** Every proof file lists the acceptance lines no test covers, the tasks with no test
  command, the features not checked and the files added outside the plan. "Nothing" means everything was checked.
- **Watch a run before you install.** `ap tour` replays a recorded build in the watch window. No login, no key, no
  cost.
- **A review on every task.** A fresh session reads the task, the change and the test output, and can send the
  task back before it merges. Before, only critical tasks got this.
- **A signed record per phase.** `receipt.json` holds the file hashes and a signature with a key that stays on your
  PC. `ap verify` checks it offline and says CHANGED when a record was edited.
- **A proof card.** Each phase gets `proof.svg`, a small card with the merged count, the cost and the date, and a
  line you can paste into a README.
- **Draft pull requests.** In PR mode, a task with open items opens a draft pull request with the list in its text.
  A clean task opens a ready one.
- **What your retries cost.** `ap audit --history` reads your Claude Code history and prints the money spent on
  repeated failing commands. It works without a project.
- **A safety hook for Claude Code.** The plugin blocks "done" while your tests fail or a test file shrank. Install
  it with `/plugin marketplace add manishjnv/AutoPilot`.
- **Run with the laptop off.** HOWTO has the steps for a Claude Code Routine, with a ready prompt.
- **Run inside a container.** `sandbox.mode: docker` runs each session in a plain Docker container with only the
  project folder mounted. Linux, WSL and macOS for now.
- **Local models.** `agent.backend: openai_compat` sends a session to Ollama, LM Studio or any OpenAI-compatible
  endpoint. `ap doctor` checks that the endpoint answers.
- **A thin VS Code extension.** Three commands and a status panel. Not published yet.
- **README** opens with what Autopilot is and lists what protects you under "Safety".

## [0.6.0] - 2026-10-13

**In plain words:** this version makes the first setup easier and the overnight build harder to stop. Setup can be
run again after a failure and continues where it stopped. Every error you see is one plain sentence with the command
to run. A short outage at the AI service no longer ends your build. Login works over a text-only connection.

- **Setup continues where it stopped.** If `ap setup` fails half way, run it again. Finished steps show as `done` and
  the rest continues. `ap setup --reset` starts from zero. `ap uninstall --steps` removes what setup installed, last
  step first.
- **Setup ends with a real test.** The last step sends one small prompt to your AI tool and waits for the answer
  "ready". When it works, the date is saved. When it fails, you get one sentence and the next command.
- **Errors are one sentence and one command.** Each error is matched by its error code, not by its English text, so
  a German or French Windows message gets the same clear sentence.
- **Login works without a browser.** On a server, in WSL, over SSH or in a container, the login address and the code
  print as text. You open the address on any device and type the code. On a desktop the browser opens and the
  address prints too.
- **Projects in OneDrive or on a network drive get a warning and a move command.** Such folders slow git and break
  the build. `ap move <folder>` copies the project to a local folder and keeps the history and the settings.
- **Eight more checks before the install.** Git ownership, line endings, an API key in the environment, a wrong
  clock, low disk space, an old git, a console that is not UTF-8 and a busy port. Each prints `found`, `fixed` or
  `skipped` with the command.
- **Five repairs with no question.** Git settings for the project, the PATH set once, a note about Windows
  Defender, duplicate installs of one AI tool named with the removal command, and an older project folder updated
  by `ap upgrade` with a backup.
- **An outage at the AI service does not end the build.** After three failed calls, the build waits 15 minutes and
  tries again, up to four times, and spends no retry. A login that ran out stops the build with the login command;
  the next start continues the same task. A model that is not on your plan is named with the one that works. The
  same error from three tasks in a row stops the build with a checklist.
- **Faster checks on GitHub.** The test run went from about 35 minutes to about 10.

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
- 2026-10-13 **P01-T01** Outcome word at the end of every run — Re-applied the outcome word. Every run end records VERIFIED, BLOCKED, BUDGET_STOP, STALLED or FAILED in state meta `outcome` (cleared at run start), a `run_end` event, the log, run.json `word`, and th
- 2026-10-13 **P01-T02** Not proven section in PROOF.md — Every PROOF.md now has a `## Not proven` section after the header lines. It lists untested criteria (with task id), tasks with no verify and no test command, features not checked, and scope-added warn
- 2026-10-13 **P02-T01** Recording format and the examples/tour data — Added examples/tour/events.jsonl (180 events, 31 KB, rising t) and PROOF.md, generated deterministically from examples/self-build by scripts/make_tour.py, which scrubs paths, addresses and '@' and use
- 2026-10-13 **P02-T02** ap tour command — Added `ap tour [--speed N] [--once]`. It reads the recording from `autopilot/templates/tour/`, builds dashboard data per second of recorded time, and draws it with `dash_term.frame`. At the end it pri
- 2026-10-13 **P03-T01** review.scope key and the review on medium and high tasks — Added review.scope (critical | all). Orchestrator.review_due(task) is the one rule: review.enabled and (risk critical, or scope all and risk above low, using effective_risk). review() and parallel_bat
- 2026-10-13 **P04-T01** receipt.py: sign the phase record — Added autopilot/receipt.py (HMAC-SHA256 signed receipt, key in ~/.autopilot/receipt.key, mode 0600, AUTOPILOT_HOME respected). close_phase now writes and commits receipt.json after the docs commit, an
- 2026-10-13 **P05-T01** Draft flag and the Not proven body — Under git.mode: pr, a task with gate warnings or a criterion without a test now opens a draft PR with a `## Not proven` list in the body; a clean task opens a ready PR with 'Nothing'. The logic is tas
- 2026-10-13 **P06-T01** proof.svg per phase and the badge markdown — Added autopilot/card.py (stdlib): svg() builds a 600x200 light card with every text value escaped, and badge() returns the BADGE.md text with one markdown image line for proof.svg plus the repo-relati
- 2026-10-13 **P07-T01** ap audit --history — Added `ap audit --history [--days N] [--home PATH]` in the new autopilot/commands/audit.py, routed in cli.main before the project lookup so it needs no project and writes nothing. It counts sessions, 
- 2026-10-13 **P08-T01** README position line, Safety block and a shorter feature list — README.md now opens with the position line, lists what every run proves with links to REFERENCE.md anchors, and has a Safety block of eight items; it is 1050 words. The W feature detail moved to a new
- 2026-10-13 **P09-T01** Stop hook script and hooks.json — Added a Stop hook to the plugin: `plugin/hooks/hooks.json` runs `plugin/scripts/seal.py` (python3, falling back to python). seal.py blocks "done" when the project test command fails or a changed test 
- 2026-10-13 **P10-T01** HOWTO section and examples/routine — Added the HOWTO section 'Run with the laptop off (Claude Code Routines)' with six numbered steps and a not-run-live note dated 2026-10-13, plus examples/routine/prompt.md that installs ap, sets max_se
- 2026-10-13 **P11-T01** sandbox.mode key: the one mode rule and its config checks — Added sandbox_mode(cfg) and allowlist_on(cfg) to config.py and rewrote _sandbox_errors on top of them. It rejects an unknown mode, docker without sandbox.image, docker with a non-claude_cli backend, a
- 2026-10-13 **P11-T02** docker run wrapper for the Claude CLI backend — With sandbox.mode: docker, ClaudeCLIBackend.run wraps the unchanged build_cmd argv in docker run --rm -i via the new docker_box.wrapped(). Only the worktree (at /work), its git folders (the shared one
- 2026-10-13 **P11-T03** Doctor docker line, gate reader and the docker docs — Implemented Doctor docker line, gate reader and the docker docs.
- 2026-10-13 **P12-T01** openai_compat backend — Added autopilot/backends/openai_compat.py: one non-streaming urllib POST to <base_url>/chat/completions with model_map, an optional Bearer key from agent.api_key_env, fenced `path:` file blocks writte
- 2026-10-13 **P12-T02** Doctor endpoint line and the local-model docs — Added check_endpoint in doctor.py (OK 'endpoint: <url> answers' when any HTTP answer comes back, WARN 'does not answer (start Ollama or LM Studio)' otherwise, never raises). checks() and check_runner_
- 2026-10-13 **P13-T01a** Status page port file — start_status_page now writes `<root>/.agent/status.port` with the port it bound (digits and a newline; an OSError on write is ignored). `.agent/status.port` is in the new-project gitignore template, a
- 2026-10-13 **P13-T01** vscode/ extension skeleton with three commands and the webview — Added the thin VS Code extension in vscode/. It has the three commands (`autopilot.start`, `autopilot.answer`, `autopilot.stop`), which send `ap start`, `ap answer` and `ap stop` to a reused terminal 
- 2026-10-13 **P14-T01** Outcome word for an interrupted run and in the watch bar — A KeyboardInterrupt end now stores BUDGET_STOP via _end_word in the finally of _run (only when no word is set). The dashboard data exposes project.word and the dash_term bottom bar shows the word afte
- 2026-10-13 **P14-T02** Receipt end-to-end test and test hygiene — Added an end-to-end receipt test that drives a one-task phase close with the fake backend and checks receipt.json plus ap verify exit 0. Gave the test_steps upgrade test a tmp_path, a chdir and a stub
- 2026-10-13 **P14-T03** REFERENCE entries for the plugin Stop hook and the Routine page — REFERENCE.md `## Proof features` now has a `### Stop hook in the plugin` subsection (seal.py's two checks, the 300 s test limit, the 330 s hook timeout in hooks.json, the 5-block counter file, `/plugi
- 2026-10-13 **P01-T01** W20 The phase docs session passes the gate too — docs_phase now runs commands.test through gate.run_commands on the staged docs result. A red result is discarded with the event '<phase>: result dropped (tests: <first failing line>)' and main stays u
- 2026-10-13 **P02-T00** Contract: gate.scope_always and gate.tests keys — Added config.scope_always(cfg) and config.tests_mode(cfg) with the defaults (REFERENCE.md, CHANGELOG.md, HOWTO.md, README.md / changed), using only cfg.get. validate() reports a non-list gate.scope_al
- 2026-10-13 **P02-T01** W19 Docs files are always in scope — task_gate now allows every entry of config.scope_always(cfg) beside the task scope, with no addition and no warning. A code file outside scope still fails. The task and replanner prompts carry the doc
- 2026-10-13 **P02-T02** W22 Tests run once, not twice — verify_commands now narrows tests per task when gate.tests is changed (the default), in every profile. The phase close (phase=True) always runs the full command, and gate.tests: full keeps the full co
- 2026-10-13 **P01-T01b** W37a A dead run shows DEAD, not ON — The earlier work was not in the tree (git was clean), so I built the whole task, including the D-001 fix. A run.json that says running with a dead pid now shows `DEAD since HH:MM` in `ap status`, `ap 
- 2026-10-13 **P01-T01c** W37b Sessions may not kill processes by name — Every Claude Code session now gets the four kill-by-name deny rules (KILL_DENY in claude_cli.py, added on top of any project list), system.md has the stop-by-pid rule, and task_gate(log_path=...) fail
- 2026-10-13 **P01-T01d** W37c A session's child processes end with it on Windows too — On Windows run_proc and stream_proc now put each process in a kill-on-close job object via ctypes; _kill_tree calls TerminateJobObject before taskkill /T, and the handle is closed when the call return
- 2026-10-13 **P01-T02** W21 Red main is detected, not deselected — Each new commit on main (run start, `_commit_main`, a pull) is now tested once before the next task. The result is cached by sha, and a red main sends a `main_red` event naming the failing test. If ma
- 2026-10-13 **P01-T02b** W21 failing_before is checked against main — Added optional `failing_before` to the task report schema and task.md. Added `Orchestrator.failing_before(phase, report, base)`, called in `execute_task` after `_fix_problem` and in `_finish_parallel`
- 2026-10-13 **P01-T01** W29a Unknown session errors are written to unknown.jsonl — Added autopilot/signals.py: record_unknown(text, runner, project, action, home=None) classifies a failed session's text by cause (limit, infra, environment from detect_limit, detect_infra and install_
- 2026-10-13 **P01-T02** W29b ap audit --signals prints the signals table — Added `ap audit --signals` (commands/audit.py cmd_signals, wired in cli.py next to --history, reusing --days). It reads unknown.jsonl and the quality/task_blocked events of every recent project's stat
- 2026-10-13 **P01-T03** W24 Dependencies come from the files, not from the order — Added plan.independent_groups(plan) and shared_files in plan.py; ap validate prints 'N phases can run side by side' and each pair of phases that shares a file with the shared path. The plan writer, re
- 2026-10-14 **P01-T04** W23 The model ladder is measured, not assumed — Added `ap audit --ladder` in commands/audit.py, wired in cli.py. It reads the project's state.db read-only and prints, per model and risk, finished tasks, median minutes per task (the sum of the task'
- 2026-10-14 **P02-T01** W41 Escalate on hard work, not on file count or a mechanical gate failure — The retry now escalates only on hard work. The size rule ignores test files, `gate.scope_always` files and `.agent/`, and a gate failure made only of growth, scope or lint problems returns '' from `es
- 2026-10-14 **P02-T02** W40 A retry fixes the review's list; the next review checks that list first — A failed review's findings are now kept per task (state meta review_list:<id>) and shown in the retry prompt as a numbered list under 'Fix exactly these review findings, nothing else:'. The next revie
- 2026-10-14 **P02-T03** W27 Scoped files in the prompt — Added autopilot/scope_files.py with scoped_files_block(root, files, cap, skip); task_prompt appends the '## Files in scope (current content)' block (exact files in list order, '(new file)' for missing
- 2026-10-14 **P03-T01** W36a Feature contracts in features/, given to the tasks that touch them — Added committed feature contracts features/watch-screen.md and features/gate.md (five sections, real test names) and autopilot/contracts.py: contracts_for(root, files) returns the pages whose ## Files
- 2026-10-14 **P03-T02** W36b The gate guards the contracts' tests; docs edit sections in place — Added contracts.contract_problems (one call from gate.task_gate): pages are read from git HEAD, and the diff uses --no-renames so a renamed test file still counts as the old path deleted. A removed co
- 2026-10-14 **P03-T03** W43 A budget stop is forecast; on a subscription it is a soft cap — W43 is re-applied with the review fix. When `ap budget` raises the cap, budget_hold now closes the open budget question itself with set_decision(status='APPLIED', answer='cap raised to $X') plus _writ
- 2026-10-14 **P03-T04** W42 Task time counts work, not the wall clock since the first session — Task time on the dashboard is now the sum of the task's session durations (running ones count to now) instead of the wall clock from its first session. A `took` note ('took 20m (2 tries, first 10:00)'
- 2026-10-14 **P04-T01** W39 ap stop --now ends the session at once and keeps its diff — `ap stop --now` (or a second `ap stop` within 60 s) writes `now` into .agent/STOP; proc.stop_when arms a watcher in run_proc/stream_proc during task sessions only. When the file says `now`, the watche
- 2026-10-14 **P04-T02** W35 The plan file is found by content, not by name — New autopilot/plan_find.py: plan_candidates(root) scores .md/.txt/.rst files by checkboxes, numbered steps, phase/milestone/sprint/step/task headings and size (200 kB cap), walking with os.walk and pr
- 2026-10-14 **P04-T03** W38 A duplicate key in project.yaml is an error; ap validate prints the session environment — config.load_yaml now rejects a duplicate key in one mapping with yaml's ConstructorError naming the key, the mapping path and both lines; ap validate prints the session env and runner/config folder li
