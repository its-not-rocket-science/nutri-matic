# Enterprise capabilities — design

Phase 4.3 of `nutri-matic-claude-prompts.txt`: design (not build — the
prompt says "design," and unlike Phase 4.2 there's no confirmed enterprise
customer to build against yet) enterprise features for supermarkets,
meal-kit companies, hospitals, schools, and care homes, covering both the
customer-facing capabilities and the operational requirements (API
versioning, rate limiting, audit logging, multi-tenancy) that audience
actually needs.

## Operational requirements first — because they gate everything else

The prompt is right to say "cover the operational requirements... rather
than just the customer-facing features": for this audience, the ops
requirements are the harder, more load-bearing part. Assessed against
what actually exists today:

| Requirement | Status today | Gap |
|---|---|---|
| **API versioning** | Done (Phase 3.2 — `/api/v1/*`) | None — a v2 can be added alongside v1 without disrupting existing integrations, the whole point of the versioned-prefix design. |
| **Rate limiting** | Partial — `ApiKey.quota_limit`/`requests_this_period` enforces a 30-day rolling request cap (Phase 3.2) | No *burst*/short-window rate limiting (requests-per-second or -minute). A key under its 30-day quota can currently hammer the API arbitrarily fast. Real gap for an enterprise customer doing batch analysis (see below) — needs a token-bucket or sliding-window limiter (e.g. per-key requests/minute) layered on top of the existing quota, not a replacement for it. |
| **Audit logging** | **Does not exist.** Zero application logging anywhere in this codebase (confirmed by grep — no `import logging` in `app/`), let alone an audit trail of who-accessed-what. | This is the single largest gap for this audience. Hospitals/care homes in particular will have compliance requirements (who viewed which patient/resident's data, when) that this app cannot currently answer at all. Needs: structured request logging (user/API-key id, endpoint, timestamp, outcome) persisted somewhere queryable — not just stdout — plus specific audit entries for clinician-dashboard access (Phase 4.2's `ClinicianClientLink`) given that's the existing feature closest to "someone viewing someone else's health data." |
| **Multi-tenancy** | **Does not exist** (see `docs/white-label-scoping.md`) | Every enterprise use case below (a hospital's dietitians, a school's meal planning) implies "many staff accounts under one organisation, seeing organisation-scoped data" — exactly the `Organization`/`organization_id` foundation that scoping doc identified as the expensive, not-yet-justified path. This is the real blocker for enterprise readiness, not any individual feature below. |

**Conclusion up front**: audit logging and multi-tenancy are prerequisites,
not parallel work. Building batch-analysis or procurement features before
either exists would mean enterprise customers running real organisational
data through a system with no access trail and no data isolation between
their own staff accounts and everyone else's. Sequence matters here.

## Customer-facing capabilities, by audience

### Batch analysis (all five audience types)
Score/analyse many foods or recipes in one call instead of one HTTP
round-trip per item — e.g. `POST /api/v1/foods/batch-score` accepting a
list of food ids. Genuinely low risk to build on top of existing
`scoring.py` (already pure, stateless — see
`docs/engine-separation-assessment.md`); the design work is bounding
batch size (to keep one request's cost predictable against the rate
limiter above) and deciding partial-failure semantics (one invalid food
id in a batch of 500 — fail the whole batch, or return per-item errors?
Per-item errors is almost certainly right for this audience's use case,
matching how most batch APIs behave).

### Recipe optimisation at scale (meal-kit companies, hospitals, care
homes)
This is Phase 2.2's optimiser (`optimizer.py`) applied across many
recipes/menus instead of one meal — e.g. "which of our 200 menu items
would most benefit from a swap to hit a magnesium target across the
week." Architecturally this is "call `suggest_meal_optimizations` in a
loop with an organisation's recipe set as input," not a new algorithm —
the design risk is entirely about request cost/timeout at that scale
(200 recipes × several candidate simulations each), which argues for an
async job pattern (submit batch, poll for results) rather than a
synchronous request for anything beyond a small batch size.

### Nutritional compliance checking (hospitals, schools, care homes)
"Does this menu/meal meet [some published nutritional standard]" —
genuinely useful and distinct from anything built so far, but requires
**real, cited standards data this app does not have today** (e.g. UK
school food standards, hospital nutrition standards for specific patient
groups). Same rule as everywhere else in this codebase: don't fabricate a
compliance rule set. This is buildable, but only once specific standards
are identified and sourced for a real customer — a generic "compliance
checker" against an invented rule set would be actively harmful (a school
trusting a made-up standard).

### Procurement optimisation (supermarkets, meal-kit companies)
"Given these prices and these nutritional targets, what's the
lowest-cost way to hit them" — this is Phase 2.2's budget-constrained
optimiser, but inverted (optimise for cost subject to nutrition
constraints, rather than optimise nutrition subject to a cost cap) and
operating on an organisation's own supplier pricing rather than
`FoodPrice`'s current one-price-per-user-per-food model. Needs real
supplier price-feed integration (per-supplier, per-SKU pricing, not the
consumer-facing "what did you pay at the shop" model `FoodPrice` is today)
— a genuinely different data source, not just a bigger version of the
existing feature.

### Reporting APIs (all five)
Scheduled/on-demand exports of an organisation's aggregate data (e.g. "average
micronutrient adequacy across all clients this month" for a care home).
Builds on Phase 4.2's per-client summary/trends endpoints, aggregated
across an organisation's roster instead of one client at a time — which
means it also depends on multi-tenancy (an "organisation's roster" isn't
a concept that exists yet) or, short of that, on the existing
`ClinicianClientLink` model scaled up (a single enterprise account with
many `ClinicianClientLink` rows) as a lower-effort interim approximation.

## Recommended sequencing

1. **Audit logging** — needed regardless of which customer-facing feature
   ships first, and needed before any of them touch real organisational
   data.
2. **Burst rate limiting** — cheap addition to the existing quota system,
   protects the API before batch/scale features increase load.
3. **Multi-tenancy foundation** (`Organization` table, org-scoped roles) —
   the real prerequisite for reporting APIs and for any "many staff, one
   organisation" use case. Large; should not start without a confirmed
   first enterprise customer to validate the design against (same
   reasoning as `docs/engine-separation-assessment.md`'s decision).
4. **Batch analysis** — lowest-risk customer-facing feature, buildable
   on existing stateless engine code without waiting for multi-tenancy.
5. **Recipe optimisation at scale** — next, once batch patterns (job
   submission/polling) exist from step 4.
6. **Compliance checking** and **procurement optimisation** — both
   blocked on real external data (standards, supplier pricing) that has
   to come from an actual customer relationship, not invented in advance.

Nothing in this list is implemented in this pass — this is a design
document per the prompt's own framing, consistent with how
`docs/engine-separation-assessment.md` and `docs/white-label-scoping.md`
handled the equivalent "assess before building" instruction elsewhere in
this phase.
