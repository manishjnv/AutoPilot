# Assignment: onboard this repository into Autopilot

Prepare the project so hundreds of autonomous sessions can build it without human help.
You MAY edit: `.agent/plan.yaml`, `.agent/BRAIN.md`, `.agent/project.yaml`, `CLAUDE.md`. Do not change application code.

Four rules for a project that already has work in it:
- Rule 1, read before write: read the discovery pack and the documents it lists before you write anything.
- Rule 2, done work stays done: work that already exists in the code or in the git log gets `status: done` in
  plan.yaml. Keep its task and mark it done. Do not delete it and do not plan it again.
- Rule 3, link, do not copy: BRAIN.md links the existing documents. It does not copy them.
- Rule 4, keep the author's file names: rename or move a file only with a reason, and write that reason in the final
  report.
Also: write no new document outside `.agent/` and CLAUDE.md. If there is no plan document, take the plan from the
documents in the pack (PLAN.md, ROADMAP, TODO, notes).

1. Inspect the repository (may be empty), the discovery pack and the plan document below.
2. `.agent/BRAIN.md`: product, architecture, stack & conventions, invariants, how to run. Concise, factual.
   Only when the code has clear layers, add a fenced block with the language `layers`: one line per layer,
   `name: path/glob`, top to bottom. A higher layer may import a lower one, never the reverse. The gate checks it.
   Do not write the block when the layers are not clear.
3. `.agent/project.yaml`: set `name`, `stack` and real `commands` (setup/build/lint/typecheck/test). If the repo is
   empty, choose commands that the first phase will make valid, and make the first task create that tooling.
   Keep every other key as is.
4. `.agent/plan.yaml`: convert the plan document into phases and tasks following the existing schema:
   - every task small enough for ONE session (~1-3 files of real logic), with a clear title and description
   - 2-5 testable acceptance_criteria per task, files_in_scope globs (required: the real files or folders the task edits; the gate fails any other file; an empty list means the whole repository and the task runs alone), risk tier
     (critical/high for auth, payments, tenant isolation, crypto, data migrations)
   - explicit depends_on only where order inside a phase matters
   - contract task: when two or more tasks in one phase touch the same module, type or API, write one small task first (interfaces, types, stubs, the shared helper's signature). Make the others depends_on it. Keep its files out of the other tasks' files_in_scope. Two tasks that share a file get a depends_on edge, so they never run in parallel.
   - stable ids: P01-T01, P01-T02, ...
   - keep the author's phase structure and intent; do not invent unrelated features
5. Validate your YAML mentally: unique ids, only known dependency ids, no cycles.

## Discovery pack
{{discovery}}

## Plan document
{{plan_doc}}

## Final report (required)
```json
{"summary": "...", "phases": 0, "tasks": 0, "assumptions": ["..."]}
```
