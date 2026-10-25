#!/bin/bash
# Forced-command wrapper for the GitHub Actions deploy key.
#
# Install on the server as /root/deploy-allowed-commands.sh (mode 0700,
# owned by root) and reference it from the deploy key's line in
# /root/.ssh/authorized_keys:
#
#   command="/root/deploy-allowed-commands.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... github-actions-deploy
#
# Every request is matched against a fixed list. There is NO eval and no
# pattern matching on free text: a command is either one of the exact
# strings below or `deploy <40-hex-sha>`, which is validated and then runs a
# fixed sequence that this script, not the caller, defines.
#
# Anything else is rejected and logged. Callers: .github/workflows/
# deploy.yml, demo-purge.yml, migrate-profiles.yml.

set -uo pipefail

APP_DIR="${NUTRI_MATIC_DIR:-/root/nutri-matic}"
CMD="${SSH_ORIGINAL_COMMAND-}"

log() { logger -t deploy-wrapper -- "$*" 2>/dev/null || true; }

reject() {
  log "REJECTED: ${CMD:0:200}"
  echo "Rejected: command not in allowlist" >&2
  exit 1
}

run_in_app() {
  cd "$APP_DIR" || exit 1
  "$@"
}

deploy() {
  local sha="$1"
  set -e
  cd "$APP_DIR"
  git fetch origin
  # Only commits that are already on origin/main may be deployed. This
  # blocks deploying an unmerged branch even if the workflow is dispatched
  # from one.
  if ! git merge-base --is-ancestor "$sha" origin/main; then
    echo "Refusing to deploy $sha: not an ancestor of origin/main" >&2
    exit 1
  fi
  git checkout --quiet "$sha"
  echo "Deploying commit: $(git rev-parse HEAD)"
  export RELEASE_VERSION="$sha"
  docker compose build backend
  docker compose up -d backend
}

case "$CMD" in
  "cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic")
    log "pg_dump"
    run_in_app docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic
    ;;
  "cd nutri-matic && docker compose exec -T backend alembic current")
    run_in_app docker compose exec -T backend alembic current
    ;;
  "cd nutri-matic && docker compose exec -T backend python -m app.migrate_profiles --dry-run")
    log "migrate_profiles --dry-run"
    run_in_app docker compose exec -T backend python -m app.migrate_profiles --dry-run
    ;;
  "cd nutri-matic && docker compose exec -T backend python -m app.migrate_profiles")
    log "migrate_profiles"
    run_in_app docker compose exec -T backend python -m app.migrate_profiles
    ;;
  "cd nutri-matic && docker compose exec -T backend python -m app.demo_purge purge")
    log "demo_purge purge"
    run_in_app docker compose exec -T backend python -m app.demo_purge purge
    ;;
  "cd nutri-matic && docker compose exec -T backend python -m app.demo_purge purge --apply")
    log "demo_purge purge --apply"
    run_in_app docker compose exec -T backend python -m app.demo_purge purge --apply
    ;;
  deploy\ *)
    sha="${CMD#deploy }"
    # Exactly 40 lowercase hex characters, nothing else. Anchored regex on
    # the whole remaining string, so no whitespace, newline, or shell
    # metacharacter can pass.
    if [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
      log "deploy $sha"
      ( deploy "$sha" )
    else
      reject
    fi
    ;;
  *)
    reject
    ;;
esac
