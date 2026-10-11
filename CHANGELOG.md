# Changelog

- 2026-10-11 **P01-T01** plan.yaml `status: done` marks finished work — Added optional task key `status` (only `done`) to plan.py with validation naming the task id. sync_plan records done tasks as done (note 'done before Autopilot') when the row is new or pending, and ne
- 2026-10-11 **P01-T02** Discovery pack for onboarding — Added discovery_pack(root, cfg) in autopilot/context.py: git log, document tree with plan-file heads, stack files and one capped test run (timeout from onboard.test_timeout_sec, default 300), all capp
- 2026-10-11 **P01-T03** Onboarding prompt: four adopt rules and the pack — onboard.md now carries a {{discovery}} section and the four adopt rules; cmd_onboard builds discovery_pack and passes it to render, and after the session warns with the names of new untracked files ou
