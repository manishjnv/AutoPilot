# Assignment: implement task {{task_id}} — {{task_title}}

## Project goal
{{goal}}

## Current phase: {{phase_id}} — {{phase_title}}
{{phase_goal}}

## Task
Risk tier: {{risk}}
{{description}}

### Acceptance criteria (all must hold)
{{acceptance}}

### Files in scope
{{scope}}

### Docs to update
{{docs}}

## Project brain (architecture, conventions, invariants)
{{brain}}

## Recent decisions (stay consistent)
{{decisions}}

## Owner answers (follow these exactly)
{{owner_answers}}

{{adr_block}}

{{research_block}}

## Previous session handoff
{{handoff}}

## Overall progress
{{progress}}

{{retry_block}}

{{fix_rules}}

## Recent commits
```
{{git_log}}
```

## How to work
1. Read the relevant existing code first. Follow the existing conventions in BRAIN.md.
2. Implement the task completely — no stubs, TODOs or placeholder logic for anything in the acceptance criteria.
3. Add or extend automated tests that prove each acceptance criterion.
4. Run the project's checks yourself and fix failures before finishing:
{{verify_cmds}}
5. Update documentation touched by this change (README, API docs, docstrings, the docs listed above).
6. If the task is genuinely impossible (missing external dependency, contradictory spec), stop and report "blocked" with a precise reason — do not fake it.

## Final report (required, last thing in your reply)
`rca` is only for corrective tasks; leave it out otherwise.
```json
{
  "status": "done | blocked",
  "summary": "2-4 sentences: what you built and how it is verified",
  "files_changed": ["path", "..."],
  "tests_added": ["path::test_name", "..."],
  "docs_updated": ["path", "..."],
  "decisions": ["decision — reason (only architecture/interface/convention choices later sessions must follow)"],
  "followups": ["work you noticed that is out of scope for this task"],
  "rca": {"symptom": "...", "root_cause": "...", "fix": "file:line — what changed", "prevention": "the test or check that stops a repeat"},
  "blocker": "only when status is blocked"
}
```
