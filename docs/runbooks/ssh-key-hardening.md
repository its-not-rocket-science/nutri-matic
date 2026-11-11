# Runbook: harden the production SSH key (PLAN — not yet implemented)

**Status: proposal for review (2026-11-11).** Nothing in this document has
been applied. No workflow, wrapper script, server file, secret, or
environment has been changed by it. Implementation waits for the decisions
listed at the end.

## What this fixes

From the Prompt C repo-health report (2026-11-11):

1. **The key is usable without approval.** `PROD_SSH_KEY` and `PROD_SSH_HOST`
   are repository-wide secrets, so any workflow on any branch can read them.
   The Production environment holds no secrets. `demo-purge.yml` and the
   deploy rehearsal job already use the key without approval. The server
   allowlist (`deploy/deploy-allowed-commands.sh`) limits what the key can
   do, but it still allows a full production `pg_dump`, `demo_purge --apply`
   and `migrate_profiles`.
4. **The server's identity is never checked.** Every SSH call uses
   `StrictHostKeyChecking=accept-new` on a fresh runner, so every
   connection is a "first" connection and any host key is accepted.
5. **The Production environment is loose.** It accepted deployments from any
   branch (now restricted to `main`, done 2026-11-11 via the API), and admins
   can bypass the approval.

## Where the key is used today

| Workflow / job | Environment today | Command sent | Approval today |
|---|---|---|---|
| `deploy.yml` → `rehearse-migration` | none | `cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic` | none (runs after CI on `main`) |
| `deploy.yml` → `deploy` (step 1) | `production` | `deploy <40-hex-sha>` | required reviewer |
| `deploy.yml` → `deploy` (step 2) | `production` | `cd nutri-matic && docker compose exec -T backend alembic current` | required reviewer |
| `migrate-profiles.yml` | `production` | `... python -m app.migrate_profiles` / `--dry-run` | required reviewer |
| `demo-purge.yml` | none | `... python -m app.demo_purge purge` / `--apply` | none (nightly schedule) |

**One GitHub constraint shapes the whole design: a job runs in at most one
environment**, and can only read that environment's secrets plus the
repository-wide ones. Any key the `deploy` and `migrate-profiles` jobs need
must therefore be either repo-wide or a Production-environment secret.

---

## A. Two keys instead of one

### Recommended split

| | **Routine key** | **Deploy key** |
|---|---|---|
| Purpose | Unattended jobs that must not wait for a click | Anything that changes or inspects production code/schema under a human approval |
| GitHub location | Secret `PROD_SSH_KEY_ROUTINE` in a **new environment `prod-routine`**: deployment branches = `main` only, **no required reviewers** | Secret `PROD_SSH_KEY_DEPLOY` in the existing **`Production`** environment (required reviewer, `main` only) |
| Wrapper mode | `routine` | `deploy` |
| Allowed commands | the exact `pg_dump` string; `demo_purge purge`; `demo_purge purge --apply` | `deploy <40-hex-sha>`; the exact `alembic current` string; `migrate_profiles --dry-run`; `migrate_profiles` |
| Used by | `deploy.yml` → `rehearse-migration`; `demo-purge.yml` | `deploy.yml` → `deploy`; `migrate-profiles.yml` |

This differs from the brief in two ways, both forced by the one-environment
constraint. Each is a decision for you (see the end):

- **The routine key is an environment secret (`prod-routine`), not
  repo-wide.** An environment with a `main`-only branch policy and *no*
  reviewers gives secrets only to jobs running on `main`, with no approval
  click. Scheduled runs and `workflow_run` runs execute on `main`, so the
  nightly purge and the rehearsal keep running unattended. A workflow pushed
  to any other branch, or a PR run, can no longer read the key. If the
  routine key were repo-wide as the brief says, any branch could still run
  `pg_dump` (a full export of production data) without approval, which is the
  main exposure in finding 1.
- **`alembic current` and `migrate_profiles` move to the deploy key.** Both
  run in jobs that are already inside `Production`. Those jobs could not read
  a `prod-routine` secret. `migrate_profiles` writes data, so putting it
  behind the approval gate matches how it is already used, and it adds no new
  approval clicks: `migrate-profiles.yml` already waits for approval today.

What stays unapproved: `pg_dump` and `demo_purge --apply`, reachable only
from workflows on `main` (which needs a PR with green CI to change, enforced
for admins). That is the price of keeping both jobs automatic. See decision 8.

