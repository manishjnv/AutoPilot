# Smoke test: a first real run

This test checks Autopilot from start to end with real Claude Code sessions. It uses a plan with 3 tasks
(`PLAN.md`), and approximately 5 to 10 sessions.

> [!IMPORTANT]
> Run the test on your own computer, in a new empty folder outside this repository.

## Run the test

1. Make the project:

   ```bash
   mkdir wordstats && cd wordstats && git init -b main
   printf '[project]\nname = "wordstats"\nversion = "0.1.0"\n' > pyproject.toml
   git add -A && git commit -m "empty project"
   ```

2. Make the tasks from the smoke plan. The command ends with `autopilot doctor`:

   ```bash
   autopilot quickstart --plan-doc /path/to/AutoPilot/examples/smoke/PLAN.md
   ```

3. Show the 3 tasks in order, with their models:

   ```bash
   autopilot next
   ```

4. Start the run:

   ```bash
   autopilot run --max-sessions 10
   ```

5. Show the numbers of the run:

   ```bash
   autopilot stats
   ```

## Examine the result

| Where | Correct result |
|---|---|
| `autopilot status`, or the page at `http://127.0.0.1:8765/` | 3 tasks are done, and no task is blocked |
| `git log --oneline` | One `[autopilot]` commit for each task, and the docs commits |
| `.agent/logs/sessions/*.log` | The `assistant` events have `message.usage`, and the last `result` event has `structured_output`. Autopilot uses both |
| `.agent/REPORT.md` | The Tokens section shows numbers that are not zero for each model |

## Optional tests

Test one option at a time.

| Option | How to turn it on |
|---|---|
| Network allowlist (WSL, Linux or macOS only) | Add `sandbox: {enabled: true, allowed_domains: [pypi.org, files.pythonhosted.org]}` to `.agent/project.yaml` |
| Fix tasks from GitHub issues | Set `intake.enabled: true`. Then open a GitHub issue with the label `autopilot`. This needs a GitHub remote and `gh` |
| Telegram | Set `AUTOPILOT_TG_TOKEN` and `AUTOPILOT_TG_CHAT`, then set `chat.enabled: true` |
