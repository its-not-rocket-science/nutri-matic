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
| Server `~/nutri-matic/.env` (untracked, `.gitignore` line 4) | `CORS_ORIGINS`, `TRUSTED_PROXY_HOP_COUNT`, `OPS_DIAGNOSTIC_TOKEN`, … | Yes. This is where the new password goes |

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
#     (Compose sees the changed environment and recreates the container.
#     Only the backend: don't recreate postgres, it gains nothing.)
docker compose up -d backend
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
# Confirm the old password is refused over TCP:
docker compose exec -T postgres sh -c 'PGPASSWORD=nutrimatic psql -h 127.0.0.1 -U nutrimatic -d nutrimatic -c "select 1"' \
  && echo "OLD PASSWORD STILL WORKS: investigate" || echo "old password refused: good"
docker compose logs --since 10m backend | grep -i -E 'password authentication failed|OperationalError' || echo "no auth errors"
```

Then trigger the deploy workflow by hand (**Actions → Rehearse and Deploy
Backend → Run workflow**) and confirm the rehearsal's `pg_dump` step still
succeeds. That proves the rehearsal path end to end. Approve or reject the
production step as you see fit; the rehearsal is what matters here.

## pg_dump in `deploy.yml`'s rehearsal

The rehearsal sends the fixed string
`cd nutri-matic && docker compose exec -T postgres pg_dump -U nutrimatic -Fc nutrimatic`
through the forced-command wrapper. It runs **inside the postgres
container** and connects over the local Unix socket, not TCP. The official
`postgres` image's `initdb` normally leaves `local all all trust` in
`pg_hba.conf` and adds password auth only for `host` (TCP) connections. If
that's so, the dump needs no password and is unaffected by the rotation.
Check this with the `pg_hba.conf` command in Step 1. Also look at the
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
# 3. Recreate the backend with the default URL.
docker compose up -d backend
curl -sf https://api.nutri-matic.uk/api/ready && echo ready OK
```

The Step 0 compose change can stay. With no `POSTGRES_PASSWORD` in `.env`
it behaves exactly as before. If the data itself is in doubt, restore from
the Step 1 dump. Restoring is a separate, deliberate decision, not part of
rollback.

## Flags (found while writing this; not fixed here)

- **`JWT_SECRET` is a literal in `docker-compose.yml`**
  (`backend.environment.JWT_SECRET: "1596…"`). The comment next to it says
  a real deployment must override it via an untracked `.env`. But a literal
  in `environment:` **can't** be overridden by `.env`; only `${VAR}`
  interpolation reads `.env`. Unless the server has a
  `docker-compose.override.yml` or another mechanism (not visible in this
  repo), production signs auth tokens with a value that is public on
  GitHub. Check on the server:
  `docker compose exec -T backend python -c "import os; print(os.environ['JWT_SECRET'].startswith('1596dfe3'))"`.
  If it prints `True`, rotate it the same way (`${JWT_SECRET:?}` in
  compose, value in `.env`). Every existing session will be logged out.
  This is more urgent than the DB password.
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
