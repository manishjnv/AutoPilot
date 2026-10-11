# Handoff

Last completed: **P06-T01 — Autopilot block in IDE rule files and CLAUDE.md** (2026-10-11)

cmd_init now calls write_ide_rules(): it appends or creates one marked Autopilot block in Cursor (.mdc with alwaysApply), Kiro steering, Copilot instructions, GEMINI.md and AGENTS.md when the IDE marker exists. The user's bytes are never changed and a second init writes nothing. CLAUDE.md.snippet now lists ap status, ap next and ap start. Verified by 4 new tests and the full WSL suite (580 passed); ruff is clean.

Files: REFERENCE.md, autopilot/cli.py, autopilot/templates/agent/CLAUDE.md.snippet, autopilot/templates/agent/ide_rules.md, tests/test_ide_rules.py

Follow-ups noted:
- An existing CLAUDE.md that already has the Autopilot heading does not get the new ap command lines
- A project with both .kiro/ and AGENTS.md gets the instruction twice, because Kiro also reads AGENTS.md

Next planned task: P07-T01
