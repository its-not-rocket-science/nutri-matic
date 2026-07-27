# Canonical domain, security headers, and CSP

Public-launch hardening prompt 5. Before this: both `https://nutri-matic.uk`
and `https://nutri-matic.vercel.app` served the application
independently (confirmed live — both returned `200` on their own), the
rendered HTML had no `<link rel="canonical">`, Open Graph/Twitter image
URLs were root-relative, and only HSTS was observed among the
recommended security headers.

## Canonical origin — `frontend/src/lib/site.ts`

`CANONICAL_ORIGIN = 'https://nutri-matic.uk'` — one constant, not
env-configurable (unlike `VITE_API_URL`, which genuinely differs per
environment, there is exactly one real canonical public origin that
matters for SEO/redirect purposes). Used by:

- `<link rel="canonical">` and the Open Graph/Twitter `og:url`/
  `og:image`/`twitter:image` tags in `+layout.svelte`, reactive to
  `page.url.pathname` — every indexable page gets a route-correct
  canonical URL from one place, not a per-route copy.
- `sitemap.xml` (below).
- `hooks.server.ts`'s alias redirect.

## Alias redirect — `frontend/src/hooks.server.ts`

`REDIRECT_FROM_HOSTS` (`site.ts`) lists exactly one confirmed, live
alias: `nutri-matic.vercel.app`. A request whose hostname exactly
matches gets a `308` (permanent, method-preserving) redirect to the same
path/query under `CANONICAL_ORIGIN` — a plain hostname/protocol swap on
the existing `URL` object, never a manually rebuilt string that could
drop something.

Deliberately an **exact hostname allowlist**, not a pattern:

- A per-deployment preview hostname
  (`nutri-matic-<hash>-pauls-projects-24d18deb.vercel.app`) never
  matches it — preview deployments are never redirected. Verified by a
  real preview deployment during this PR's review (see the PR itself
  for the actual preview URL checked), not just in theory.
- `localhost`/CI hostnames never match either.
- `CANONICAL_ORIGIN`'s own hostname is never in the list — no redirect
  loop is possible by construction.

Regression-tested in `frontend/src/hooks.server.test.ts` (redirect
fires only for the known alias, path+query preserved, no redirect for
the canonical host/preview hostnames/localhost).

## Security headers — also `hooks.server.ts`

Set on every non-redirect response:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()` — this app uses none of these; deny by default rather than leaving the browser's permissive default.
- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` — Vercel's platform already adds a baseline HSTS header for custom domains with valid TLS (confirmed via a real request to both `nutri-matic.uk` and the Vercel alias before this prompt), but this sets an explicit, equally strong value too rather than relying on that alone.

## Content-Security-Policy — `frontend/vite.config.ts`'s `kit.csp`

Uses SvelteKit's native CSP support (`kit.csp`, passed directly into the
`sveltekit({...})` call in `vite.config.ts` — this project configures
SvelteKit that way rather than a separate `svelte.config.js`; both are
equivalent as of `@sveltejs/kit` 2.62+, and the latter is ignored when
options are passed to the Vite plugin directly). SvelteKit auto-handles
nonces/hashes for its own generated inline scripts/styles; `mode: 'auto'`
picks nonces for the dynamically-rendered pages this app actually has
(no route currently prerenders) and hashes for any that later do.

Derived from an actual inventory of this app, not a copy-pasted
template — checked directly, not assumed:

| Directive | Value | Why |
|---|---|---|
| `default-src` | `'self'` | Baseline. |
| `script-src` | `'self'` (+ auto nonce) | No external script tags anywhere in `app.html` or any route; no `eval`/`new Function`. |
| `style-src` | `'self'` (+ auto nonce/hash) | No Svelte transitions anywhere in the app (checked: `grep` for `svelte/transition`/`svelte/animate` — zero matches) — those compile to inline `<style>` elements and are the usual reason this needs loosening. |
| `style-src-attr` | `'unsafe-inline'` | Several components (`NutrientBars.svelte`, `ScoreCard.svelte`, the homepage, onboarding) set a dynamically-computed inline `style="width: N%"` for progress/score bar fills — real per-render values, not hashable ahead of time. Scoped to attribute-level only; `style-src`/`style-src-elem` stay strict. The app never renders user-controlled HTML anywhere (`{@html}` is used nowhere in the codebase), so this can't be leveraged to inject an arbitrary `<style>` block via any user-supplied content. |
| `img-src` | `'self'` | No external images, no `data:`/`blob:` image URIs anywhere. |
| `font-src` | `'self'` | No external font imports (no Google Fonts etc.) — system/bundled fonts only. |
| `connect-src` | `'self'`, the backend origin | `VITE_API_URL` (baked in at build time) computed to just its origin via `vite.config.ts`'s `loadEnv`, so it always matches whatever the actual build's backend target is per environment, never hand-copied and liable to drift. |
| `manifest-src` | `'self'` | The PWA manifest (`static/manifest.webmanifest`) is same-origin. |
| `worker-src` | `'self'` | The service worker (`src/service-worker.ts`) registers same-origin; it fetches only same-origin build assets and passes `/api/*` straight through rather than caching it. |
| `object-src` | `'none'` | No plugin content anywhere. |
| `base-uri` | `'self'` | Prevents a `<base>`-tag injection from redirecting relative URLs elsewhere. |
| `form-action` | `'self'` | No cross-origin form submissions. |
| `frame-ancestors` | `'none'` | Clickjacking protection — this app is never meant to be embedded in a frame on another site. |

No `unsafe-eval`, no blanket `unsafe-inline` on `script-src`/`style-src`
— the one narrow exception (`style-src-attr`) is scoped as tightly as
CSP allows and documented above with the actual reason, not assumed
away. Not deployed as `Content-Security-Policy-Report-Only` — there's no
report-collection endpoint in this repo to make a Report-Only rollout
meaningful, and the inventory above was verified directly (real
`curl`/browser checks against a running build — see below), so
report-only-then-promote wasn't judged necessary.

The one hand-written inline script (`app.html`'s theme-flash-prevention
snippet) uses SvelteKit's `%sveltekit.nonce%` placeholder, per the
documented mechanism for scripts not generated by SvelteKit itself.

## Verification performed

Real, not inferred:

- `npm run build` — succeeded; production build's headers checked via
  `npm run preview` + `curl -sI` — confirmed CSP, all four other
  headers, and a correctly per-request nonce present.
- `npm run dev` + a real Chrome tab: logged into a real demo account
  end to end (`POST /api/auth/demo` → `/me` → `/profiles`, all `200`/
  `201`), navigated to `/diary` via the in-app nav link, confirmed the
  nutrient bars (the `style-src-attr` case) render correctly, zero CSP
  violations in the browser console throughout.
- `vitest run` — `hooks.server.test.ts` (redirect + headers),
  `site.test.ts`, `sitemap.xml`'s `server.test.ts`, all passing
  alongside the full existing suite.
- `svelte-check` — 0 errors (one required `as any` cast in
  `vite.config.ts`: SvelteKit's `CspDirectives` types each source as a
  template-literal pattern a dynamically computed origin string can't
  be statically narrowed to, documented inline at that cast).
- **Still pending as of this commit**: verification against this PR's
  actual Vercel preview deployment (the prompt's explicit instruction —
  "test this against an actual preview deployment, not only in
  theory"). Local `npm run dev`/`npm run preview` checks above stand in
  for that until the PR itself is open and a real preview URL exists;
  see the PR description for the specific preview URL checked and its
  result before this is treated as merge-ready. The exact-hostname-
  allowlist design (a per-deployment hostname never equals the literal
  string in `REDIRECT_FROM_HOSTS`) is why no redirect is *expected*
  there — this step confirms it, rather than trusting the design
  argument alone.

## robots.txt / sitemap.xml

`static/robots.txt` now allows only `/`, `/about`, `/methodology`,
`/login`, `/register` (Google/Bing's `$` end-anchor extension — the only
practical way to allow specific exact paths under a blanket
`Disallow: /`) and points to `Sitemap: https://nutri-matic.uk/sitemap.xml`.
`frontend/src/routes/sitemap.xml/+server.ts` serves the same list
(`site.ts`'s `PUBLIC_ROUTES`) as absolute canonical-origin URLs.

Deliberately excluded from both: every authenticated-app route (diary,
meal-plan, profile, search, recipes, collections, trends, weight-log,
food-prices, clinician, foods/*) and anything demo-account-specific —
none of these have useful content for a signed-out crawler, per the
prompt's explicit instruction. Widening `PUBLIC_ROUTES` later (e.g. if
public/stock recipes are meant to be indexable) is a deliberate content
decision for whoever owns that call, not assumed here.
