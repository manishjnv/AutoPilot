# Autopilot features

Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.
It is for one developer, or for a person with an idea and a developer friend.

Skills tell the model how. Autopilot proves it did. See [Compare](COMPARE.md) for the reason.

This page lists every feature in simple words. Each row says what the feature does and why it helps you. For commands and settings, see the [Reference](REFERENCE.md). For steps, see the [How-to guides](HOWTO.md).

Words on this page: a *task* is one piece of work from your plan. A *phase* is a group of tasks. The *gate* is the check that runs after each task. A *run* is one build from start to end. A *session* is one fresh start of the AI with an empty memory.

## Install and set up

| Feature | What it does | Why it helps you |
|---|---|---|
| **One-line install** | You run one line in your shell. The script installs Python, Autopilot and the AI program you pay for. No administrator prompt. | **You start in minutes on Windows, macOS, or Linux.** |
| **One question at setup** | Setup asks only "Which AI do you pay for?" (Claude, GitHub Copilot, Codex, Cursor or Kiro). | **You do not need to know technical settings.** |
| **Setup continues after a failure** | If setup stops half way, you run it again. Finished steps show as done. | **You never start from zero again.** |
| **Setup ends with a real test** | The last step sends one small prompt to your AI and waits for the word "ready." | **You know the AI works before you start a build.** |
| **Errors in one sentence** | Every install error shows one plain sentence and the one command to run. | **You do not need to read a long error text.** |
| **Login without a browser** | On a server or over a text connection, the login address, and the code print as text. | **You can set up Autopilot on any computer.** |
| **Checks your computer** | `ap doctor` checks the AI login, git, disk space, the clock, the console, and more. It repairs what it can. | **A build does not stop on a problem that Autopilot can fix.** |
| **Bad folder warning** | A project in OneDrive or on a network drive gets a warning. `ap move` copies it to a safe folder. | **Slow or broken builds in these folders are prevented.** |
| **Checksums for the installer** | Each release ships a checksum file. A dry run shows every step before it changes anything. | **You can check what the script does before you run it.** |
| **Updates itself** | Before a build, Autopilot installs a newer release and starts the same command on the new version. Every update line names the way back. | **You always run the newest version, and you can go back.** |
| **Clean removal** | `ap uninstall --all` removes Autopilot, its rights, and its folder. It keeps your projects and your AI tool. | **Nothing is left behind.** |

## Start a project

| Feature | What it does | Why it helps you |
|---|---|---|
| **Type `ap` and go** | In a folder, you type `ap`. Autopilot decides what to do: ask for the idea, read existing code, or continue the build. | **One short command does the right thing.** |
| **Plan from an idea** | You write your idea in a few sentences. The AI writes the plan and the tasks for you. | **You do not need to write a technical plan.** |
| **Plan from your own file** | Autopilot finds your plan file by its content, whatever its name. | **You can use the notes you already have.** |
| **Start an existing project** | In a folder with code, Autopilot reads the code, the git log, and your notes. Finished work stays done. | **You can use Autopilot on work you already started, and nothing is built twice.** |
| **One-screen summary** | Before the start, you see what is done, what is open and what comes next. | **You know the state of the project in one look.** |
| **Starts without a question** | A plan with no risky task starts at once. The status page opens once. `ap --ask` keeps the question. | **You do not need to confirm each step.** |
| **Installs project dependencies** | Before a run, Autopilot installs missing packages of your project with the standard command. | **You do not install anything by hand.** |
| **Rules for your editor** | `ap init` writes a short Autopilot block into the rule files of Claude Code, Cursor, Kiro, Copilot, and Gemini. | **Your editor chat knows how to use Autopilot.** |
| **Checks the plan** | `ap validate` finds an error in the settings or the plan, and shows which phases can run side by side. | **A bad plan is found before the run.** |
| **Finds your AI tool** | Autopilot uses the AI program that is installed and logged in. | **No setting to write.** |

## Build without you

