#!/usr/bin/env bash
# Idempotent deploy: ssh -> checkout DEPLOY_REF -> build -> restart -> health check.
# Usage: deploy.sh [--dry-run] [--rollback]
# Env (required): DEPLOY_SSH_HOST DEPLOY_SSH_KEY_PATH DEPLOY_REF DEPLOY_HEALTH_URL
# Env (project-supplied): DEPLOY_DIR DEPLOY_BUILD_CMD DEPLOY_RESTART_CMD
# Env (optional): DEPLOY_STATE_FILE (default .deploy_prev_ref), DEPLOY_SSH_CMD (default ssh)
# Exit: 0 ok | 2 bad input | 3 ssh/deploy step failed | 4 health check failed (prev ref logged)
set -euo pipefail

DRY=0; ROLLBACK=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --rollback) ROLLBACK=1 ;;
    *) echo "ERROR: unknown arg $a" >&2; exit 2 ;;
  esac
done

: "${DEPLOY_SSH_HOST:?DEPLOY_SSH_HOST required}" "${DEPLOY_SSH_KEY_PATH:?DEPLOY_SSH_KEY_PATH required}"
: "${DEPLOY_HEALTH_URL:?DEPLOY_HEALTH_URL required}"
DEPLOY_DIR=${DEPLOY_DIR:-.}
DEPLOY_BUILD_CMD=${DEPLOY_BUILD_CMD:-true}
DEPLOY_RESTART_CMD=${DEPLOY_RESTART_CMD:-true}
STATE=${DEPLOY_STATE_FILE:-.deploy_prev_ref}
SSH=${DEPLOY_SSH_CMD:-ssh}
err() { echo "ERROR: $*" >&2; }

if [ "$ROLLBACK" = 1 ]; then
  [ -f "$STATE" ] || { err "no previous ref in $STATE"; exit 2; }
  REF=$(cat "$STATE")
else
  REF=${DEPLOY_REF:?DEPLOY_REF required}
fi
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || { err "invalid ref '$REF'"; exit 2; }

# Runs on the remote host. Prints the previous HEAD on line 1; skips build/restart when already at REF.
REMOTE=$(cat <<R
set -e
cd '$DEPLOY_DIR'
prev=\$(git rev-parse HEAD)
echo "PREV_REF=\$prev"
git fetch --quiet origin
target=\$(git rev-parse --verify '$REF^{commit}' 2>/dev/null || git rev-parse --verify 'origin/$REF^{commit}')
if [ "\$target" = "\$prev" ]; then echo "UNCHANGED=1"; exit 0; fi
git checkout --quiet --detach "\$target"
$DEPLOY_BUILD_CMD
$DEPLOY_RESTART_CMD
echo "NEW_REF=\$target"
R
)

if [ "$DRY" = 1 ]; then
  echo "[dry-run] would ssh $DEPLOY_SSH_HOST (key $DEPLOY_SSH_KEY_PATH) and run:"
  echo "$REMOTE" | sed 's/^/[dry-run]   /'
  echo "[dry-run] would GET $DEPLOY_HEALTH_URL; previous ref saved to $STATE"
  exit 0
fi

OUT=$($SSH -i "$DEPLOY_SSH_KEY_PATH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$HOME/.ssh/known_hosts" -o PasswordAuthentication=no "$DEPLOY_SSH_HOST" "bash -s" <<<"$REMOTE") \
  || { err "remote deploy step failed"; exit 3; }
echo "$OUT"
PREV=$(sed -n 's/^PREV_REF=//p' <<<"$OUT")
# Save the previous ref only on a real change, so a re-run keeps the true rollback target.
if ! grep -q '^UNCHANGED=1' <<<"$OUT" && [ -n "$PREV" ]; then echo "$PREV" > "$STATE"; fi

for i in 1 2 3 4 5; do
  if curl -fsS -o /dev/null --max-time 10 "$DEPLOY_HEALTH_URL"; then echo "HEALTH=ok"; exit 0; fi
  sleep 2
done
err "health check failed for $DEPLOY_HEALTH_URL; previous ref: ${PREV:-unknown} (run: deploy.sh --rollback)"
exit 4
