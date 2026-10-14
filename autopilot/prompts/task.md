# Assignment: implement task {{task_id}} — {{task_title}}

## Current phase: {{phase_id}} — {{phase_title}}
{{phase_goal}}

## Task
Risk tier: {{risk}}
{{description}}

### Acceptance criteria (all must hold)
{{acceptance}}

### Files in scope
{{scope}}
The gate fails a change to any file outside this list (tests, docs, README and CHANGELOG are always allowed). List the docs a change needs. REFERENCE, CHANGELOG, HOWTO and README are in scope for every task. On a retry (attempt 2 or later) you may name up to 3 more files in the report under `scope_additions` with a reason; on the first attempt leave every other file unchanged.

### Docs to update
{{docs}}

## Recent decisions (stay consistent)
{{decisions}}

## Owner answers (follow these exactly)
{{owner_answers}}

{{adr_block}}

{{research_block}}

## Existing helpers (reuse before you write)
Reuse or extend a listed helper before you write a new one. A new helper with the same job as a listed one is a defect.
```
{{helper_index}}
```

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
3. {{test_rule}}
4. Run the build, lint and typecheck commands below and fix failures before finishing. Run the tests of the files you changed. The gate runs the full suite at the phase close. Do not run the full test command yourself. Tests that already fail before your change: list them in the report under `failing_before` (node ids such as `tests/test_x.py::test_y`). Never skip, deselect, xfail or delete a test to get green; each name is checked against main, and a name that passes on main fails your attempt.
{{verify_cmds}}
5. Update documentation touched by this change (README, API docs, docstrings, the docs listed above).
6. If the task is genuinely impossible (missing external dependency, contradictory spec), stop and report "blocked" with a precise reason — do not fake it.

## Final report (required, last thing in your reply)
`rca` is only for corrective tasks; leave it out otherwise.
`new_files` lists each new non-test file with its reason; leave it out when you added none.
`contracts` names each feature contract shown above: `kept`, or `changed` with a `why`. The gate fails a removed test, fewer tests in a file, or a deleted page of a contract unless its entry says `changed` with a reason. An edited `features/<id>.md` needs a new dated line under `## Changes`.
```json
{
  "status": "done | blocked",
  "summary": "2-4 sentences: what you built and how it is verified",
  "files_changed": ["path", "..."],
  "tests_added": ["path::test_name", "..."],
  "docs_updated": ["path", "..."],
  "decisions": ["decision — reason (only architecture/interface/convention choices later sessions must follow)"],
  "followups": ["work you noticed that is out of scope for this task"],
  "new_files": [{"path": "src/new_module.py", "reason": "why no existing file can own this content"}],
  "scope_additions": {"src/other.py": "why this file outside the task scope had to change (omit when none)"},
  "new_deps": [{"name": "package", "reason": "why no installed dependency does this (omit when none)"}],
  "failing_before": ["path::test_name (omit when none)"],
  "contracts": [{"id": "gate", "status": "kept | changed", "why": "only for changed: why the contract had to change (omit the field when no contract was shown)"}],
  "rca": {"symptom": "...", "root_cause": "...", "fix": "file:line — what changed", "prevention": "the test or check that stops a repeat"},
  "blocker": "only when status is blocked"
}
```

A fake secret in a test is built from pieces (`'sk-' + 'a' * 24`), never written as one literal: the secret scan cannot tell a fake key from a real one.
