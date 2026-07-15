# Full product, technical, and investment-readiness audit

Phase 5.2 of `nutri-matic-claude-prompts.txt` — the capstone review.
Extends Phase 0's hardening checklist into full technical due diligence,
reviews the product from five stakeholder perspectives, and assesses
adoption blockers, IP defensibility, scalability, and competitive
differentiation. Per the prompt's own instruction, only the
highest-impact/lowest-risk fixes were implemented directly (see
"Fixes implemented in this pass" below); everything else is a prioritised
roadmap item for separate review, not an implementation backlog to work
through unsupervised.

## Fixes implemented in this pass

Two, chosen specifically because they were high-impact, low-risk, and
*verifiable* against the real running system rather than theoretical:

1. **`food_nutrients` composite index** (`ix_food_nutrients_key_amount`
   on `(nutrient_key, amount_per_100g)`). The gap-suggestions/meal-optimize
   query path (`_rank_foods_by_nutrient`) filters by `nutrient_key` and
   sorts by `amount_per_100g` on every call, with no supporting index.
   Measured on the real docker database (222,222 rows from the current
   partial USDA ingestion): **137ms sequential scan → 0.175ms index
   scan**, a ~780x improvement on a hot path hit by two endpoints across
   two routers. See `DEPLOYMENT.md`'s "Manual migrations" section for the
   `CREATE INDEX` needed on any database that predates this change.
2. **PyJWT 2.10.1 → 2.13.0**. `pip-audit` found real CVEs against the
   pinned version, including in the auth-critical signing/verification
   path. Verified safe: full test suite (309 tests, including every
   auth-specific test) passes unchanged, and a real register→token→
   `/api/auth/me` round trip against the rebuilt docker image succeeds.
   Other flagged dependencies (`starlette`, `pytest`, `python-dotenv`)
   were deliberately **not** bumped in this pass — their upgrade paths
   have larger transitive surface area (`starlette` in particular is
   pinned by `fastapi`, so bumping it means verifying FastAPI
   compatibility too) and deserve dedicated attention rather than a
   rushed bump at the end of a long work session. Tracked in the roadmap
   below.
3. **CI dependency vulnerability scanning** (`pip-audit`, `npm audit`),
   added as **informational, non-blocking** steps to `.github/workflows/ci.yml`.
   Non-blocking specifically because `npm audit` currently reports a
   transitive `cookie` advisory via `@sveltejs/kit` whose only available
   fix is a breaking downgrade — there's no safe non-breaking fix
   available today, so a blocking scan would either permanently red the
   build or force a risky change; informational visibility is the honest
   middle ground until that's specifically addressed.

## Stakeholder perspectives

### Consumers
**Real strength**: the app does something calorie counters genuinely
don't (protein quality, bioavailability, complementarity, computed not
guessed) — see `README.md`'s Example Outputs section for concrete,
reproducible numbers. **Real blocker**: no billing exists yet (Phase 3.2's
`NoOpBillingProvider` is a deliberate stub), so there is currently no way
to actually charge anyone — the product can be used but not yet sold.
**Secondary blocker**: food data isn't bundled (`README.md`'s
Installation section) — a consumer can't self-serve onto a hosted
instance without someone having already run the USDA ingestion; there is
no public hosted instance today.

### Dietitians / nutritionists
**Real strength**: Phase 4.2's clinician dashboard is real, tested
functionality built specifically for this audience, reusing the same
live-computed data a client sees for themselves. **Real blocker,
disclosed explicitly in `docs/professional-dashboard-scope.md`**: no
license verification exists — "clinician" is self-declared. For a
dietitian evaluating this professionally, that's a legitimate trust
question this document does not paper over.

### Researchers
**Real strength**: the methodology transparency (measured/estimated
labelling, cited sources back to FAO/WHO/UK RNI, `methodology_version`
stamping, Live/Snapshot Mode for reproducibility — see
`docs/live-vs-snapshot-mode.md`) is exactly the kind of auditable
methodology a researcher would need to trust before using this as a data
source. **Real blocker**: no cohort management, anonymised export, or
consent/IRB-workflow features exist — a researcher today could use this
as an individual tool, not as research infrastructure.

