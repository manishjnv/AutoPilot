# Learnings

What fixed tasks that failed first. Written by the orchestrator; read by every session.

- [2026-10-11] [P05-T01] The orchestrator rejects any new skipif marker, even a platform one; guard platform-only parts with a plain `if` inside the test and keep the text checks running everywhere.