**If you prefer the brief's literal layout** (routine key repo-wide, deploy
key allows only `deploy <sha>`): `alembic current` and `migrate_profiles`
stay in the routine mode, the deploy job uses both keys in different steps,
and `migrate-profiles.yml` uses the routine key. That works, but leaves the
`pg_dump` exposure from finding 1 in place.

### Generate the keys

On your own machine, not the server, and not a shared machine:

```bash
ssh-keygen -t ed25519 -N "" -C "nutri-matic-actions-routine-2026-11" -f ./nutri-matic-routine
ssh-keygen -t ed25519 -N "" -C "nutri-matic-actions-deploy-2026-11"  -f ./nutri-matic-deploy
```

No passphrase: the runner can't type one, and the forced command is what
limits the key. Upload the private halves straight into GitHub (step D4) and
then delete them locally. If a private key is lost later, generate a new one
rather than looking for a copy.

### authorized_keys lines (on the server, in `/root/.ssh/authorized_keys`)

```
restrict,command="/root/deploy-allowed-commands.sh routine" ssh-ed25519 AAAA...routine... nutri-matic-actions-routine-2026-11
restrict,command="/root/deploy-allowed-commands.sh deploy" ssh-ed25519 AAAA...deploy... nutri-matic-actions-deploy-2026-11
```

`restrict` (OpenSSH 7.2+) turns off port, X11 and agent forwarding, PTY
allocation and `~/.ssh/rc` in one word, and also covers any forwarding
option a future OpenSSH adds. It is a superset of the current
`no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty` list.
Check the server's version first with `ssh -V`. If it is older than 7.2,
keep the explicit list instead.

The existing line (`command="/root/deploy-allowed-commands.sh",...`, no
argument) stays in place until step D8.

### One wrapper script, mode chosen by argument

Replaces `deploy/deploy-allowed-commands.sh`. The mode comes from the
`command=` option, which the caller cannot change. Only
`SSH_ORIGINAL_COMMAND` comes from the caller, and it is still matched only
against exact strings or the anchored SHA regex. The `""` (no-argument)
branch keeps the old key working during rollout and is deleted in step D8.

```bash
#!/bin/bash
# Forced-command wrapper for the GitHub Actions SSH keys.
#
# Install as /root/deploy-allowed-commands.sh (mode 0700, owner root).
# authorized_keys passes the key's mode as $1:
#
#   restrict,command="/root/deploy-allowed-commands.sh routine" ssh-ed25519 ... routine key
#   restrict,command="/root/deploy-allowed-commands.sh deploy"  ssh-ed25519 ... deploy key
#
# routine: unattended jobs (deploy.yml rehearsal pg_dump, demo-purge.yml).
# deploy:  approval-gated jobs (deploy.yml deploy, migrate-profiles.yml).
#
# No eval, no free-text matching: a command is one of the exact strings for
# its mode, or (deploy mode only) `deploy <40-hex-sha>`. Anything else is
# rejected and logged.

set -uo pipefail

APP_DIR="${NUTRI_MATIC_DIR:-/root/nutri-matic}"
MODE="${1-}"
CMD="${SSH_ORIGINAL_COMMAND-}"

PG_DUMP="cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic"
ALEMBIC_CURRENT="cd nutri-matic && docker compose exec -T backend alembic current"
MIGRATE_DRY="cd nutri-matic && docker compose exec -T backend python -m app.migrate_profiles --dry-run"
MIGRATE_APPLY="cd nutri-matic && docker compose exec -T backend python -m app.migrate_profiles"
PURGE_DRY="cd nutri-matic && docker compose exec -T backend python -m app.demo_purge purge"
PURGE_APPLY="cd nutri-matic && docker compose exec -T backend python -m app.demo_purge purge --apply"

log() { logger -t deploy-wrapper -- "[${MODE:-legacy}] $*" 2>/dev/null || true; }

reject() {
  log "REJECTED: ${CMD:0:200}"
  echo "Rejected: command not in allowlist for this key" >&2
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

# Each *_cmd function either runs an allowed command (and the script exits
# with that command's own status) or rejects. A failing allowed command is
# never reported as "REJECTED".
routine_cmd() {
  case "$CMD" in
    "$PG_DUMP")     log "pg_dump";                  run_in_app docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic ;;
    "$PURGE_DRY")   log "demo_purge purge";         run_in_app docker compose exec -T backend python -m app.demo_purge purge ;;
    "$PURGE_APPLY") log "demo_purge purge --apply"; run_in_app docker compose exec -T backend python -m app.demo_purge purge --apply ;;
    *) reject ;;
  esac
}

deploy_cmd() {
  case "$CMD" in
    "$ALEMBIC_CURRENT") run_in_app docker compose exec -T backend alembic current ;;
    "$MIGRATE_DRY")     log "migrate_profiles --dry-run"; run_in_app docker compose exec -T backend python -m app.migrate_profiles --dry-run ;;
    "$MIGRATE_APPLY")   log "migrate_profiles";           run_in_app docker compose exec -T backend python -m app.migrate_profiles ;;
    deploy\ *)
      local sha="${CMD#deploy }"
      # Exactly 40 lowercase hex characters, anchored on the whole string.
      [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || reject
      log "deploy $sha"
      ( deploy "$sha" )
      ;;
    *) reject ;;
  esac
}

# TRANSITIONAL: the old single key (no argument) keeps exactly the current
# full allowlist until rollout step D8 removes its authorized_keys line.
# Delete this function and its case branch below in that same step.
legacy_cmd() {
  case "$CMD" in
    "$PG_DUMP"|"$PURGE_DRY"|"$PURGE_APPLY") routine_cmd ;;
    "$ALEMBIC_CURRENT"|"$MIGRATE_DRY"|"$MIGRATE_APPLY"|deploy\ *) deploy_cmd ;;
    *) reject ;;
  esac
}

case "$MODE" in
  routine) routine_cmd ;;
  deploy)  deploy_cmd ;;
  "")      legacy_cmd ;;
  *)       reject ;;
esac
```

