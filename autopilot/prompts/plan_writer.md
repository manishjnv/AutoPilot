# Assignment: write the build plan for a new project

The owner described what they want built (below). Turn it into `PLAN.md` at the repository root: a complete
architecture and phased build plan that autonomous coding sessions will follow without asking questions. Write only
`PLAN.md`; do not create any other file or code.

Do not ask the owner anything. Where the idea leaves a choice open, pick the simplest option a careful senior
engineer would pick for a solo developer, and list it under "Assumptions". Prefer a small, well-tested first version
over many features.

## Structure of PLAN.md

### Part 1: Architecture
1. **Product**: what it does, for whom, in scope and out of scope.
2. **Hard invariants**: 4-8 rules every task must keep (security, data safety, determinism, dependencies).
3. **Stack and conventions**: language and version, layout, packaging, lint and test tools, exit codes or API shape.
4. **Modules**: each module or component with its responsibility and its interface (functions, endpoints, data
   types).
5. **Data flow**: one short paragraph or diagram.
6. **Testing strategy**: unit, end-to-end and any special checks. Tests must run offline and without real secrets.
7. **Assumptions**: every choice you made that the idea did not specify.

### Part 2: Build plan
- The project commands (setup, lint, typecheck, test), and a first task that creates the tooling they need.
- 3-5 phases. Each has a goal and a **feature check**: one user journey to run on the working app at the end of the
  phase.
- Each phase has 2-5 tasks. Each task is small enough for ONE coding session (about 1-3 files of real logic) and has:
  a title, a risk (low | medium | high | critical; high or critical for auth, payments, crypto, data migrations),
  what to build, 2-5 testable acceptance criteria, and the files in scope.
- A short **Definition of done**.

## The owner's idea
{{idea}}

## Final report (required)
```json
{"summary": "...", "phases": 0, "tasks": 0, "assumptions": ["..."]}
```
