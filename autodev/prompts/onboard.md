# Assignment: onboard this repository into AutoDev

Prepare the project so hundreds of autonomous sessions can build it without human help.
You MAY edit: `.agent/plan.yaml`, `.agent/BRAIN.md`, `.agent/project.yaml`, `CLAUDE.md`. Do not change application code.

1. Inspect the repository (may be empty) and the plan document below.
2. `.agent/BRAIN.md`: product, architecture, stack & conventions, invariants, how to run. Concise, factual.
3. `.agent/project.yaml`: set `name`, `stack` and real `commands` (setup/build/lint/typecheck/test). If the repo is
   empty, choose commands that the first phase will make valid, and make the first task create that tooling.
   Keep every other key as is.
4. `.agent/plan.yaml`: convert the plan document into phases and tasks following the existing schema:
   - every task small enough for ONE session (~1-3 files of real logic), with a clear title and description
   - 2-5 testable acceptance_criteria per task, files_in_scope globs, risk tier
     (critical/high for auth, payments, tenant isolation, crypto, data migrations)
   - explicit depends_on only where order inside a phase matters
   - stable ids: P01-T01, P01-T02, ...
   - keep the author's phase structure and intent; do not invent unrelated features
5. Validate your YAML mentally: unique ids, only known dependency ids, no cycles.

## Plan document
{{plan_doc}}

## Final report (required)
```json
{"summary": "...", "phases": 0, "tasks": 0, "assumptions": ["..."]}
```
