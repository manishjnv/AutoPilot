# Assignment: repair the main branch

The main branch fails the project's verification gate. Nothing else can proceed until it is green.
Find the root cause and fix it with the smallest correct change. Do not delete or weaken tests to make them pass
unless a test is itself provably wrong (then explain why in the report).

## Recent decisions
{{decisions}}

## Recent commits
```
{{git_log}}
```

## Failing checks
```
{{errors}}
```

Verify commands (run them until green):
{{verify_cmds}}

## Final report (required)
```json
{"status": "done | blocked", "summary": "what was broken and what you changed", "root_cause": "...", "rca": {"symptom": "...", "root_cause": "...", "fix": "file:line — what changed", "prevention": "the test or check that stops a repeat"}, "decisions": [], "blocker": ""}
```
