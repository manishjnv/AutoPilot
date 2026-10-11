# Handoff

Last completed: **P03-T03 — Preflight writes the detected runner to project.yaml** (2026-10-11)

preflight(cfg) now reads the raw project.yaml. When it sets no backend, command or preset, preflight calls detect_runner and writes backend/preset as a comment-keeping text edit that is parse-checked before the write. It prints `runner: <binary> (found on PATH)`, or prints the Claude Code install command and the supported CLIs and returns False when none is found. The template backend line is commented out and config.defaults() keeps claude_cli as the in-memory default. 8 new tests, including a smoke test where a fake kiro-cli runs one task to done through the Orchestrator; WSL suite 570 passed, ruff clean.

Files: .agent/DECISIONS.md, .agent/HANDOFF.md, HOWTO.md, REFERENCE.md, autopilot/cli.py, autopilot/config.py, autopilot/templates/agent/project.yaml, tests/test_runner_detect.py

Follow-ups noted:
- ap init writes a short project.yaml without an agent: block, so the runner lines are appended as a new block at the end of the file
- doctor.checks still shows the claude rows for a project with no runner set before its first preflight
- config.py was edited (one line in defaults(), as the ADR says) although it was not in the listed files

Next planned task: P04-T01
