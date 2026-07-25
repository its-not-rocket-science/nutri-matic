# Frontend deployment

Operational-hardening prompt 6. `frontend/` builds with `@sveltejs/
adapter-node` — a plain Node.js server, chosen because this repo's only
actual deployment story is the backend's own Docker/`docker-compose`
setup; `adapter-node` is the standard choice for that kind of Docker/VM
deploy, not a guess about a platform (Vercel/Netlify/Cloudflare) nothing
else in this repo uses. `adapter-auto`'s "Could not detect a supported
production environment" build warning is gone as a result — the adapter
is chosen and committed (`frontend/vite.config.ts`), not auto-detected.

## Build and run

```bash
cd frontend
npm run build      # writes build/ — a self-contained Node server, not static files
node build/index.js
```

`VITE_API_URL` (see `frontend/.env`) is baked in **at build time** — it
becomes part of the compiled client bundle, not something read at
server startup. Pointing a build at a different backend origin needs a
rebuild with that variable set, not just a different runtime
environment variable.

## Required runtime environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PORT` | No | `3000` | Port the Node server listens on. |
| `ORIGIN` | Yes in production | none — SvelteKit warns/misbehaves on form actions and CSRF checks without it | The public URL this app is served at (e.g. `https://app.example.com`) — adapter-node needs this to correctly construct absolute URLs and validate same-origin requests. |
| `HOST` | No | `0.0.0.0` | Interface to bind. |
| `BODY_SIZE_LIMIT` | No | `512kb` | Raise if a route ever needs to accept a larger request body. |

(`VITE_API_URL` is **not** a runtime variable for the built server — see
above.)

## Verification performed

Real, not inferred — see the commit that introduced `adapter-node` for
exact commands:

- `npm run build` — succeeded, `adapter-auto`'s warning gone, confirmed
  `Using @sveltejs/adapter-node` in the build output.
- Started the built server locally (`PORT=4173 ORIGIN=http://localhost:4173
  node build/index.js`) and confirmed via direct HTTP requests: the root
  route, `/login`, a nested route (`/diary`) hit directly (proving
  refresh-on-a-nested-route works — a raw GET on a nested path returning
  real SSR HTML, not a 404, is exactly what a browser refresh needs),
  and a deliberately-nonexistent route (correctly 404s, confirming
  routing isn't just returning 200 for everything) — all through
  `curl`, checking status codes and that real page HTML (not an error
  page) came back.
- Static assets (`/manifest.webmanifest`, an icon under `/icons/`)
  served correctly.
- **Full browser smoke test**, real evidence via the browser's own
  network log, not inferred: built the frontend against a temporary,
  isolated backend (its own throwaway Postgres database, migrated to
  head, `CORS_ORIGINS` set to the preview server's origin — never the
  real `docker-compose` backend or its data), then in an actual browser:
  registered a new account, confirmed the CORS preflight (`OPTIONS`) and
  the real request both returned `200`/`201` for `/api/auth/register`,
  `/api/auth/me`, and `/api/profiles`; navigated to `/diary`, expanded
  the "Improve this day" recommendation panel, and confirmed
  `/api/recommendations/ingredients` returned `200` — the recommendation
  panel genuinely loads and calls the backend successfully, not just
  renders an empty shell. No console errors, no CORS failures. The
  temporary backend, its database, and the browser tab were all torn
  down afterward; nothing about this test touched the real
  `docker-compose` service or its data.

**Not done**: an actual external "preview deployment" on real hosting
infrastructure — this repo has no hosting platform selected yet (see
`DEPLOYMENT.md`), so "deploy a preview and smoke-test it" was performed
as a local, not external, smoke test. The verification above is real
(a real built server, a real isolated backend, a real browser, real
network requests) but ran on this machine, not on production-equivalent
infrastructure.