### Food companies (meal-kit, supermarket, procurement)
**Real blocker, not yet a strength**: nothing built for this audience
beyond design docs (`docs/enterprise-capabilities.md`). Procurement
optimisation specifically needs real supplier price-feed data this app
has no access to. This is the least-ready stakeholder segment today.

### Investors
**Real strength**: a genuinely differentiated product (see Competitive
differentiation below) with working software across the full stack,
tested (309 backend tests, CI-enforced), and a coherent tier/entitlement
model already wired (not just planned) for at least two segments
(individual subscriptions, professional/clinician). **Real blocker**: pre-
revenue (billing stub, no live payment collection), single-tenant
architecture that caps addressable enterprise revenue until multi-tenancy
is built (`docs/white-label-scoping.md`), and — the most fundamental gap
for due diligence — **no usage/traction data of any kind**, because there
is no logging or analytics anywhere in the stack (see Technical due
diligence below). An investor cannot currently be shown "X users, Y%
retention" because the system has no way to measure either.

## Technical due diligence (extends Phase 0's checklist)

Phase 0 covered secrets/config hygiene, CI, and the auth model review.
Extending it:

| Area | Status | Assessment |
|---|---|---|
| Test coverage | 309 backend tests, CI-enforced against real Postgres | Strong for a project this size; nutrition-calculation modules specifically are at/near 100% (see earlier testing-audit work) |
| Application logging | **None** — zero `import logging` anywhere in `app/` | Real gap. No way to debug a production incident after the fact beyond whatever the hosting platform captures at the process level. |
| Error monitoring | **None** — no Sentry-equivalent, no structured exception capture | Same root cause as above; an unhandled exception in production is invisible until a user reports it. |
| Audit logging | **None** (flagged in `docs/enterprise-capabilities.md`) | Blocks any customer with compliance requirements (healthcare, education, government) from adoption, not just enterprise specifically. |
| Rate limiting | Partial — `ApiKey` has a 30-day rolling quota (Phase 3.2/4.4), but no burst/per-minute limiting | A key under quota can still call as fast as the network allows. |
| Database backups/DR | Not addressed anywhere in this codebase or its docs | Real operational gap — `DEPLOYMENT.md` tells you how to point at a Postgres instance, not how to make sure it's recoverable. |
| Dependency vulnerabilities | Now scanned (informational) in CI as of this pass; PyJWT patched | starlette/pytest/python-dotenv bumps still pending — see roadmap. |
| Horizontal scalability | **Real strength** — JWT is stateless (no server-side session store), FastAPI/Uvicorn workers are stateless, so the backend should scale horizontally without architectural changes. Not load-tested to confirm. |
| Query performance | One real hot-path issue found and fixed this pass (`food_nutrients` index); no broader query audit performed beyond what's flagged from direct experience building features this session. |
| Frontend adapter | `@sveltejs/adapter-auto` doesn't target a real deployment platform (`DEPLOYMENT.md`, flagged in the earlier production-readiness pass) — still unresolved, needs a specific target platform decision. |
| Staging environment | None exists — `docker-compose.yml` is dev-only, there's no separate pre-production environment described anywhere. |

## Adoption blockers, by segment

1. **No billing** — blocks all commercial adoption regardless of segment
   (consumers, dietitians, enterprise all need to be chargeable).
2. **No usage analytics/logging** — blocks investor due diligence and
   blocks the team's own ability to know what's working.
3. **No license verification** — blocks confident dietitian/healthcare
   adoption at the trust level, independent of features.
4. **No audit logging** — blocks any compliance-sensitive customer
   (healthcare, education, government) regardless of feature completeness.
5. **Single-tenant architecture** — blocks true enterprise/institutional
   sales (many staff, one organisation) until the multi-tenancy
   foundation from `docs/white-label-scoping.md` is built.
6. **No bundled data / no public hosted instance** — blocks frictionless
   consumer signup today; a real deployment needs someone to run the USDA
   ingestion first.

## IP defensibility

Honest assessment: **the underlying nutrition science (DIAAS/PDCAAS
formulas, FAO amino acid patterns, Monsen bioavailability constants) is
published, cited, public science — not defensible IP**, and shouldn't be
claimed as such (this app's own credibility rests on citing real sources,
not obscuring them). What's genuinely defensible:

