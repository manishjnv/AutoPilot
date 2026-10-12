#!/usr/bin/env bash
# Autopilot installer for Linux, macOS, WSL and Git Bash (handed to install.ps1). Options: --dry-run, --skip-login,
# --runner NAME, --yes. Env: AUTOPILOT_REF (git tag or branch), AUTOPILOT_DRY_RUN=1, AUTOPILOT_SKIP_LOGIN=1,
# AUTOPILOT_RUNNER=NAME. Four steps (pre-check, uv, Python, the package), then `ap setup` chooses and installs the one
# AI runner you pay for. No sudo, no profile edit, safe to run twice. Q4: tool output goes to ~/.autopilot/install.log;
# the screen gets one sentence and one command per failure. Q5: keep this file under 150 lines; the logic is in Python.
set -eu
set -o pipefail

# ponytail: set this to the release tag when the first tag is made
DEFAULT_REF=v0.4.0
RAW=https://raw.githubusercontent.com/manishjnv/AutoPilot

step() { echo "==> Step $1 of 5: $2"; }
have() { command -v "$1" >/dev/null 2>&1; }
ver() { local v; v=$("$1" --version 2>&1) || true; echo "${v%%$'\n'*}"; }
CURL_OPTS=""

# One sentence for the common failures (the full catalogue lives in autopilot/install_errors.py); the rest is generic.
explain() {
  local t; t=$(tail -c 4000 "$1" 2>/dev/null || true)
  case "$t" in
    *CRYPT_E_NO_REVOCATION_CHECK*|*"curl: (35)"*) echo "Windows could not check the certificate of the download server (a proxy or a security program blocks the revocation check)." ;;
    *"Could not resolve host"*|*getaddrinfo*) echo "No connection to the download server: check the network, and set HTTPS_PROXY when a proxy is in the way." ;;
    *"Permission denied"*|*EACCES*) echo "No permission to write to the install folder: install for your user only, without sudo." ;;
    *"No space left on device"*) echo "The disk is full: free some space, then run the step again." ;;
    *) echo "The step did not finish. The full output is in the log." ;;
  esac
}
fail() { local src="$tmp"; [ -s "$tmp" ] || src="$elog"; echo "FAILED  step $1: $2" >&2; echo "        $(explain "$src")" >&2; echo "        Run by hand: $3  -- details: $log" >&2; exit 1; }
# run <n> <name> <command>: the output goes to the log only
run() { echo "run: $3"; : >"$tmp"; bash -o pipefail -c "$3" >"$tmp" 2>&1 || { cat "$tmp" >>"$log"; fail "$1" "$2" "$3"; }; cat "$tmp" >>"$log"; }
# fetch <url> [file]: a HEAD probe, or a download; a Schannel curl that fails with 35 retries once with --ssl-no-revoke
fetch() {
  local rc=0 out="${2:-}"
  if [ -n "$out" ]; then curl $CURL_OPTS -fsSL --max-time 60 "$1" -o "$out" 2>>"$elog" || rc=$?
  else curl $CURL_OPTS -sSI --max-time 8 -o /dev/null "$1" 2>>"$elog" || rc=$?; fi
  if [ "$rc" = 35 ] && [ -z "$CURL_OPTS" ] && curl -V 2>/dev/null | grep -qi schannel; then
    CURL_OPTS="--ssl-no-revoke"
    echo "note: curl could not check certificate revocation (Schannel); retrying once with --ssl-no-revoke, kept for this run"
    fetch "$1" "$out"; return
  fi
  return $rc
}
pyok() { local p; for p in python3 python; do have "$p" && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && return 0; done; return 1; }

# Git Bash or Cygwin: the Windows installer takes over with the same options (its curl is the Windows one).
handoff() {
  echo "Git Bash found: install.ps1 takes over with the same options."
  local ps1 args="" here; here=$(dirname "$0")
  if [ -f "$here/install.ps1" ]; then ps1="$here/install.ps1"
  else ps1="${TEMP:-/tmp}/autopilot-install.ps1"; fetch "$RAW/$ref/install.ps1" "$ps1" || fail 1 "pre-check" "curl -fsSL $RAW/$ref/install.ps1 -o install.ps1"; fi
  [ "$dry" = 1 ] && args="$args -DryRun"; [ "$skip" = 1 ] && args="$args -SkipLogin"; [ "$yes" = 1 ] && args="$args -Yes"
  [ -n "$runner" ] && args="$args -Runner $runner"
  have cygpath && ps1=$(cygpath -w "$ps1")
  # shellcheck disable=SC2086
  exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$ps1" $args
}

