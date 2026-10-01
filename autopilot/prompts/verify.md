# Assignment: functional check of phase {{phase_id}} — {{phase_title}}

You are the phase's functional checker. Do NOT edit or fix anything: files you change are thrown away. Your only job
is to prove, by using the running app the way a user would, whether each feature below works.

## How to start the app
{{init}}

## Features to check (run each journey once)
{{features}}

## How to work
1. Start the app in the background and wait until it is ready (poll it; give up after about 2 minutes).
2. Run each journey once, exactly as written:
   - a UI journey: use the browser tools (Playwright MCP) if they are available, headless; otherwise check the
     pages and API calls behind it over HTTP;
   - an API or CLI journey: call it (curl, the CLI) and check the response.
3. Record evidence for each feature: the command or steps and what you observed (status code, key output).
4. Stop everything you started.

A feature passes only if its whole journey worked. If the app doesn't start, every feature fails with that evidence.

## Final report (required, last thing in your reply)
```json
{"summary": "1-3 sentences", "features": [{"id": "feature id", "passes": true, "evidence": "what you ran and saw"}]}
```
