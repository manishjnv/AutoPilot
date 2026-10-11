#!/usr/bin/env bash
# Autopilot installer for Linux, macOS and WSL. Options: --dry-run, --skip-login.
# Env: AUTOPILOT_REF (git tag/branch to install), AUTOPILOT_DRY_RUN=1, AUTOPILOT_SKIP_LOGIN=1.
# Safe to run twice. One sudo at most (N8): it installs git when missing and writes /etc/sudoers.d/autopilot, so later
# runs install system tools with no password. Edits no profile file. `ap uninstall --rights` removes the sudoers file.
set -eu
set -o pipefail

# ponytail: set this to the release tag when the first tag is made
DEFAULT_REF=main

step() { echo "==> Step $1 of 6: $2"; }
fail() { echo "FAILED: step $1. Run this by hand: $2" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
ver() { local v; v=$("$1" --version 2>&1) || true; echo "${v%%$'\n'*}"; }

# A Python >= 3.10 on PATH (N5)
pyok() { local p; for p in python3 python; do have "$p" && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && return 0; done; return 1; }

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

  # N8: the one consent. Starting this script is the consent; nothing below asks again.
  echo "This script installs: git (sudo, when missing), uv, Claude Code, Python 3.12 (when missing), Autopilot."
  case "${OSTYPE:-}" in
    darwin*) echo "Rights it takes: none (brew needs none)." ;;
    *) echo "Rights it takes: one sudo now, and /etc/sudoers.d/autopilot so later runs install system tools with no" \
            "password (apt-get, dpkg, snap, brew). Remove it later with: ap uninstall --rights" ;;
  esac

  step 1 git
  if have git; then
    echo "found: $(ver git)"
  else
    case "${OSTYPE:-}" in
      darwin*) cmd="xcode-select --install" ;;
      *) if have dnf; then cmd="sudo dnf install -y git"; else cmd="sudo apt-get install -y git"; fi ;;
    esac
    if [ "$dry" = 1 ]; then echo "would install. Command: $cmd"
    else echo "run: $cmd"; bash -c "$cmd" || fail 1 "$cmd"; have git || fail 1 "$cmd"; fi
  fi

  ensure 2 uv uv "curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"
  ensure 3 "Claude Code" claude "curl --proto '=https' --tlsv1.2 -fsSL https://claude.ai/install.sh | bash"

  step 4 Autopilot
  # N5: Autopilot cannot run without Python 3.10 or newer. This is the one system install; uv installs it for this user.
  pycmd="uv python install 3.12"
  if pyok; then echo "found: $(have python3 && ver python3 || ver python)"
  elif [ "$dry" = 1 ]; then echo "would run (no Python 3.10 or newer found). Command: $pycmd"
  else
    echo "run: $pycmd"
    uv python install 3.12 || fail 4 "$pycmd"
  fi
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
  if [ "$dry" = 1 ]; then echo "would check: ap is on PATH"
  elif have ap; then echo "found: ap"
  else fail 4 "uv tool install --reinstall \"$addr\" (then make sure $HOME/.local/bin is on PATH)"; fi

  step 5 "login check"
  if [ "$skip" = 1 ]; then echo "skipped (--skip-login)"
  elif [ "$dry" = 1 ]; then echo "would run: claude auth status"
  elif claude auth status >/dev/null 2>&1; then echo "Claude Code is logged in."
  else
    echo "Claude Code is not logged in. Run: claude auth login"
    echo "You need a paid Claude plan or an API key. This script does not log in for you."
  fi

  step 6 "rights for later installs"
  sudoers=/etc/sudoers.d/autopilot
  line="${USER:-${LOGNAME:-$(id -un 2>/dev/null || echo me)}} ALL=(root) NOPASSWD: /usr/bin/apt-get, /usr/bin/dpkg, /usr/bin/snap, /usr/local/bin/brew"
  case "${OSTYPE:-}" in
    darwin*) echo "none needed on macOS" ;;
    *) if [ -f "$sudoers" ]; then echo "found: $sudoers"
       elif [ "$dry" = 1 ]; then echo "would write $sudoers (one sudo): $line"
       elif ! have sudo; then echo "no sudo on this machine: later runs print the install command instead"
       else
         echo "run: sudo tee $sudoers (one sudo; the file is checked with visudo)"
         if printf '%s\n' "$line" | sudo tee "$sudoers" >/dev/null && sudo chmod 0440 "$sudoers" \
            && sudo visudo -cf "$sudoers" >/dev/null; then echo "wrote $sudoers"
         else sudo rm -f "$sudoers" 2>/dev/null || true; echo "could not write $sudoers: later runs print the install command instead"; fi
       fi ;;
  esac

  [ "$dry" = 1 ] || echo "Installed: $(ver autopilot)"
  echo "To uninstall, run: uv tool uninstall dev-autopilot (and ap uninstall --rights)"
  echo "Done. Open a NEW terminal if \`ap\` is not found."
  echo 'Open a project folder and type `ap`.'
}

main "$@"