Two behaviours to check during review:
- Quoting `"$CMD"`-style variables in a `case` pattern makes the match
  literal (no glob), the same as the current script.
- The script exits with the allowed command's own status, so a failing
  `pg_dump` still fails the workflow. It's logged as the command, not as a
  rejection.

### Rollback (keys)

At any point before step D8, the old key, the old secret and the old
authorized_keys line are untouched, so rolling back means reverting the
workflow PR. The new wrapper's `""` branch accepts exactly what the old
script accepted. To undo the server side as well: put back the previous
`/root/deploy-allowed-commands.sh` (keep a copy, see D1) and delete the two
new authorized_keys lines.

---

## B. Host-key verification

### Record the fingerprint safely

The point is to learn the server's real host key over a channel an attacker
on the network path can't tamper with.

1. In the **Hetzner Cloud Console** → the server → **Console** (the browser
   VNC console, which goes through Hetzner's control plane, not over SSH),
   log in and run:
   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```
   Note the `SHA256:...` fingerprint. It's short enough to read off the
   screen. The console has no clipboard, which is why you read the
   fingerprint here and fetch the full key in step 2.
2. On your own machine, fetch the full public key over the network:
   ```bash
   ssh-keyscan -t ed25519 <host> 2>/dev/null > prod_known_hosts
   ssh-keygen -lf prod_known_hosts
   ```
   `<host>` must be exactly the host part of `PROD_SSH_HOST`, IP or name,
   because `known_hosts` entries match on that string.
3. **The two fingerprints must match character for character.** If they
   don't, stop: either you scanned the wrong host or something is
   intercepting traffic.
4. Store the one-line contents of `prod_known_hosts` as a **repository
   variable** (not a secret) named `PROD_SSH_KNOWN_HOSTS`:
   ```bash
   gh variable set PROD_SSH_KNOWN_HOSTS < prod_known_hosts
   ```
   A host public key is public information. Keeping it as a variable means
   it shows up readably in the settings and in run logs, which helps with
   debugging. See decision 4.

### Use it in each workflow

Every SSH step writes the variable to `known_hosts` and uses
`StrictHostKeyChecking=yes`. An empty variable fails closed with a clear
error instead of falling back to trust-on-first-use:

```bash
if [ -z "$SSH_KNOWN_HOSTS" ]; then
  echo "::error::PROD_SSH_KNOWN_HOSTS repository variable is not set — refusing to connect without host-key verification."
  exit 1
fi
printf '%s\n' "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
chmod 644 ~/.ssh/known_hosts
ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes "$SSH_HOST" "..."
```

### If the server is rebuilt or its host keys change

A rebuild from a fresh image generates new host keys. Restoring a Hetzner
snapshot or backup keeps the old ones. After a change, every SSH step fails
with `Host key verification failed.` before authenticating, so nothing runs
on the server. That's the intended fail-closed behaviour. To recover, repeat
steps 1–4 above and re-run the failed workflow. **Never** "fix" it by going
back to `accept-new`, even temporarily.

If you ever change `PROD_SSH_HOST` (new IP or a DNS name), update the
variable in the same sitting, since the entry is keyed by that host string.

---

## C. Production environment settings (GitHub UI)

- **Deployment branches: `main` only.** Already applied on 2026-11-11 via the
  REST API (custom branch policy `main`). Nothing left to do.
- **Required reviewers:** unchanged (you). "Prevent self-review" must stay
  **off**, because you're the only reviewer.
- **Admin bypass ("Allow administrators to bypass configured protection
  rules"): recommend turning it OFF.**
  - For a solo repo it adds little security on its own. Anyone holding your
    admin token can also approve the deployment as the required reviewer,
    since that's the same account.
  - It does remove the "deploy without approval" button, so an approval is
    always an explicit, logged click rather than a bypass.
  - It costs nothing: you remain a reviewer, so you can always approve, and
    turning it off can't lock you out.
- **New environment `prod-routine`** (only if decision 1 is accepted):
  deployment branches `main` only; **no** required reviewers; no wait timer;
  secret `PROD_SSH_KEY_ROUTINE`.

Side effect to expect: every job that names an environment creates a GitHub
"deployment" record. The repo's Deployments sidebar will start listing
`prod-routine` runs (nightly purge, every rehearsal). That's cosmetic.

---

## D. Workflow edits and ordered rollout

### Workflow edits (applied in step D5, as one PR)

Shown as diffs against `main` as of 2026-11-11 (before PR #72's action pins,
which don't touch these lines).

**`.github/workflows/deploy.yml` — `rehearse-migration` job**

```diff
   rehearse-migration:
     if: ${{ github.event.workflow_run.conclusion == 'success' || github.event_name == 'workflow_dispatch' }}
     runs-on: ubuntu-latest
+    environment:
+      name: prod-routine
     outputs:
@@
       - name: Fetch a fresh production dump over SSH
         env:
-          SSH_KEY: ${{ secrets.PROD_SSH_KEY }}
+          SSH_KEY: ${{ secrets.PROD_SSH_KEY_ROUTINE }}
           SSH_HOST: ${{ secrets.PROD_SSH_HOST }}
+          SSH_KNOWN_HOSTS: ${{ vars.PROD_SSH_KNOWN_HOSTS }}
         run: |
           mkdir -p ~/.ssh
           echo "$SSH_KEY" > ~/.ssh/deploy_key
           chmod 600 ~/.ssh/deploy_key
-          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=accept-new "$SSH_HOST" \
+          if [ -z "$SSH_KNOWN_HOSTS" ]; then
+            echo "::error::PROD_SSH_KNOWN_HOSTS repository variable is not set — refusing to connect without host-key verification."
+            exit 1
+          fi
+          printf '%s\n' "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
+          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes "$SSH_HOST" \
             "cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic" \
             > rehearsal.dump
```

Also update the stale comment above that step (lines 56–62), which describes
`PROD_SSH_KEY` as a repo-scoped secret.

**`.github/workflows/deploy.yml` — `deploy` job** (already `environment: production`)

```diff
       - name: Deploy the exact rehearsed commit via SSH
         env:
-          SSH_KEY: ${{ secrets.PROD_SSH_KEY }}
+          SSH_KEY: ${{ secrets.PROD_SSH_KEY_DEPLOY }}
           SSH_HOST: ${{ secrets.PROD_SSH_HOST }}
+          SSH_KNOWN_HOSTS: ${{ vars.PROD_SSH_KNOWN_HOSTS }}
         run: |
           mkdir -p ~/.ssh
           echo "$SSH_KEY" > ~/.ssh/deploy_key
           chmod 600 ~/.ssh/deploy_key
+          if [ -z "$SSH_KNOWN_HOSTS" ]; then
+            echo "::error::PROD_SSH_KNOWN_HOSTS repository variable is not set — refusing to connect without host-key verification."
+            exit 1
+          fi
+          printf '%s\n' "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
@@
-          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=accept-new "$SSH_HOST" "deploy $DEPLOY_SHA"
+          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes "$SSH_HOST" "deploy $DEPLOY_SHA"

       - name: Verify migration reached head on the live server
         env:
-          SSH_KEY: ${{ secrets.PROD_SSH_KEY }}
           SSH_HOST: ${{ secrets.PROD_SSH_HOST }}
         run: |
-          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=accept-new "$SSH_HOST" \
+          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes "$SSH_HOST" \
             "cd nutri-matic && docker compose exec -T backend alembic current"
```

(The second step reuses `~/.ssh/deploy_key` and `~/.ssh/known_hosts` written
by the first step in the same job, as it already does for the key today.
The unused `SSH_KEY` env line is dropped.)

**`.github/workflows/migrate-profiles.yml`** (already `environment: production`)

```diff
         env:
-          SSH_KEY: ${{ secrets.PROD_SSH_KEY }}
+          SSH_KEY: ${{ secrets.PROD_SSH_KEY_DEPLOY }}
           SSH_HOST: ${{ secrets.PROD_SSH_HOST }}
+          SSH_KNOWN_HOSTS: ${{ vars.PROD_SSH_KNOWN_HOSTS }}
         run: |
           mkdir -p ~/.ssh
           echo "$SSH_KEY" > ~/.ssh/deploy_key
           chmod 600 ~/.ssh/deploy_key
+          if [ -z "$SSH_KNOWN_HOSTS" ]; then
+            echo "::error::PROD_SSH_KNOWN_HOSTS repository variable is not set — refusing to connect without host-key verification."
+            exit 1
+          fi
+          printf '%s\n' "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
@@
-          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=accept-new "$SSH_HOST" \
+          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes "$SSH_HOST" \
             "cd nutri-matic && docker compose exec -T backend $CMD"
```

**`.github/workflows/demo-purge.yml`**

```diff
   purge:
     name: Demo purge
     runs-on: ubuntu-latest
+    environment:
+      name: prod-routine
     steps:
       - name: Run demo purge on the server
         env:
-          SSH_KEY: ${{ secrets.PROD_SSH_KEY }}
+          SSH_KEY: ${{ secrets.PROD_SSH_KEY_ROUTINE }}
           SSH_HOST: ${{ secrets.PROD_SSH_HOST }}
+          SSH_KNOWN_HOSTS: ${{ vars.PROD_SSH_KNOWN_HOSTS }}
         run: |
-          if [ -z "$SSH_KEY" ] || [ -z "$SSH_HOST" ]; then
-            echo "::error::PROD_SSH_KEY/PROD_SSH_HOST not configured — see docs/demo-lifecycle.md. Refusing to run (fail closed)."
+          if [ -z "$SSH_KEY" ] || [ -z "$SSH_HOST" ] || [ -z "$SSH_KNOWN_HOSTS" ]; then
+            echo "::error::PROD_SSH_KEY_ROUTINE/PROD_SSH_HOST/PROD_SSH_KNOWN_HOSTS not configured — see docs/runbooks/ssh-key-hardening.md. Refusing to run (fail closed)."
             exit 1
           fi
           mkdir -p ~/.ssh
           echo "$SSH_KEY" > ~/.ssh/deploy_key
           chmod 600 ~/.ssh/deploy_key
+          printf '%s\n' "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
@@
-          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=accept-new "$SSH_HOST" \
+          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes "$SSH_HOST" \
             "cd nutri-matic && docker compose exec -T backend $CMD"
```

Also update the header comment (lines 14–17) and `docs/demo-lifecycle.md`'s
"No `environment: production` approval gate" paragraph, plus
`DEPLOYMENT.md` → "Deploy key and server-side allowlist", to describe the
two keys.

### Ordered rollout

Deploys keep working at every step. Do the steps in order and finish each
check before moving on.

| Step | Who / where | Action | Check before continuing | Rollback |
|---|---|---|---|---|
| D1 | You, on the server | `cp /root/deploy-allowed-commands.sh /root/deploy-allowed-commands.sh.bak-2026-11` then install the new wrapper (section A), mode `0700`, owner root. Keep the old authorized_keys line unchanged. | Run the section E "legacy mode" checks on the server. Then dispatch `demo-purge.yml` from `main` with `apply` unchecked (uses the old key and the `""` branch) and confirm it's green. | `cp` the `.bak` back. |
| D2 | You, on the server | Append the two new authorized_keys lines (section A). | Section E mode checks on the server (no keys needed). | Delete the two lines. |
| D3 | You, GitHub | Record the host key: section B steps 1–4 → variable `PROD_SSH_KNOWN_HOSTS`. | `gh variable list` shows it. Section E host-key check. | `gh variable delete PROD_SSH_KNOWN_HOSTS` (nothing uses it yet). |
| D4 | You, GitHub | Create environment `prod-routine` (branches: `main`; no reviewers). `gh secret set PROD_SSH_KEY_ROUTINE --env prod-routine < nutri-matic-routine`; `gh secret set PROD_SSH_KEY_DEPLOY --env Production < nutri-matic-deploy`. Then delete both local private key files. Turn off admin bypass on Production (decision 5). Leave repo secret `PROD_SSH_KEY` in place. | `gh secret list --env prod-routine` / `--env Production` list the new names. | Delete the two env secrets. Nothing uses them yet. |
| D5 | Me (after approval) → you merge | One PR with the workflow edits above plus the doc updates. The PR's own CI never touches SSH, so it can't break anything before merge. | CI green on the PR. | Revert the PR. The old secret, key and wrapper branch are all still live. |
| D6 | You | Merge D5. CI on `main` → `deploy.yml`: the rehearsal job uses the **routine key** (pg_dump). The deploy job waits for approval → approve → **deploy key** (`deploy <sha>` + `alembic current`). Then dispatch `demo-purge.yml` (dry-run, routine key) and `migrate-profiles.yml` (dry-run, deploy key, approve). | All four green. On the server, `journalctl -t deploy-wrapper --since today` shows entries tagged `[routine]` and `[deploy]`, and **none** tagged `[legacy]`. | Revert the D5 merge. The old key still works through `""`. |
| D7 | You | Run the section E negative tests. | All expected rejections happen. | — |
| D8 | You, server + GitHub | Revoke the old key: delete the argument-less line from `/root/.ssh/authorized_keys`; remove the `""` branch from the wrapper; `gh secret delete PROD_SSH_KEY`. Then grep the repo to confirm nothing references `secrets.PROD_SSH_KEY }}` any more. | Next nightly purge and next deploy are green. Section E "legacy gone" check. | Re-add the old line and `""` branch from the D1 backup. The old private key is gone from GitHub at that point, so a true rollback past D8 means generating another key: treat D8 as the point of no return and only do it after D6/D7 are clean. |

---

## E. Test plan

### On the server, no keys needed (D1, D2, D7)

`sshd` runs the wrapper with `SSH_ORIGINAL_COMMAND` set, so you can test
mode handling directly as root. Every "expect reject" case below exits 1 and
writes a `REJECTED` line to `journalctl -t deploy-wrapper`. Only use
read-only or dry-run commands for the "expect allowed" cases.

```bash
W=/root/deploy-allowed-commands.sh
t() { SSH_ORIGINAL_COMMAND="$2" "$W" $1 >/dev/null 2>&1; echo "mode=${1:-<none>} exit=$?  $2"; }

