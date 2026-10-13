# Assignment: replan remaining work

The plan was written before the code existed. Align the REMAINING plan with reality.
You MAY edit exactly two files: `.agent/plan.yaml` and `.agent/BRAIN.md`. Do not touch any other file.

In `.agent/plan.yaml`:
- Never change or remove tasks listed as done. Keep all existing ids stable.
- List the docs a change needs. REFERENCE, CHANGELOG, HOWTO and README are in scope for every task.
- Rewrite pending tasks whose description / acceptance criteria / files_in_scope no longer match the codebase.
- Contract task: when two or more pending tasks in one phase touch the same module, type or API, add one small task first (interfaces, types, stubs, the shared helper's signature). Make the others depends_on it. Keep its files out of the other tasks' files_in_scope.
- Split pending tasks that are too big for one session; merge trivial ones; remove ones already implemented.
- For each BLOCKED task: if it can now succeed with a better spec, rewrite it and add `reopen: true`;
  otherwise leave it blocked.
- New task ids must be unique (e.g. P07-T05b). Keep dependencies valid and acyclic.
- For each NEW IDEA below: if the plan already covers it, leave it out. Otherwise plan it as new pending tasks with
  acceptance criteria, in the open phase it fits or in a new phase at the end. List the new task ids in `added`.
In `.agent/BRAIN.md`: update architecture/conventions to reflect what actually exists (keep < 300 lines).

## Plan status
{{plan_status}}

## Blocked tasks and reasons
{{blocked}}

## Recent decisions
{{decisions}}

## Follow-ups reported by sessions
{{followups}}

## New ideas from the backlog (docs/BACKLOG.md)
{{backlog}}

## Change of the plan source (unified diff of the plan document)
{{source_diff}}
If a diff is shown: each added item becomes a pending task (keep the id the document gives it, for example N8). Update the
task of a changed item. Mark the task of a removed item `status: dropped`; never delete it. Never edit a running or done
task. Keep every top-level key of `plan.yaml`, including `plan_source`.

## Final report (required)
```json
{"summary": "...", "changed": ["task ids"], "added": ["task ids"], "removed": ["task ids"], "reopened": ["task ids"]}
```
