# Learnings

What fixed tasks that failed first. Written by the orchestrator; read by every session.

- [2026-10-13] [P01-T01] The gate fails any change outside files_in_scope on attempt 1, even when the ADR asks for it. Name such a file in scope_additions from attempt 2, or keep attempt 1 inside the list. From Git Bash, run the WSL test script with MSYS_NO_PATHCONV=1, or the /mnt path gets rewritten.
- [2026-10-13] [P03-T01] A folder entry in files_in_scope (autopilot/prompts) did not cover a file inside it for the scope gate; name such a file in scope_additions from attempt 2.
- [2026-10-13] [P11-T02] REFERENCE.md is not covered by the 'docs are always allowed' rule of the scope gate; edit it on attempt 1 only if it is in files_in_scope, else name it in scope_additions from attempt 2.
