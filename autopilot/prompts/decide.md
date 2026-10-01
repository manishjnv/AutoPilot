# Assignment: decide the approach for task {{task_id}} — {{task_title}}

You are a separate, READ-ONLY design session: do not edit files. Another session will implement this task next and
must follow your decision. Pick the best approach before any code is written.

## Project goal
{{goal}}

## Phase goal
{{phase_goal}}

## Task
Risk tier: {{risk}}
{{description}}

### Acceptance criteria
{{acceptance}}

### Files in scope
{{scope}}

## Project brain
{{brain}}

## Recent decisions (stay consistent)
{{decisions}}

{{research_block}}

## What to do
1. Read the relevant code to see what already exists and what the task touches.
2. You MAY use WebSearch / WebFetch for library docs, competitors and best practice.
3. List the decision drivers (3-5 criteria such as correctness, security, simplicity, fit with the existing code, cost).
4. Weigh 2-3 realistic options against them. Score each 1-10. Prefer the simplest option that meets the criteria.
5. Choose one. Be concrete: name libraries, data shapes, files and interfaces, so the implementer can follow it.

## Final report (required, last thing in your reply)
```json
{"title": "short decision title", "context": "the problem in 2-4 sentences",
 "criteria": ["decision driver", "..."],
 "options": [{"name": "...", "summary": "...", "pros": ["..."], "cons": ["..."], "score": 8}],
 "decision": "name of the chosen option", "rationale": "why it wins against the criteria",
 "consequences": ["what follows for the implementation, good or bad"]}
```
