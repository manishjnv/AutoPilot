# Assignment: document phase {{phase_id}} — {{phase_title}}

You are the documentation session that runs once when a phase closes. You write for a person who did not watch the
build. You may edit ONLY these files: `{{readme}}`, `{{rca}}`, `{{developing}}`, `HOWTO.md` and files under `docs/`. Any change to
another file (code, tests, settings) fails the gate and your whole result is thrown away. Do not run the build or the
tests; do not commit. Python runs the project test command on your result: a red test drops the whole result.

Write in short, plain sentences: active voice, one instruction per sentence, simple words.

Edit sections in place. Before you write, find the section that already covers the change and edit it there. Add a
section only when no section covers it. Never add a second section on the same topic: a result that adds a heading that
already exists in the same file (a second `## Safety`) is dropped whole.

## Last gate output
The last gate output is below. Do not run the test suite.
{{gate_output}}

## Output 1: the RCA log `{{rca}}`
Append one entry for each task below that needed a retry or a repair. Use the heading form the file already uses
(`## <date> · <task id> <title>`) with four lines: Symptom, Root cause, Fix (file and line), Prevention. Read the task's
history file and the LEARNINGS line to find them. Never add a second entry for a task that already has one (search the
file for the task id first). Skip a task you cannot explain; say so in the report summary.

### Tasks that needed a retry or a repair
{{retried}}

### LEARNINGS lines for these tasks
{{learned}}

## Output 2: the README `{{readme}}`
One section per feature the phase shipped: heading `## <feature title>`, then what the user can do and how, from the
journey and the acceptance criteria. If the README has no title yet, add one from the project name. If a section with
that heading exists, update it in place; never add a second one. Keep every other section as it is.
Keep the README short. A test may cap its length: Autopilot's own `tests/test_opening.py` allows at most 1200 words, so stay under the cap. Add detail to HOWTO.md (or a file under `docs/` when there is no HOWTO) and link it from the README.
When the project has a `.vale.ini`, a doc edit must pass `vale --minAlertLevel=warning <file>` and the project's docs tests (for example `tests/test_docs_*.py`) before it is kept: keep sentences under 25 words and table cells under 40 words.

### Features shipped in this phase
{{features}}

## Output 3: `{{developing}}` for a person
How to run, test, deploy and extend the project: the commands from the project contract below, the layout and the
rules from the project brain. Under 200 lines. Create it if missing; otherwise update the sections that changed.

### Project commands (`.agent/project.yaml`)
{{commands}}

### Project brain (BRAIN.md, capped)
{{brain}}

### What exists now
- README headings: {{readme_headings}}
- RCA entries: {{rca_ids}}
- {{developing}}: {{developing_state}}

## Final report (required, last thing in your reply)
```json
{"summary": "1-3 sentences: what you wrote and what you skipped", "files": ["each file you changed"]}
```
