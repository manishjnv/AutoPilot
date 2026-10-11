# Handoff

Last completed: **P05-T02 — README: one install line per system and honest limits** (2026-10-11)

README.md now shows one Windows install line and one macOS/Linux/WSL line (`| bash`), then "Open a project folder and type `ap`.", plus an honest-limits section naming Replit, the Kiro and Cursor chat panels and the six CLI runners. The manual install steps moved to a new HOWTO.md section "Install by hand". Four new tests in tests/test_quickstart.py cover the install lines, the limits, the relative links, and a piped bash dry-run of install.sh. The full WSL suite passes (576 tests) and ruff is clean. Vale was not run because it is not installed here.

Files: .vale/styles/config/vocabularies/Autopilot/accept.txt, HOWTO.md, README.md, tests/test_quickstart.py

Follow-ups noted:
- Run Vale (CI or locally) to confirm the new README and HOWTO text passes; it was not run because vale is not installed here
- The README says Codex, Gemini and OpenCode work through presets, but the honest-limits list names six runners without OpenCode; decide whether OpenCode belongs in the supported list
- Refresh the HOWTO checksums when the first release tag is made (P05-T03)

Next planned task: P06-T01
