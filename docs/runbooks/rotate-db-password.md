# Runbook: rotate the production Postgres password

**Status: runbook only (written 2026-11-15).** Nothing here has been run.
No server, secret, workflow or compose file was changed when it was written.
Every server step is for an operator with shell access to the production
host. Run them in order, in one sitting.

## Why

Postgres, Redis and the backend are bound to `127.0.0.1` on the host, so
the database isn't reachable from outside. But the `nutrimatic` role still
uses the development password `nutrimatic`, which is public in this repo.
Anything that runs on the host or in its Docker network (a compromised
container, a mistaken port publish, a future service) can log in with it.

## Where the password lives today

| Place | What it holds | Production? |
|---|---|---|
| `docker-compose.yml` → `postgres.environment.POSTGRES_PASSWORD` | `nutrimatic` (literal) | Yes, but **only read when the data volume is first initialised**. Changing it later does nothing to an existing role. |
| `docker-compose.yml` → `backend.environment.DATABASE_URL` | `postgresql://nutrimatic:nutrimatic@postgres:5432/nutrimatic` (literal) | **Yes.** This is what the live backend connects with. A server `.env` can't override it while it's a literal. |
| `backend/app/database.py:10` | default `DATABASE_URL` with the dev password, used only when the env var is unset | No (compose always sets it), but see "Flags" |
| `.github/workflows/ci.yml` lines 33–39, 57, 83 | CI's own throwaway `postgres` service: `POSTGRES_PASSWORD: nutrimatic` and matching `DATABASE_URL`s | No. It's a disposable container per CI run |
| `.github/workflows/deploy.yml` → `rehearse-migration` | throwaway rehearsal DB, password `rehearsal`, user `postgres` | No |
| Host-side tools (`app.ingest_fdc` etc. via `127.0.0.1:5433`) | whatever `DATABASE_URL` the operator exports | Yes, when run |
| GitHub secrets | **none.** No workflow holds a database password. `demo-purge.yml` used to have a `PRODUCTION_DATABASE_URL` secret; it was removed in favour of `docker compose exec` over SSH | — |
| Server `~/nutri-matic/.env` (untracked, `.gitignore` line 4) | `JWT_SECRET`, `CORS_ORIGINS`, `TRUSTED_PROXY_HOP_COUNT`, `OPS_DIAGNOSTIC_TOKEN`, … | Yes. This is where the new password goes. Since #109, compose refuses to run at all (including `docker compose exec`) if `JWT_SECRET` is missing from it |

The workflows never send a password. Everything reaches the database with
`docker compose exec` on the server (see `deploy/deploy-allowed-commands.sh`).

## Step 0 — repo change (one PR, merged and deployed before the rotation)

Make the compose file read the password from the server's `.env`, keeping
the dev value as the default so local `docker compose up` and CI are
unchanged:

```yaml
  postgres:
    environment:
      POSTGRES_USER: nutrimatic
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-nutrimatic}
      POSTGRES_DB: nutrimatic
  backend:
    environment:
      DATABASE_URL: postgresql://nutrimatic:${POSTGRES_PASSWORD:-nutrimatic}@postgres:5432/nutrimatic
```

Use a password with no URL-special characters (`openssl rand -hex 32`
gives 64 hex characters), so it can sit in the URL without escaping.

