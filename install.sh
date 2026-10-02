#!/usr/bin/env bash
# Autopilot installer for Linux, macOS and WSL. Options: --dry-run, --skip-login.
# Env: AUTOPILOT_REF (git tag/branch to install), AUTOPILOT_DRY_RUN=1, AUTOPILOT_SKIP_LOGIN=1.
# Safe to run twice. Needs no sudo. Edits no profile file.
set -eu
set -o pipefail

# ponytail: set this to the release tag when the first tag is made
DEFAULT_REF=main

step() { echo "==> Step $1 of 5: $2"; }
fail() { echo "FAILED: step $1. Run this by hand: $2" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
ver() { local v; v=$("$1" --version 2>&1) || true; echo "${v%%$'\n'*}"; }

# ensure <n> <name> <program> <fixed install command>
ensure() {
  step "$1" "$2"
  if have "$3"; then echo "found: $(ver "$3")"; return; fi
  if [ "$dry" = 1 ]; then echo "would install. Command: $4"; return; fi
  echo "run: $4"
  bash -o pipefail -c "$4" || fail "$1" "$4"
  PATH="$HOME/.local/bin:$PATH"
  have "$3" || fail "$1" "$4"
}

main() {
  dry=${AUTOPILOT_DRY_RUN:-0}; skip=${AUTOPILOT_SKIP_LOGIN:-0}
  for a in "$@"; do
    case "$a" in
      --dry-run) dry=1 ;;
      --skip-login) skip=1 ;;
      *) echo "usage: install.sh [--dry-run] [--skip-login]" >&2; exit 2 ;;
    esac
  done
  ref=${AUTOPILOT_REF:-$DEFAULT_REF}
  case "$ref" in
    ''|[!A-Za-z0-9]*|*..*|*[!A-Za-z0-9._/-]*)
      echo "AUTOPILOT_REF must start with a letter or a digit, and may use only A-Z a-z 0-9 . _ / - (no \"..\")" >&2; exit 2 ;;
  esac
  [ "${#ref}" -le 100 ] || { echo "AUTOPILOT_REF is longer than 100 characters" >&2; exit 2; }
  PATH="$PATH:$HOME/.local/bin"   # uv and Claude Code install here; this changes only this script

  step 1 git
  if have git; then
    echo "found: $(ver git)"
  else
    case "${OSTYPE:-}" in
      darwin*) cmd="xcode-select --install" ;;
      *) if have dnf; then cmd="sudo dnf install git"; else cmd="sudo apt install git"; fi ;;
    esac
    if [ "$dry" = 1 ]; then echo "would stop: git is missing. You would run: $cmd"
    else echo "git is missing. This script does not use sudo. Run this, then run the script again: $cmd" >&2; exit 1; fi
  fi

  ensure 2 uv uv "curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"
  ensure 3 "Claude Code" claude "curl --proto '=https' --tlsv1.2 -fsSL https://claude.ai/install.sh | bash"

  step 4 Autopilot
  addr="git+https://github.com/manishjnv/AutoPilot@$ref"
  if have autopilot || { have uv && uv tool list 2>/dev/null | grep dev-autopilot >/dev/null; }; then
    echo "found: $(have autopilot && ver autopilot || echo dev-autopilot)"
    echo "To update, run: uv tool install --reinstall \"$addr\""
  elif [ "$dry" = 1 ]; then
    echo "would install. Command: uv tool install \"$addr\""
  else
    echo "run: uv tool install \"$addr\""
    uv tool install "$addr" || fail 4 "uv tool install \"$addr\""
    have autopilot || fail 4 "uv tool install \"$addr\""
  fi

  step 5 "login check"
  if [ "$skip" = 1 ]; then echo "skipped (--skip-login)"
  elif [ "$dry" = 1 ]; then echo "would run: claude auth status"
  elif claude auth status >/dev/null 2>&1; then echo "Claude Code is logged in."
  else
    echo "Claude Code is not logged in. Run: claude auth login"
    echo "You need a paid Claude plan or an API key. This script does not log in for you."
  fi

  [ "$dry" = 1 ] || echo "Installed: $(ver autopilot)"
  echo "Done. Open a NEW terminal, then run: autopilot"
  echo "To uninstall, run: uv tool uninstall dev-autopilot"
}

main "$@"