main() {
  dry=${AUTOPILOT_DRY_RUN:-0}; skip=${AUTOPILOT_SKIP_LOGIN:-0}; yes=0; runner=${AUTOPILOT_RUNNER:-}
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) dry=1 ;;
      --skip-login) skip=1 ;;
      --yes) yes=1 ;;
      --runner) shift; runner=${1:-} ;;
      --runner=*) runner=${1#--runner=} ;;
      *) echo "usage: install.sh [--dry-run] [--skip-login] [--runner NAME] [--yes]" >&2; exit 2 ;;
    esac
    shift
  done
  ref=${AUTOPILOT_REF:-$DEFAULT_REF}
  case "$ref" in
    ''|[!A-Za-z0-9]*|*..*|*[!A-Za-z0-9._/-]*)
      echo "AUTOPILOT_REF must start with a letter or a digit, and may use only A-Z a-z 0-9 . _ / - (no \"..\")" >&2; exit 2 ;;
  esac
  [ "${#ref}" -le 100 ] || { echo "AUTOPILOT_REF is longer than 100 characters" >&2; exit 2; }
  case "$runner" in ''|claude|copilot|codex|cursor|kiro) ;; *) echo "--runner must be claude, copilot, codex, cursor or kiro" >&2; exit 2 ;; esac
  PATH="$PATH:$HOME/.local/bin"   # uv installs here; this changes only this script
  log="${AUTOPILOT_HOME:-$HOME/.autopilot}/install.log"; tmp="${TMPDIR:-/tmp}/autopilot-install.$$"; elog=/dev/null
  [ "$dry" = 1 ] || { mkdir -p "$(dirname "$log")"; echo "=== install.sh $(date) ===" >>"$log"; elog=$log; }
  trap '[ -f "$tmp" ] && rm -f "$tmp"; true' EXIT

  # N8: the one consent. Starting this script is the consent; nothing below asks again, except the one runner question.
  echo "Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step."
  echo "This script installs: uv, Python 3.12 (when missing), Autopilot. Then \`ap setup\` names the AI runner you pay for and installs that one CLI. git is checked, not installed."
  echo "Rights it takes: none (N5.4). \`ap install --rights\` sets up the no-password path for system tools once."

  step 1 pre-check
  case "${OSTYPE:-}" in msys*|cygwin*) handoff ;; esac
  if have git; then echo "found: $(ver git)"; else echo "skipped: git is missing (not needed for the package install; a project that uses git needs it)"; fi
  if ! have curl; then echo "skipped: curl is not installed (needed to download uv)"; [ "$dry" = 1 ] || fail 1 "pre-check" "sudo apt-get install -y curl"
  elif [ "$dry" = 1 ] && [ "${AUTOPILOT_PROBE:-0}" = 0 ]; then echo "would check: astral.sh, pypi.org, github.com are reachable"
  else
    bad=""; for host in astral.sh pypi.org github.com; do fetch "https://$host/" || bad="$bad $host"; done
    if [ -n "$bad" ]; then echo "cannot reach:$bad" >>"$elog"; : >"$tmp"; fail 1 "pre-check" "curl -sSI https://${bad# }/   # then set HTTPS_PROXY when a proxy is in the way"; fi
    echo "found: astral.sh, pypi.org, github.com reachable"
  fi

  step 2 uv
  uvcmd="curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"
  if have uv; then echo "found: $(ver uv)"
  elif [ "$dry" = 1 ]; then echo "would install. Command: $uvcmd"
  else run 2 uv "$uvcmd"; have uv || fail 2 uv "$uvcmd"; fi

  step 3 Python
  # N5: Autopilot cannot run without Python 3.10 or newer. This is the one system install; uv installs it for this user.
  pycmd="uv python install 3.12"
  if pyok; then echo "found: $(have python3 && ver python3 || ver python)"
  elif [ "$dry" = 1 ]; then echo "would install (no Python 3.10 or newer found). Command: $pycmd"
  else run 3 Python "$pycmd"; fi

  step 4 Autopilot
  # N5.3: the package from PyPI first (no git needed); the release tag on GitHub when PyPI has no release yet.
  addr="git+https://github.com/manishjnv/AutoPilot@$ref"
  if have autopilot || { have uv && uv tool list 2>/dev/null | grep dev-autopilot >/dev/null; }; then
    echo "found: $(have autopilot && ver autopilot || echo dev-autopilot)"; echo "To update, run: ap upgrade"
  elif [ "$dry" = 1 ]; then echo "would install. Command: uv tool install dev-autopilot (or uv tool install \"$addr\")"
  else
    echo "run: uv tool install dev-autopilot"
    if ! bash -c "uv tool install dev-autopilot" >"$tmp" 2>&1; then cat "$tmp" >>"$log"; run 4 Autopilot "uv tool install \"$addr\""; fi
    have autopilot || fail 4 Autopilot "uv tool install \"$addr\""
  fi
  if [ "$dry" = 1 ]; then echo "would check: ap is on PATH"
  elif have ap; then echo "found: ap"
  else fail 4 Autopilot "uv tool install --reinstall \"$addr\" (then make sure $HOME/.local/bin is on PATH)"; fi
  # an Autopilot without `ap setup` (0.4.0 from PyPI or an older checkout) is updated from main before step 5
  newer="uv tool install --reinstall git+https://github.com/manishjnv/AutoPilot@main"
  if [ "$dry" != 1 ] && ! ap --help 2>&1 | grep -q setup; then echo "found: an Autopilot without ap setup: updating"; run 4 Autopilot "$newer"; fi

  step 5 "runner (ap setup)"
  args=""; [ "$skip" = 1 ] && args="$args --skip-login"; [ "$yes" = 1 ] && args="$args --yes"; [ -n "$runner" ] && args="$args --runner $runner"
  if [ "$dry" = 1 ]; then
    # shellcheck disable=SC2086
    if have ap; then ap setup --dry-run $args; else echo "would run: ap setup --dry-run$args"; fi
  else
    # shellcheck disable=SC2086
    ap setup $args || { rc=$?; [ "$rc" = 3 ] && echo "Autopilot is installed. Run the line above to name your runner." ; exit "$rc"; }
    echo "Installed: $(ver autopilot)"
  fi
  echo "To uninstall, run: uv tool uninstall dev-autopilot (and ap uninstall --rights)"
  echo "Done. Open a NEW terminal if \`ap\` is not found."
  echo 'Open a project folder and type `ap`.'
}

main "$@"
