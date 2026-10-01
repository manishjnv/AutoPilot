# Assignment: unstick task {{task_id}} — {{task_title}}

This task keeps failing. You are a separate, READ-ONLY review session: do not edit files. Find out why and decide how to
proceed so the build can continue without the owner whenever that is possible.

## Task
{{description}}

### Acceptance criteria
{{acceptance}}

## Phase goal
{{phase_goal}}

## Recent decisions
{{decisions}}

## Last error
```
{{error}}
```

## What to do
1. Find the root cause (read the code and the error; run the checks if useful).
2. You MAY use WebSearch / WebFetch for documentation, competitors and best practice.
3. Classify the situation:
   - `technical`: a fixable bug or mistake. Give a precise diagnosis and fix plan.
   - `spec`: unclear spec or a product choice that has a clear best practice. Pick one and list the options considered.
   - `owner`: needs credentials, an account, a paid service, a legal/business decision, or taste with no clear best
     practice. Write the question in plain words for a non-technical owner.

## Final report (required, last thing in your reply)
```json
{"class": "technical | spec | owner", "diagnosis": "root cause and fix plan", "decision": "what was decided (spec)",
 "options_considered": ["..."], "question": "plain-words question (owner)", "checked": "what you looked at",
 "why": "why only the owner can decide (owner)", "suggestion": "your recommended answer (owner)"}
```