- **Data curation work**: `digestibility_reference.py`'s carefully
  sourced, citation-traced coefficients (explicitly excluding
  study/food mismatches rather than guessing) represent real accumulated
  effort that's slow to replicate — a time-to-replicate moat, not a legal
  one.
- **The specific combination and implementation**: the meal optimiser,
  complementation engine, and Live/Snapshot Mode together, computed live
  against real simulated data rather than heuristics, is a genuine
  engineering asset — copyright-protected as code, though the underlying
  *ideas* (simulate a swap, compute the delta) aren't patentable novelty
  on their own.
- **No patents filed, no trademark registered** on "Nutri-Matic" — both
  would need real legal work this document can't substitute for. Flagged
  as a gap, not resolved here.
- **Data partnerships/relationships** (a real customer's supplier price
  feed, a research collaboration) would be more defensible than anything
  in the codebase itself, but none exist yet (see Revenue audit,
  `docs/revenue-opportunities-audit.md`).

## Scalability limits

- **Fixed in this pass**: the `food_nutrients` query hot path (see
  above) — was a real, measured bottleneck at today's partial-ingestion
  scale (222k rows), would have gotten worse with a full USDA import
  (300k+ branded foods alone).
- **Not addressed**: no caching layer anywhere (every request recomputes
  live, which is a deliberate design choice for Live Mode's correctness
  — see `docs/live-vs-snapshot-mode.md` — but means there's no fallback
  if compute cost becomes a real problem at higher traffic).
- **Not addressed**: no load testing has been performed; the "should
  scale horizontally" assessment above is architectural reasoning, not a
  measured result.
- **Not addressed**: Postgres itself — no read-replica, connection
  pooling (beyond SQLAlchemy's defaults), or partitioning strategy
  discussed anywhere.

## Competitive differentiation

Real, feature-level differentiation (not fabricated market-share claims
about named competitors, which this document can't verify): most
consumer nutrition-tracking tools optimise for calorie/macro logging
speed and food-database breadth. This app's differentiation is depth on
protein quality (DIAAS not just protein grams), bioavailability
(absorbed-vs-logged iron, computed not estimated from a flat percentage),
computed complementarity (real simulated pairings, not a folk-wisdom
list — see `README.md`'s rice/bratwurst example, which is itself evidence
the system computes rather than recites), and transparency (every figure
labelled measured/estimated with a cited source, methodology-versioned).
Whether that depth is a defensible wedge against broader competitors with
more resources is a market question this document isn't positioned to
answer with confidence — it's a real, verifiable technical difference,
not a proven business moat.

## Prioritised roadmap (not implemented in this pass)

Ordered by the same effort/impact reasoning used throughout Phases 0-5:

1. **Application logging + error monitoring** — foundational, blocks
   debugging production issues and blocks ever having real usage data for
   stakeholder/investor conversations. Should precede any real user
   traffic.
2. **Billing integration** (behind the existing `BillingProvider`
   interface) — unblocks every commercial revenue stream in
   `docs/revenue-opportunities-audit.md`.
3. **Remaining dependency upgrades** (`starlette`, `pytest`,
   `python-dotenv`) — each needs its own compatibility check, not a bulk
   bump.
4. **Audit logging** — needed before any compliance-sensitive customer
   (healthcare, education, government) can adopt.
5. **Database backup/DR plan** — operational basic, currently entirely
   undocumented.
6. **Burst rate limiting** on top of the existing 30-day quota.
7. **SvelteKit adapter decision** (`adapter-auto` → a real target) —
   cheap once a hosting platform is chosen, blocks a real production
   frontend deploy until then.
8. **License verification** for clinician accounts — a trust/adoption
   blocker for the healthcare segment specifically, more of a product/
   process decision (what verification is even feasible) than a pure
   engineering task.
9. **Multi-tenancy foundation** — large, and per
   `docs/engine-separation-assessment.md`/`docs/white-label-scoping.md`'s
   established reasoning, should wait for a confirmed first enterprise
   customer to validate the design against rather than being built
   speculatively.
10. **Load testing** — once there's a real hosting target and a
    plausible traffic estimate to test against (not meaningful to do in
    the abstract).

This list is the deliverable — implementing it is explicitly out of scope
for this pass, per the prompt's own instruction not to let this turn into
an uncontrolled implementation pass.