| Feature | What it does | Why it helps you |
|---|---|---|
| **Builds while you are away** | Autopilot runs each task in a new AI session, one after the other, until the plan is done. | **You give it a plan tonight and see a working app in the morning.** |
| **Runs in the background** | The build continues after you close the terminal or the chat. | **Your computer works while you sleep.** |
| **Python decides, not the AI** | Your build, lint and test commands run after each task. A task is done only when they pass. | **The AI cannot say "done" when the work is not done.** |
| **The plan cannot change** | The gate refuses a change to the plan during a run. | **The AI builds what you asked for, not what it prefers.** |
| **Fresh memory for each task** | Each task starts a new session with a short brief. The memory is in files, not in a long chat. | **The AI does not forget early details after many hours.** |
| **Low cost first** | A simple task starts on a cheap model. A hard task starts on a strong one. | **You pay for power only where it is needed.** |
| **Stronger model on failure** | When a task fails, a stronger model tries again. | **Hard problems get more power, easy ones stay cheap.** |
| **Diagnosis of a blocked task** | After two failures, a read-only session finds the cause. It can search the web. One more try uses the result. | **A blocked task gets a real diagnosis, not a blind retry.** |
| **Questions do not stop the build** | When a task needs you, it waits in a questions file. The other tasks continue. | **One open question does not waste the night.** |
| **Design choice before a risky task** | Before a critical task, the AI compares two or three designs and records the choice. | **Risky decisions get thought before code.** |
| **Web research before a task** | A task can ask for research first. The notes go to a folder in your project. | **The AI reads the docs before it writes the code.** |
| Feature check at the end of a phase | A session starts the app and tries each user journey. In the full profile it also tries one way to break it. A failed feature becomes a fix task. | The app works for a user, not only for the tests. |
| **Completion audit** | At the end, a check finds gaps in the work and adds tasks to fill them. Under the lean profile, you start it with `ap audit`. | **The app is complete, not only the task list.** |
| **Other AI tools** | Autopilot can run Claude Code or a local model on your own computer. GitHub Copilot, Codex, Cursor and Kiro are experimental. | **You use the tool you already pay for.** |
| **Second login takes over** | When one login reaches its usage limit, a second login or a second AI tool can continue. | **The build does not stop at a limit.** |

## Smart retries and less waste

| Feature | What it does | Why it helps you |
|---|---|---|
| **A failed try keeps its work** | A task that fails only on its scope or its tests keeps its files for the next try. | **Less work is repeated.** |
| **A retry fixes the list** | A retry fixes exactly the findings of the review. New small findings become follow-ups. | **The AI does not start over.** |
| **Stronger model only for hard work** | A retry moves to a stronger model for a hard problem, not for a long file list or a lint error. | **Less money is spent on simple fixes.** |
| **Tests run once** | Each task runs only the tests of the changed files. The full suite runs when a phase ends. | **The build is faster.** |
| **Files in the prompt** | Each task gets the text of its files in its prompt. | **The AI reads less and starts faster.** |
| **Reuse before write** | Each task gets a list of helpers that already exist in the project. | **Less duplicate code.** |
| **Lean profile** | A smaller prompt and fewer checks save about 40 percent of tokens per task. | **Lower cost, same result.** |
| **Hints to a task** | `ap hint` gives advice to the next session of a task, also on a retry. | **You help the AI without a full stop.** |

## Watch and steer

