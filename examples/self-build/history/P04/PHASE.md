# Phase P04 — N4 `ap` with no arguments does the right thing

- Closed: 2026-10-11
- Status: done
- Cost: $1.13

## Goal
Plain `ap` handles three cases: an empty folder (idea prompt and plan, exists), code without `.agent/` (adopt with N1, one-screen summary, then start), and an Autopilot project (continue, exists).


## Tasks
- [done] P04-T01 One-screen adopt summary: done, open, next
- [done] P04-T02 Plain `ap`: adopt a project that has code and no .agent/