# routine: allowed (read-only / dry-run)
t routine "cd nutri-matic && docker compose exec -T backend python -m app.demo_purge purge"   # expect 0
# routine: must reject
t routine "cd nutri-matic && docker compose exec -T backend alembic current"                   # expect 1
t routine "cd nutri-matic && docker compose exec -T backend python -m app.migrate_profiles --dry-run"  # expect 1
t routine "deploy 0000000000000000000000000000000000000000"                                    # expect 1
t routine "ls /root"                                                                          # expect 1
t routine "cd nutri-matic && docker compose exec -T backend python -m app.demo_purge purge; id"  # expect 1

# deploy: allowed (read-only / dry-run)
t deploy  "cd nutri-matic && docker compose exec -T backend alembic current"                   # expect 0
t deploy  "cd nutri-matic && docker compose exec -T backend python -m app.migrate_profiles --dry-run"  # expect 0
# deploy: must reject
t deploy  "cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic"  # expect 1
t deploy  "cd nutri-matic && docker compose exec -T backend python -m app.demo_purge purge --apply"  # expect 1
t deploy  "deploy abc"                                                                        # expect 1
t deploy  "deploy $(printf 'a%.0s' {1..40}) "                                                 # expect 1 (trailing space)
t deploy  "deploy $(printf 'a%.0s' {1..40});id"                                               # expect 1