| Feature | What it does | Why it helps you |
|---|---|---|
| **Live view in the terminal** | `ap watch` shows the tasks, the live output, the progress, the cost, and the issues. | **You see the whole build on one screen.** |
| **Status page in the browser** | The same view opens as a web page. With a token, you can open it from another computer. | **You can follow the build from any device.** |
| **Card for the current task** | A card at the top shows the task in work, its steps, an end-time range and what changed so far. | **You know what happens now and when it ends.** |
| **What the run waits for** | The screen tells you what the run waits for, and its clock ticks every second. | **You never wonder if the build is stuck.** |
| **One color, one meaning** | Green is done, yellow is a warning, red is a failure, on every screen. | **You read the screen without a legend.** |
| **A dead run says DEAD** | A run whose process is gone shows DEAD, not ON. | **You trust what the screen says.** |
| **Type into a running build** | You type a command or a question while the build runs. A command runs at once. A question gets a short answer. | **You steer without a stop.** |
| **Answer questions** | `ap answer` lists the open questions with a suggested fix. You pick a number. | **A blocked task continues with one key press.** |
| **Change the plan in plain words** | `ap change "text"` updates the plan. You confirm before it starts and after it ends. Done tasks never change. | **You can change your mind without a new setup.** |
| **Add ideas later** | You write new ideas in a backlog file, one per line. The next run adds them to the plan. | **Your app grows after the first run.** |
| **Skip or unblock a task** | `ap skip` removes a task. `ap unblock` puts a blocked task back. | **You control the queue.** |
| **Quick stop** | `ap stop --now` ends the current session within 30 seconds and keeps its work. | **Nothing is lost when you stop.** |
| **Alerts on your phone** | Autopilot sends a message to Telegram, Slack, ntfy or a web address when it needs you or when the build ends. | **You do not need to watch the screen.** |
| **Control from Telegram** | You send `status`, `answer`, `approve`, `unblock` or `hint` to your bot. | **You steer the build from your phone.** |
| **Fix tasks from GitHub issues** | An issue with the label `autopilot` becomes a fix task. A failed CI run on main becomes one too. Off by default. | **Bugs that users report get fixed without you.** |
| **Work from the editor** | A Claude Code plugin gives you start, answer, and stop. Your IDE chat can ask for the status. | **You use Autopilot from the tools you already open.** |
| **Status page without a run** | `ap serve` opens the status page and the full report after a run. | **You can read the result later.** |
| **Numbers of a run** | `ap stats` and `ap report --tokens` show the tasks done, the time, the cost, and the tokens per model. | **You see what the run cost.** |

## Proof of the work

| Feature | What it does | Why it helps you |
|---|---|---|
| **One word at the end** | Every run ends with VERIFIED, BLOCKED, STOPPED, BUDGET_STOP, STALLED, or FAILED. | **You know the result in one look.** |
| **What is not proven** | Each phase lists the criteria that no test covers. "Nothing" means everything was checked. | **You see the gaps before you ship.** |
| **Fresh review of each task** | A new AI session reads the task, the change, and the test output. It can send the task back. Every task over low risk gets one. | **A second pair of eyes checks each task.** |
| **Signed record per phase** | Each closed phase gets a signed record. `ap verify` checks it offline and says CHANGED when a record was edited. | **Nobody can edit the proof unnoticed.** |
| **Proof card** | Each phase gets a small image with the merged count, the cost and the date, and a line for your README. | **You can show the result.** |
| **Draft pull requests** | In pull-request mode, each task opens a pull request. A task with open items opens a draft with the list. A clean task opens a ready one. | **A reviewer sees what is still open.** |
| **Record of every step** | Every session, decision, cost and bug is written to the history, a decisions log, and a bug log. | **You can see what happened and why.** |
| **Docs written for you** | At the end of each phase, a session writes the README sections, the changelog, the bug log and the developer notes of your app. | **Your app comes with its own documentation.** |
| **Replay a run** | `ap tour` replays a recorded build. No login, no key, no cost. | **You can see Autopilot work before you install it.** |

## Keep it safe

