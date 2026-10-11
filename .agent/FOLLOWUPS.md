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
- [P03-T01] config.py:95 error text still lists only codex, gemini, opencode
- [P03-T01] HOWTO.md:329 and README.md:123 name only the old presets
- [P03-T01] Live check of kiro-cli, cursor-agent and aider; especially whether cursor-agent reads stdin (fallback: _ASK pointing to {prompt_file})
- [P03-T01] wsltest_self.sh needs MSYS_NO_PATHCONV=1 when run from Git Bash
- [P03-T02] P03 next task: preflight calls detect_runner when no runner is set and writes it to project.yaml; then document it in REFERENCE.md
- [P03-T02] Known gaps: gemini Google login without a key, aider keys only in project .env or .aider.conf.yml, cursor-agent installed as 'agent', OPENAI_API_KEY not counted for codex
- [P03-T02] check_login for claude runs with os.environ, not the env argument of detect_runner (only PATH lookup uses env)
- [P03-T02] Live check of kiro-cli whoami / cursor-agent status / codex login status output when logged out
- [P03-T03] ap init writes a short project.yaml without an agent: block, so the runner lines are appended as a new block at the end of the file
- [P03-T03] doctor.checks still shows the claude rows for a project with no runner set before its first preflight
- [P03-T03] config.py was edited (one line in defaults(), as the ADR says) although it was not in the listed files
- [P05-T01] The bash dry-run test returns early on Windows or without bash instead of skipping; it really runs only on WSL/Linux
- [P05-T01] HOWTO.md pins install.sh and install.ps1 SHA-256 values to an old commit; refresh them when the first release tag is made
- [P05-T01] install.yml (protected) could also run `ap --version` in the real-install step
- [P05-T02] Run Vale (CI or locally) to confirm the new README and HOWTO text passes; it was not run because vale is not installed here
- [P05-T02] The README says Codex, Gemini and OpenCode work through presets, but the honest-limits list names six runners without OpenCode; decide whether OpenCode belongs in the supported list
- [P05-T02] Refresh the HOWTO checksums when the first release tag is made (P05-T03)
- [P06-T01] An existing CLAUDE.md that already has the Autopilot heading does not get the new ap command lines
- [P06-T01] A project with both .kiro/ and AGENTS.md gets the instruction twice, because Kiro also reads AGENTS.md
