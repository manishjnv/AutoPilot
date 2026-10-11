# Handoff

Last completed: **P03-T02 — Detect the installed and logged-in runner** (2026-10-11)

Added detect_runner(env=None) to autopilot/doctor.py: a RUNNERS table (claude, kiro-cli, cursor-agent, codex, gemini, aider) checked in order with shutil.which on env PATH; a non-empty documented key variable counts first, then check_login for claude or a read-only status command (whoami / status / login status) via run_proc with LOGIN_TIMEOUT=10, exit 0 without logged-out wording. _run and check_login got a defaulted timeout kwarg. 9 tests with fake executables on a tmp PATH cover every acceptance criterion; ruff clean, full WSL suite 562 passed.

Files: autopilot/doctor.py, tests/test_runner_detect.py

Follow-ups noted:
- P03 next task: preflight calls detect_runner when no runner is set and writes it to project.yaml; then document it in REFERENCE.md
- Known gaps: gemini Google login without a key, aider keys only in project .env or .aider.conf.yml, cursor-agent installed as 'agent', OPENAI_API_KEY not counted for codex
- check_login for claude runs with os.environ, not the env argument of detect_runner (only PATH lookup uses env)
- Live check of kiro-cli whoami / cursor-agent status / codex login status output when logged out

Next planned task: P03-T03
