# Security policy

Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.
It is for one developer, or for a person with an idea and a developer friend.

Autopilot runs a coding agent, Claude Code (the program that writes the code), that has shell access. A fault in its guards can damage a computer or leak a secret.
Autopilot masks the values of known secret variables in the error text of a failed deploy.

## What to report

- A way for a session to get past the [trust boundary](ARCHITECTURE.md#10-trust-boundary). Examples are a commit, a
  push, a change to git hooks, or a read of an environment variable that is not on the allowlist.
- A way for a session to change the files that only Autopilot writes, for example `.agent/plan.yaml` (the task list).
- A secret that Autopilot writes to git, to a log, or to the status page.
- A way to read the status page from a different computer without the token.

## How to report

> [!WARNING]
> Do not open a public issue for a security fault.

1. Open the [private report form](https://github.com/manishjnv/AutoPilot/security/advisories/new).
2. Give the version or the commit, the steps to show the fault, and the result.

## What to expect

- This project has one maintainer. You get a first reply in approximately one week.
- Fixes go to the `main` branch. Older versions get no fixes.
- The advisory names you, unless you ask for no name.
- There is no payment for reports.

## Presets that approve every tool

Four presets let the agent run every tool without a prompt. This is not limited to the worktree (the separate copy of the project for one task).

| Preset | Flag | What it allows |
|---|---|---|
| `kiro` | `--trust-all-tools` | Every tool, with no prompt. |
| `cursor` | `--force` | Every command, with no prompt. |
| `copilot` | `--allow-all-tools` and `--no-ask-user` | Every tool, with no prompt, and no question. |
| `gemini` | `--approval-mode=yolo` (`yolo` mode) | Every tool, with no prompt. |

- The worktree is the only boundary. The agent can still reach files and the network outside it.
- These four presets never ran live. Autopilot wrote them from the vendor docs.
- Use them only on a PC and an account where you accept this risk.

## Rights the installer takes

The installer takes rights once, with one prompt, so a later run never asks. On Windows it creates the scheduled task `Autopilot-Setup` with the highest run level. The task runs only `%ProgramData%\Autopilot\setup.ps1`. Only Administrators can change that script. The script installs only `winget` ids from the queue file in the same folder. On Linux it writes `/etc/sudoers.d/autopilot` for `apt-get`, `dpkg`, `snap` and `brew`. You accept this standing elevation when you run the installer on a solo PC. On a shared PC, do not run the installer. Remove the rights with `ap uninstall --rights`.
