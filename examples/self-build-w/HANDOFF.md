# Handoff

Last completed: **P14-T03 — REFERENCE entries for the plugin Stop hook and the Routine page** (2026-10-13)

REFERENCE.md `## Proof features` now has a `### Stop hook in the plugin` subsection (seal.py's two checks, the 300 s test limit, the 330 s hook timeout in hooks.json, the 5-block counter file, `/plugin disable autopilot`, no load in Autopilot's own sessions) and a `### Routine` subsection (links HOWTO and examples/routine/prompt.md, the max_sessions_per_run: 3 local edit, "not run live yet"). Three tests in tests/test_plugin_hook.py pin the numbers and links to seal.py and hooks.json; the 9 tests in that file pass and ruff passes. The WSL script stopped at a pre-existing README word-count failure (not caused by this change), so the full suite did not finish.

Files: REFERENCE.md, tests/test_plugin_hook.py

Follow-ups noted:
- tests/test_opening.py::test_readme_states_the_position_and_the_safety_block fails on the current README: 1334 words against a 1200 limit. README was not changed in this task; the WSL run stopped at this failure (-x), so the rest of the suite was not run under WSL
- The README has no plugin hook or Routine link; add them when the README is next trimmed

Next planned task: (none)
