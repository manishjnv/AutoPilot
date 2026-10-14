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

## What the updater trusts

The update that runs by itself gets the newest release from GitHub (`gh` when present, else the public releases
API, no login). It installs a wheel only when its SHA256 matches the `SHA256SUMS` file of that release. A release
exists only after CI is green on Linux and Windows. The updater never runs while a build is active, and the way back
is one command: `ap upgrade --ref vX.Y.Z`. Stop it with `upgrade.auto: false` in `.agent/project.yaml` or
`AUTOPILOT_NO_AUTO_UPGRADE=1`.

## Rights the installer takes

The installer takes rights once, with one prompt, so a later run never asks. This is a feature. The build never stops for a password.

> [!WARNING]
> Do not run the installer on a shared PC. Any process that runs as your user can then install packages with full rights, and an AI session is such a process.

**What the installer grants**

| System | What is created | What it allows |
|---|---|---|
| Windows | The scheduled task `Autopilot-Setup` with the highest run level | The task runs only `%ProgramData%\Autopilot\setup.ps1`. Only Administrators can change that script. It installs only `winget` ids from the queue file in the same folder. |
| Linux and WSL | The file `/etc/sudoers.d/autopilot` | Your user runs `apt-get`, `dpkg`, `snap` and `brew` as root, with no password. |
| macOS | Nothing | `brew` needs no rights. |

**Why Autopilot needs this.** A task sometimes needs a system tool, such as a compiler or a database. Without these rights, the run stops and waits for a password. With them, Autopilot installs the tool, writes it to the log, and goes on.

**What this means for you.** You accept a standing elevation. Any process that runs as your user can install packages as root (Linux) or as administrator (Windows), without a prompt. This includes a Claude Code session that Autopilot starts. Package installs can run code, so treat these rights as admin rights.

**Who should not use it.** Do not run the installer on a shared PC or on a machine with data that you cannot lose. Use a personal PC or a virtual machine for the build.

**How to remove it.** Run `ap uninstall --rights` to remove only the rights. Run `ap uninstall --all` to remove the rights and Autopilot. Run `ap doctor` to check the state. It shows the line `rights` with the result.

## Docker sandbox

With `sandbox.mode: docker` each Claude Code session runs in a container from `sandbox.image`. The container protects
the rest of the computer: only the worktree (at `/work`), its git folders (the shared one read-only) and a temp copy
of the login file are mounted. Your home folder is not mounted, and secret variables pass by name only, so their values
never appear in the command line. The container and the temp folder are removed after each session.

It does not protect the network. The API host must be reachable, and the default `bridge` network is open egress
unless `sandbox.enabled: true` also turns on the allowlist. A mount outside the worktree, such as an absolute
`mcp_config` path, is not visible inside the container.

## The plugin Stop hook and the project list

The Claude Code plugin's Stop hook runs the project test command only in a folder that `ap init`, `ap quickstart`, `ap run` or `ap start` registered in `~/.autopilot/projects.txt`. This stops a hostile clone that you only open in Claude Code from running a command. It is not a boundary against a session that already runs on your computer: such a session can write that file. Autopilot's own build sessions never load the plugin.
