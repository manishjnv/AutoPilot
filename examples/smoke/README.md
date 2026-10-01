# Smoke test: a first real run

Checks Autopilot end to end with real Claude Code sessions on a 3-task plan (`PLAN.md`). Expect roughly 5-10
sessions. Run it on your own PC, in a new empty folder outside this repo.

```bash
mkdir wordstats && cd wordstats && git init -b main
printf '[project]\nname = "wordstats"\nversion = "0.1.0"\n' > pyproject.toml
git add -A && git commit -m "empty project"

autopilot quickstart --plan-doc /path/to/AutoPilot/examples/smoke/PLAN.md   # ends with `autopilot doctor`
autopilot next                           # the 3 tasks in order, with their models
autopilot run --max-sessions 10
autopilot stats                          # the numbers of the run
```

## What to look at
- `autopilot status` (or `autopilot serve`, then http://127.0.0.1:8765/): 3 tasks done, nothing blocked.
- `git log --oneline`: one `[autopilot]` commit per task, plus docs commits.
- `.agent/logs/sessions/*.log`: the stream-json events. Note whether `assistant` events carry `message.usage` and
  whether the final `result` event has `structured_output`. Both are assumed by Autopilot and not yet seen live.
- `REPORT.md`: the Tokens section has non-zero numbers per model.

## Optional extras, one at a time
- Network allowlist (WSL/Linux/macOS only): `sandbox: {enabled: true, allowed_domains: [pypi.org,
  files.pythonhosted.org]}` in `.agent/project.yaml`.
- Bug intake: `intake.enabled: true`, then open a GitHub issue labelled `autopilot` (needs a GitHub remote and `gh`).
- Telegram: set `AUTOPILOT_TG_TOKEN` and `AUTOPILOT_TG_CHAT`, then `chat.enabled: true`.