# unknown mode
t bogus   "cd nutri-matic && docker compose exec -T backend alembic current"                   # expect 1

# legacy (no argument) — D1/D2: expect 0 for the old allowlist; after D8: expect 1
t ""      "cd nutri-matic && docker compose exec -T backend alembic current"
```

Don't test `pg_dump`, `demo_purge --apply`, `migrate_profiles` (apply) or a
real `deploy <sha>` in "allowed" mode by hand. The D6 workflow runs cover
those end to end.

### End to end over SSH (optional, D2–D4)

Before deleting the local private keys in D4, you can prove each key's
forced command from your own machine:

```bash
ssh -i ./nutri-matic-routine -o StrictHostKeyChecking=yes -o UserKnownHostsFile=./prod_known_hosts <user@host> "deploy 0000000000000000000000000000000000000000"
# expect: "Rejected: command not in allowlist for this key", exit 1
ssh -i ./nutri-matic-deploy  -o StrictHostKeyChecking=yes -o UserKnownHostsFile=./prod_known_hosts <user@host> "cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic"
# expect: rejected, exit 1, and no dump written
ssh -i ./nutri-matic-deploy  -o StrictHostKeyChecking=yes -o UserKnownHostsFile=./prod_known_hosts <user@host> "cd nutri-matic && docker compose exec -T backend alembic current"
# expect: alembic output (allowed, read-only)
```

### Host-key verification (D3)

No key needed, because host verification happens before authentication:

```bash
# wrong/empty known_hosts → must fail before auth
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/dev/null <user@host> true
# expect: "Host key verification failed."

