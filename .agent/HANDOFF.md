# Handoff

Last completed: **P05-T01 — Install scripts: Python when missing, `ap` on PATH, one final line** (2026-10-11)

install.sh and install.ps1 now run `uv python install 3.12` only when no Python >= 3.10 is found (command printed in dry-run), check that `ap` is on PATH after the install, and end with exactly: Open a project folder and type `ap`. Two new tests in tests/test_quickstart.py (text checks for both scripts, plus a bash --dry-run test that runs on WSL) pass without any skip marker. tests/test_quickstart.py passes on WSL (22 passed) and ruff is clean. The full WSL suite was not re-run after this retry.

Files: .agent/LEARNINGS.md, HOWTO.md, install.ps1, install.sh, tests/test_quickstart.py

Follow-ups noted:
- The bash dry-run test returns early on Windows or without bash instead of skipping; it really runs only on WSL/Linux
- HOWTO.md pins install.sh and install.ps1 SHA-256 values to an old commit; refresh them when the first release tag is made
- install.yml (protected) could also run `ap --version` in the real-install step

Next planned task: P05-T02
