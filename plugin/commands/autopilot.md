---
description: Start, follow, answer or stop an Autopilot build (status | stop | answer | <your idea>)
argument-hint: "[status | stop | answer | what to build]"
---

You help the user control Autopilot, a CLI that builds a project with Claude Code sessions. All logic is in the
`autopilot` CLI: only run its commands, never edit its files. Show each command before you run it.

Two rules for commands:

- **When you run a command yourself,** use the long form with the folder, for example
  `autopilot status -C "<folder>"`. The chat can be in a different folder.
- **When you tell the user a command to type,** always give the short form with no folder: `ap status`,
  `ap watch`, `ap stop`, `ap start`, `ap answer`. The short commands find the project. Never show the user `-C`,
  a folder path, or the word `autopilot` in a command to type. This rule applies to every reply, also to "next
  steps" lists.

The user typed: `$ARGUMENTS`

Do one of these:

1. **Empty, or `status`:** if the current folder has `.agent/project.yaml`, run `autopilot status`. If it does not,
   ask what to build and in which folder, then continue as in step 4.
2. **`stop`:** run `autopilot stop`. The run stops before its next session.
3. **`answer`:** show the open questions in `docs/NEEDS-YOU.md`. Ask the user for each answer. Send each one with
   `autopilot answer D-001 "the answer"`.
4. **Any other text is the idea to build:**
   1. Run `autopilot --version`. If the command is not found, ask before you install it with
      `uv tool install git+https://github.com/manishjnv/AutoPilot`. If `uv` is not found, show the tutorial
      <https://github.com/manishjnv/AutoPilot/blob/main/GUIDE.md> and stop.
   2. Run `claude auth status`. If it shows no login, tell the user to run `claude auth login` and stop.
   3. Ask for the folder. Refuse the home folder and the root of a drive. A new folder is best.
   4. Tell the user: the build runs for hours, it uses the same Claude plan as this chat, and it works without
      questions. Wait for "go".
   5. Run `autopilot quickstart -C "<folder>" --idea "<the idea>" --run --detach`. The `--detach` flag starts a
      separate process, so the build continues after this chat closes.
   6. Wait one minute. Show the last 20 lines of `<folder>/.agent/logs/detached.log`.
   7. Tell the user the short commands for a terminal: `ap watch` (follow the build), `ap status`, `ap stop`,
      `ap start` (continue the build). They need no folder. Do not show the long `autopilot ... -C` form.

Do not start a second build in a folder that has an active run: `autopilot status` shows it.