| Feature | What it does | Why it helps you |
|---|---|---|
| **Separate copy per task** | Every task works in its own copy of the project. The main branch changes only when the checks pass. | **A failed task cannot break your code.** |
| **Only Autopilot uses git** | A session cannot commit, push, or change branches. | **The AI cannot damage your history.** |
| **Broken main found at once** | After each merge, the main branch is tested before the next task starts. A fixer session repairs it. | **A problem is found at its source.** |
| **Tests cannot be weakened** | The gate refuses a deleted test, fewer tests, fewer checks, a skip marker, or a changed CI file. | **The AI cannot pass by removing the test.** |
| **Tests of key features are guarded** | A matured feature has a written contract. A task cannot remove its tests without a reason. | **Important features cannot shrink unnoticed.** |
| **Files outside the task fail** | A task may change only the files in its scope. Docs are always allowed. In a new project, a new file needs a reason. | **The AI cannot make changes you did not ask for.** |
| **Files cannot grow without limit** | A file that grows too much in one task fails the gate. A clean-up task runs when duplicates grow. | **The code stays small and tidy.** |
| **Secrets stay out** | Keys and passwords are found in a change and refused. Logs and error texts hide secret values. | **Your secrets do not leak.** |
| **Only allowed variables** | A session sees only the environment variables on a list, not your whole environment. | **Your tokens stay private.** |
| **Same behaviour everywhere** | A session does not load your own plugins, hooks, or extra servers. | **A run acts the same on each computer, and costs less.** |
| **Network allowlist** | A session can reach only the addresses you allow. Off by default. Linux, WSL, and macOS only. | **The AI cannot send your code elsewhere.** |
| **Container mode** | Each session runs in a plain Docker container. Only the project folder is mounted. It does not limit the network by itself. | **The AI cannot reach the rest of your computer.** |
| **Your email stays private** | Each commit uses your GitHub no-reply address. Your git settings do not change. | **Your email does not appear in the history.** |
| **Own Python environment** | Python packages go into a project environment, never into the system Python. | **Your computer stays clean.** |
| **No stop by name** | A session can stop only its own processes, never all programs with a name. | **Your other programs are safe.** |
| **Cost caps** | You set a limit per session, task, phase, day, and run. `ap budget` changes it during a run. | **You never get a surprise bill.** |
| **Cost forecast** | The run estimates the end cost early. On a subscription it asks you before it stops at the cap. | **You know before the money is spent.** |
| **Keeps usage for you** | On a subscription, the run pauses when only 15 percent of your usage window is left. You get an alert at 90 percent of the weekly limit. | **You can still use Claude yourself.** |
| **Spends every credit before it expires** | Autopilot ranks your logins and credits and suggests a switch, or switches between tasks on its own when you allow it. A credit gets an alert three days before it expires. | **No credit runs out unused.** |
| **Spends the bars on purpose** | A retry moves up to a stronger model only when that model has room. A task moves to the login where it fits. The same failure twice parks a task instead of a costly third try. | **No run sleeps while another login has room, and no money goes to a repeat.** |
| **One AI box** | The watch screen and the status page show every login, model and credit in one box with a state word. The one bar that limits the next task is in colour, and the next switch is one line. | **You see which model runs now and what it has left.** |
| **Production stays safe** | A deploy has a health check and a rollback. `ap run --no-prod` skips the production step until you approve it. | **Nothing goes live without you.** |
| **Safety hook for Claude Code** | The plugin blocks "done" while your tests fail or a test file shrank. | **The hook helps even outside Autopilot.** |

## Repairs itself

| Feature | What it does | Why it helps you |
|---|---|---|
| **Waits out an outage** | When the AI service is down, the run waits 15 minutes and tries again, up to four times. No try is spent. | **A short outage does not end the build.** |
| **Sleeps at a usage limit** | At a usage limit, the run sleeps until the window resets. When every login is out, it waits for the earliest refill and resumes on the login that has room, with one line that says when. | **The build continues on its own.** |
| **Repairs a missing tool** | A missing project package is installed again. A broken Claude program is installed again. A missing system tool gets one printed command for you to run. | **A small problem does not end the build.** |
| **Restarts after a crash** | After a crash or a restart of the computer, the run continues from its saved state. | **You do not lose the night.** |
| **Restores damaged files** | A damaged plan or state file is restored from the last good copy. | **The plan is never lost.** |
| **Pushes again** | A failed push to GitHub is tried again, and again at each commit. | **Your backup on GitHub stays current.** |
| **Plan file sync** | When you change your plan document, the next start updates the tasks. | **Your document and the tasks stay the same.** |

## Coming soon

A build on a server with Docker, and a scheduled cloud run with the laptop off. Both paths exist but have not run live yet.

## Learn from every run

| Feature | What it does | Why it helps you |
|---|---|---|
| **Finds what to fix next** | `ap audit --signals` counts unknown errors, blocked tasks, and retries by cause. | **Each run makes the next one better.** |
| **Measures the models** | `ap audit --ladder` shows which model is fast and cheap for each kind of task, and proposes a change. After every 20 finished tasks, Autopilot also suggests a cheaper model where the data shows it is safe. | **You pay less for the same result.** |
| **Cost of your retries** | `ap audit --history` reads your Claude Code history and prices repeated failing commands. | **You see where money goes.** |
| **Bug log** | Each bug gets a line with the symptom, the cause, the fix, and the prevention. | **The same bug does not come back.** |
| **Release notes in simple words** | Every release starts with a plain-words summary. | **You understand what changed without technical words.** |