# correct known_hosts → passes host check, then fails auth (no key offered)
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=./prod_known_hosts -o IdentitiesOnly=yes -o IdentityFile=/dev/null <user@host> true
# expect: "Permission denied (publickey...)." — getting this far proves the host key matched
```

### GitHub-side gates (D6–D7)

- **Branch policy on `prod-routine`:** push a throwaway branch and dispatch
  `demo-purge.yml` from it (`gh workflow run demo-purge.yml --ref <branch>`).
  Expect the job to be refused before it starts, with an error saying the
  branch isn't allowed to deploy to `prod-routine`, and no SSH attempted. Delete the branch.
- **Branch policy on `Production`:** same with `migrate-profiles.yml` from a
  throwaway branch. Expect the same refusal for `Production`.
- **Old secret gone (after D8):** `gh secret list` no longer shows
  `PROD_SSH_KEY`, and `grep -rn "secrets.PROD_SSH_KEY }}" .github/` returns
  nothing.
- **Legacy gone (after D8):** on the server, the last `t ""` line above now
  exits 1.

---

## Decisions needed from you

1. **Routine key location:** a `prod-routine` environment with a `main`-only
   branch policy and no reviewers (**recommended**), or repo-wide as in the
   brief. Repo-wide leaves `pg_dump` available to any branch.
2. **`migrate_profiles` (+ `--dry-run`) under the deploy key**
   (**recommended**; the job is already approval-gated), or under the
   routine key (only possible if decision 1 is "repo-wide").
3. **`alembic current` under the deploy key** (**recommended**; it's read-only
   and the deploy job can only see Production secrets under decision 1), or
   keep the deploy key to `deploy <sha>` only and give `alembic current` to
   the routine key (again only possible if the routine key is repo-wide).
4. **Host key storage:** repository *variable* `PROD_SSH_KNOWN_HOSTS`
   (**recommended**; it's public data) or a secret. Also, optionally, turn
   `PROD_SSH_HOST` into a variable. It isn't really secret, and it's already
   shown in a comment in `deploy.yml`.
5. **Admin bypass on Production:** turn it off (**recommended**; it can't
   lock you out) or keep it.
6. **`restrict` in authorized_keys** (**recommended**, needs OpenSSH ≥ 7.2
   on the server), or keep the explicit `no-*` list.
7. **Key details:** ed25519, no passphrase, comment naming as above. Do you
   want a rotation reminder (for example yearly)?
8. **Accept that `pg_dump` and `demo_purge --apply` stay unapproved** (from
   `main` only) to keep the rehearsal and nightly purge automatic. The
   alternative is approving every rehearsal, or rehearsing against a backup
   copy instead of a live dump.
9. **Out of scope for now, but worth noting:** the wrapper and both keys
   still run as `root`. A dedicated non-root deploy user in the `docker`
   group would further limit a wrapper bug. Do you want a separate plan for
   that?
10. **Who performs the server steps (D1, D2, D8):** you, via the Hetzner
    console or your own admin SSH key. This plan assumes I never SSH to the
    server.
