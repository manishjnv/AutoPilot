# Assignment: replan remaining work

The plan was written before the code existed. Align the REMAINING plan with reality.
You MAY edit exactly two files: `.agent/plan.yaml` and `.agent/BRAIN.md`. Do not touch any other file.

In `.agent/plan.yaml`:
- Never change or remove tasks listed as done. Keep all existing ids stable.
- Rewrite pending tasks whose description / acceptance criteria / files_in_scope no longer match the codebase.
- Split pending tasks that are too big for one session; merge trivial ones; remove ones already implemented.
- For each BLOCKED task: if it can now succeed with a better spec, rewrite it and add `reopen: true`;
  otherwise leave it blocked.
- New task ids must be unique (e.g. P07-T05b). Keep dependencies valid and acyclic.
In `.agent/BRAIN.md`: update architecture/conventions to reflect what actually exists (keep < 300 lines).

## Plan status
{{plan_status}}

## Blocked tasks and reasons
{{blocked}}

## Recent decisions
{{decisions}}

## Follow-ups reported by sessions
{{followups}}

## Final report (required)
```json
{"summary": "...", "changed": ["task ids"], "added": ["task ids"], "removed": ["task ids"], "reopened": ["task ids"]}
```
