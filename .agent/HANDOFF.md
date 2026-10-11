# Handoff

Last completed: **P03-T01 — Presets for kiro, cursor and aider** (2026-10-11)

Added kiro, cursor and aider presets to PRESETS in autopilot/backends/command.py, following the ADR. The model option is --model for these three (_MODEL_OPT), and a {prompt_file} placeholder lets aider read the prompt from a temp file outside the worktree that is removed after the run. New parametrized tests run each preset through CommandBackend with a fake executable of that name on PATH and check the parsed report, the flags, the model flag, unsafe model names, and that codex/gemini/opencode are byte-identical. Ruff is clean and the full WSL suite passes (553 tests).

Files: .agent/DECISIONS.md, REFERENCE.md, autopilot/backends/command.py, autopilot/templates/agent/project.yaml, tests/test_presets.py

Follow-ups noted:
- config.py:95 error text still lists only codex, gemini, opencode
- HOWTO.md:329 and README.md:123 name only the old presets
- Live check of kiro-cli, cursor-agent and aider; especially whether cursor-agent reads stdin (fallback: _ASK pointing to {prompt_file})
- wsltest_self.sh needs MSYS_NO_PATHCONV=1 when run from Git Bash

Next planned task: P03-T02
