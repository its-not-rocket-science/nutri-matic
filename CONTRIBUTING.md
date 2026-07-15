# Contributing

## Running checks locally (same as CI)

CI (`.github/workflows/ci.yml`) runs two independent jobs on every push and
pull request. To reproduce them locally:

### Backend

Needs a real Postgres instance — the test suite exercises the actual
dialect-specific code paths (e.g. the `pg_trgm` fuzzy-search fallback in
`search.py`), not just SQLite. The bundled `docker-compose.yml` provides one:

```bash
docker compose up -d postgres
cd backend
pip install -r requirements.txt
pytest -q
```

`DATABASE_URL` defaults to the docker-compose Postgres (`localhost:5433`);
override it if you're pointing at a different instance.

CI also runs `pip-audit` here, informationally (doesn't fail the build —
see `docs/production-readiness-audit.md` for why).

### Frontend

```bash
cd frontend
npm ci
npm run check   # svelte-check — type errors fail this the same way CI fails
npm run build
```

CI also runs `npm audit --audit-level=high` here, informationally.

## Before opening a PR

- Both jobs above should pass locally first — CI runs the same commands,
  not a stricter or different check.
- Add or update tests for any change to `backend/app/` — see the existing
  `backend/tests/` files for the two established patterns (pure-function
  tests against an in-memory SQLite session, and `TestClient` +
  `dependency_overrides[get_db]` router-integration tests).
- If a change alters what a previously-computed score or DRV comparison
  means, bump the relevant constant in `backend/app/methodology.py` rather
  than changing behaviour silently — see that file's docstring.
- Keep the measured-vs-estimated provenance labelling and confidence tiers
  honest: don't report more precision or certainty than the underlying
  data supports.