Merging this changes nothing in production while `.env` has no
`POSTGRES_PASSWORD`: the default resolves to the same URL as today. Let the
normal deploy run (it touches `docker-compose.yml`, so it isn't skipped)
and confirm `/api/ready` is green before going further.

## Step 1 — before you start (on the server)

```sh
cd ~/nutri-matic
git status --short                  # .env must not be listed (it is ignored)
git check-ignore -v .env            # must print the .gitignore rule
ls -l .env                          # make it 600 if it isn't: chmod 600 .env
# Fresh backup, kept off the repo directory:
mkdir -p ~/backups && chmod 700 ~/backups
docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic > ~/backups/pre-rotation-$(date +%F).dump
# How does pg_dump authenticate inside the container? (see "pg_dump" below)
docker compose exec -T postgres sh -c 'grep -Ev "^\s*(#|$)" "$PGDATA/pg_hba.conf"'
crontab -l; ls /etc/cron.d        # anything else that connects with the old password?
```

## Step 2 — rotate (minimum downtime: one backend restart)

Existing connections stay open after a password change. Postgres only
checks the password on new connections. So the gap is between changing the
role (2b) and the backend restarting with the new URL (2c). Run 2b and 2c
back to back.

```sh
cd ~/nutri-matic
# 2a. Generate and store the new password (never echo it to the terminal log).
NEWPW=$(openssl rand -hex 32)
printf 'POSTGRES_PASSWORD=%s\n' "$NEWPW" >> .env
unset NEWPW

# 2b. Change the role's password. \password prompts and sends only the hash,
#     so the password never appears in `ps`, psql history or server logs.
#     Paste the value from .env when asked.
docker compose exec postgres psql -U nutrimatic -d nutrimatic -c '\password nutrimatic'

# 2c. Recreate the backend so it picks up the new DATABASE_URL.
#     --no-deps is required. POSTGRES_PASSWORD also changes the postgres
#     service's environment, so a plain `up -d backend` recreates postgres
#     too (it is a depends_on service whose config changed), dropping every
#     connection and restarting the database. Recreating postgres gains
#     nothing: POSTGRES_PASSWORD is only read when the volume is initialised.
docker compose up -d --no-deps backend
```

Expected downtime is the same as a normal deploy's `up -d backend`, a few
seconds. Requests in that window may fail to get a new DB connection.

## Step 3 — verify

```sh
curl -sf https://api.nutri-matic.uk/api/health && echo health OK
curl -sf https://api.nutri-matic.uk/api/ready  && echo ready OK      # opens a DB connection
docker compose exec -T backend alembic current                       # must show head, no auth error
# Confirm the backend is NOT using the dev password (prints True/False only):
docker compose exec -T backend python -c "import os; print(':nutrimatic@' not in os.environ['DATABASE_URL'])"
# Confirm the old password is refused over the Docker network, the way the
# backend connects. Run it from the backend container: inside the postgres
# container, pg_hba.conf trusts 127.0.0.1, so any password "works" there.
# The backend image has no psql, so this uses psycopg2. Only an explicit
# "password authentication failed" counts as success; anything else (DNS,
# timeout, postgres down, backend not running) is not proof.
docker compose exec -T backend python - <<'EOF'
import sys
import psycopg2
try:
    psycopg2.connect(host="postgres", port=5432, user="nutrimatic", password="nutrimatic",
                     dbname="nutrimatic", connect_timeout=5).close()
except psycopg2.OperationalError as e:
    if "password authentication failed" in str(e):
        print("old password refused: good")
        sys.exit(0)
    print("INCONCLUSIVE, not an auth refusal:", str(e).strip())
    sys.exit(2)
print("OLD PASSWORD STILL WORKS: investigate")
sys.exit(1)
EOF
docker compose logs --since 10m backend | grep -i -E 'password authentication failed|OperationalError' || echo "no auth errors"
```

Then trigger the deploy workflow by hand (**Actions → Rehearse and Deploy
Backend → Run workflow**) and confirm the rehearsal's `pg_dump` step still
succeeds. That proves the rehearsal path end to end. Approve or reject the
production step as you see fit; the rehearsal is what matters here.

## Step 4 — planned postgres recreate (quiet window, after Step 3 passes)

Step 2c used `--no-deps`, so the running postgres container still has the
old `POSTGRES_PASSWORD` in its environment and no longer matches the
compose config. The normal deploy runs a plain `docker compose up -d
backend` (`deploy/deploy-allowed-commands.sh`), which would notice that
and recreate postgres during the next deploy, unplanned. Do it yourself
instead, at a quiet time:

```sh
cd ~/nutri-matic
docker compose up -d postgres         # recreates postgres only; data stays in the volume
docker compose ps postgres            # wait for "(healthy)"
curl -sf https://api.nutri-matic.uk/api/ready && echo ready OK
```

Only postgres is recreated; the backend container keeps running. This is
still a database restart: open connections drop and requests fail for a
few seconds. Once postgres is healthy the backend reconnects on its own:
its engine uses `pool_pre_ping` (#118), so connections the restart killed
are replaced before a request gets them. It doesn't change
the role's password (`POSTGRES_PASSWORD` is only read when the volume is
first initialised). Re-run Step 3's checks afterwards.

If you rolled back before this step, skip it: removing the `.env` line
makes the running postgres container match the compose config again. If
you roll back after it, run this step again once the `.env` line is gone.

## pg_dump in `deploy.yml`'s rehearsal

The rehearsal sends the fixed string
`cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic`
through the forced-command wrapper. It runs **inside the postgres
container** and connects over the local Unix socket, not TCP. The official
`postgres` image's `pg_hba.conf` trusts every connection from inside the
container: the Unix socket (`local all all trust`) and loopback TCP
(`host all all 127.0.0.1/32 trust` and `::1/128 trust`). It requires a
password (`host all all all scram-sha-256`) only for TCP from other
addresses, which includes the backend over the Docker network and host
tools through the published port. If that's so, the dump needs no password
and is unaffected by the rotation. Check this with the `pg_hba.conf`
command in Step 1: the `local all all` line must say `trust`. (The loopback
`trust` lines are also why the old-password check in Step 3 must run from
the backend container, not inside postgres.) Also look at the
`demo_purge` and `migrate_profiles` commands: they run in the backend
container and use `DATABASE_URL`, so Step 3's checks cover them.

If `local` is **not** `trust` (someone hardened it), the dump will start
failing after rotation. You'd need to pass the password, e.g.
`docker compose exec -T -e PGPASSWORD=... postgres pg_dump ...`, which
changes the exact string the wrapper allows. Per `DEPLOYMENT.md`, install
the new wrapper on the server **before** merging the workflow change. Keep
the secret in the server's `.env`, never in the workflow.

The rehearsal's own restore database (`postgres:rehearsal`) is a throwaway
service container on the runner and is unaffected.

## Host-side tools

Anything run on the host against `127.0.0.1:5433` (for example
`python -m app.ingest_fdc`) now needs
`DATABASE_URL=postgresql://nutrimatic:<new>@127.0.0.1:5433/nutrimatic`.
Read it from `.env` rather than typing it:
`set -a; . ./.env; set +a; export DATABASE_URL="postgresql://nutrimatic:${POSTGRES_PASSWORD}@127.0.0.1:5433/nutrimatic"`.

## Rollback

If Step 3 fails:

```sh
cd ~/nutri-matic
# 1. Put the role back to the old (known, public) password.
docker compose exec postgres psql -U nutrimatic -d nutrimatic -c '\password nutrimatic'   # enter: nutrimatic
# 2. Remove the POSTGRES_PASSWORD line from .env (the compose default takes over again).
sed -i '/^POSTGRES_PASSWORD=/d' .env
# 3. Recreate the backend with the default URL (--no-deps: see Step 2c).
docker compose up -d --no-deps backend
curl -sf https://api.nutri-matic.uk/api/ready && echo ready OK
```

The Step 0 compose change can stay. With no `POSTGRES_PASSWORD` in `.env`
it behaves exactly as before. If the data itself is in doubt, restore from
the Step 1 dump. Restoring is a separate, deliberate decision, not part of
rollback.

## Flags (found while writing this; not fixed here)

- **`JWT_SECRET` was a literal in `docker-compose.yml`.** A literal in
  `environment:` can't be overridden by `.env`, so production signed auth
  tokens with a value public on GitHub. Fixed in #109: compose now reads
  `${JWT_SECRET:?...}` from the server `.env` (which already holds a
  private value), and the backend refuses a secret shorter than 32
  characters or equal to the old literal. Deploying it logs every user out
  once. Same pattern as Step 0 here; the two changes don't conflict.
- `ci.yml` hard-codes `nutrimatic`/`nutrimatic` for its own throwaway
  service container (lines 33–39, 57, 83). That's harmless: it never
  touches production. Leave it, but don't copy those URLs anywhere real.
- `backend/app/database.py:10` falls back to the dev URL when
  `DATABASE_URL` is unset. That's harmless in production (compose sets it)
  but hides misconfiguration. Consider failing at startup when
  `APP_ENV=production` and `DATABASE_URL` is unset, as `REDIS_URL` already
  does.
- After rotation, `POSTGRES_PASSWORD` in `docker-compose.yml` still
  defaults to the dev value. That's intentional, for local dev. The
  production protection is the `.env` entry. Anyone rebuilding the server
  must restore `.env` from a secure backup *before* `docker compose up`.
  Otherwise a fresh volume is initialised with the dev password and the
  backend connects with it.
  Since #109 a missing `.env` makes compose fail on `JWT_SECRET` before
  anything starts, which catches the common case of forgetting it entirely.
