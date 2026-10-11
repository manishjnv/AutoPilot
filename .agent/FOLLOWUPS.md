# Follow-ups

Reported by sessions; consumed by the auditor and replanner.

- [P01-T01] Full pytest suite (background run killed at time limit) and the WSL script were not run to completion in this session; the orchestrator should run them
- [P01-T02] Full pytest suite and the WSL script were not run in this session; the orchestrator should run them
- [P01-T02] discovery_pack is not yet wired into the onboard prompt (cmd_onboard); a later N1 task should do that
- [P01-T03] Full pytest suite and the WSL script were not run in this session; the orchestrator should run them
- [P01-T03] cmd_quickstart onboarding goes through cmd_onboard, so it gets the pack and warning too; no separate check was added
- [P02-T01] A Poetry venv outside the project gives a false WARN; consider poetry env info -p or POETRY_VIRTUALENVS_IN_PROJECT
- [P02-T01] Run the full pytest suite and the WSL script
- [P02-T02] Bug in cmd_init: the regex `(?ms)^commands:\n(?:[ \t]+.*\n)*` has re.S so `.*\n` eats the rest of project.yaml; after `ap init --stack X` everything after the commands block (agent:, scheduling:, ...) is lost
- [P02-T02] Run the full pytest suite and wsltest_self.sh (the script path was not found from Git Bash)
