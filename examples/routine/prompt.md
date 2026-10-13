# Routine prompt: one Autopilot run in the cloud

Paste this whole file as the prompt of a Claude Code Routine. The routine clones the project repository and works in it.
This prompt has not run live yet (written 2026-10-13). See [the HOWTO section](../../HOWTO.md#run-with-the-laptop-off-claude-code-routines).

You are running one Autopilot build in the cloned repository (the current folder). Do these steps in order. Stop and say
so if a step fails.

1. Install Autopilot:

   ```bash
   uv tool install dev-autopilot
   ```

2. Check the project. This must work before the run starts:

   ```bash
   ap status
   ```

3. Limit this run to three sessions. Open `.agent/project.yaml` and set this key, then save the file:

   ```yaml
   scheduling:
     max_sessions_per_run: 3
   ```

   This change is for this run only. Do not commit it.

4. Run the plan. Do not deploy to production:

   ```bash
   ap run --no-prod
   ```

   Autopilot makes one branch per task, with a name that starts with `autopilot/`. Wait until the run ends.

5. Push each branch that Autopilot made. Do not push any other branch:

   ```bash
   git branch --list "autopilot/*"
   git push origin <branch>
   ```

   Run the push once for each branch in the list.

6. Show the result. The output has a line `outcome: <word>` (for example `outcome: VERIFIED`):

   ```bash
   ap status
   ```

Report the outcome word, the branches you pushed, and anything that stopped the run.
