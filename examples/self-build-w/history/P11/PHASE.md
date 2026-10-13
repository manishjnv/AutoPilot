# Phase P11 — W11 sandbox.mode: docker

- Closed: 2026-10-13
- Status: done
- Cost: $3.96

## Goal
The Claude CLI can start inside a plain Docker container with only the worktree (and its git folders) mounted. Note: `docker sandbox` was removed in Docker 29; use `docker run`.


## Tasks
- [done] P11-T01 sandbox.mode key: the one mode rule and its config checks
- [done] P11-T02 docker run wrapper for the Claude CLI backend
- [done] P11-T03 Doctor docker line, gate reader and the docker docs
