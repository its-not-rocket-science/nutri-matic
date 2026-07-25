# Frontend deployment

Operational-hardening prompt 6. `frontend/` builds with `@sveltejs/
adapter-vercel` — this repo has a live Vercel project
(`pauls-projects-24d18deb/nutri-matic`) already connected to GitHub,
auto-deploying every push and pull request (visible as the `Vercel`/
`Vercel Preview Comments` status checks on any PR). `adapter-vercel`
targets Vercel's Build Output API directly, which is what that
integration actually expects.

> **Corrected after initially shipping `adapter-node`.** The first pass
> at this prompt picked `adapter-node` from repo-local configuration
> alone (the backend's `Dockerfile`/`docker-compose.yml`) without
> checking *actual current hosting* — which the prompt explicitly asks
> for, and which this missed. The existing Vercel integration was only
> discovered afterward, via the status checks on an unrelated PR.
> `adapter-node`'s build reported "Ready" on Vercel too (Vercel can run
> a Node server build, just not through its native Build Output API
> path), but was never actually confirmed working end-to-end there
> before being corrected. Kept as a matter of record, not to relitigate
> it — the adapter actually installed and committed is `adapter-vercel`.

## Build

```bash
cd frontend
npm run build      # writes .vercel/output/ — Vercel's Build Output API v3
                    # (config.json + functions/ + static/), not a standalone server
```

There is no local `npm run build && node ...` run step the way
`adapter-node` had — `.vercel/output/` is consumed by Vercel's own
platform (or `vercel dev`/`vercel build` tooling), not run directly with
plain `node`. Local iteration during development still uses `npm run
dev`, unaffected by the adapter choice.

`VITE_API_URL` (see `frontend/.env`) is baked in **at build time** — it
becomes part of the compiled client bundle, not something read at
request time. Vercel's own project settings (Environment Variables)
control what value is baked in for each of its own build contexts
(production/preview/development) — this is Vercel's mechanism, not
something this repo's `.env` file controls for deployed builds.

## Vercel project configuration

Set in the Vercel project's own dashboard (Settings → Environment
Variables), not in this repo:

| Variable | Environment(s) | Purpose |
|---|---|---|
| `VITE_API_URL` | Production, Preview | The backend origin this build's client bundle will call. Needs a real, reachable backend URL for each environment it's set for — a preview deployment with no backend to call will build fine and then fail every API request at runtime. |

No other frontend-specific environment variables are required —
`adapter-vercel` doesn't need the `PORT`/`ORIGIN`/`HOST` runtime
variables `adapter-node` did, since Vercel's platform handles routing
and doesn't run this as a conventional long-lived Node server process.

## Verification performed

Real, not inferred:

- `npm run build` — succeeded, confirmed `Using @sveltejs/
  adapter-vercel` in the build output, and confirmed the resulting
  `.vercel/output/` directory matches Vercel's Build Output API v3
  shape (`config.json`, `functions/`, `static/`).
- `vitest run` (17 passed) and `svelte-check` (0 errors, same 1
  pre-existing unrelated warning) both remain green after the
  dependency swap.
- **Not independently re-verified with a full browser smoke test**
  against a real Vercel deployment — the earlier `adapter-node` pass
  did run that (registration, CORS, recommendation panel, all against
  a real isolated backend — see the commit history for that test if
  useful as a reference), but re-running an equivalent test against an
  *actual* Vercel deployment needs either Vercel CLI credentials (not
  available in this environment) or waiting for this change's own PR
  preview deployment and checking it manually — the repository owner is
  better placed to do the latter than a from-this-machine local repeat.

## What "current hosting" actually is, for future reference

This is the fact this prompt's first pass got wrong by not checking for
it: the frontend's real deployment target is Vercel, connected via
GitHub integration, not chosen or configured from anything in this
repository's own files. Check the PR status checks (`Vercel`, `Vercel
Preview Comments`) or the Vercel dashboard directly — not just
`Dockerfile`/`docker-compose.yml` — before concluding what "current
hosting" is for either half of this app in the future. The backend
still has no such integration as of this writing; `docker-compose.yml`
remains its only concrete deployment story.
