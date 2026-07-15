# Revenue opportunities audit

Phase 5.1 of `nutri-matic-claude-prompts.txt` — an audit deliverable, not
an implementation prompt. Ranks every realistic revenue stream by
implementation effort, time to revenue, market size, and strategic value,
grounded in what Phases 2-4 actually built. Ratings are qualitative
(High/Medium/Low), not fabricated numeric market-size estimates — this
app's own house rule against false precision applies here too; a
specific dollar figure with no market research behind it would be worse
than no figure.

## Ranked summary

| Stream | Effort remaining | Time to revenue | Market size | Strategic value | Priority |
|---|---|---|---|---|---|
| 1. Subscriptions (Free/Pro/Professional) | Low | Fast | Large, crowded | High | **Do first** |
| 2. Healthcare — individual dietitians (Professional tier self-serve) | Low-Medium | Medium | Large | High | **Do first** |
| 3. API licensing | Low | Fast | Small-Medium | Medium | **Do second** |
| 4. Research partnerships | Medium | Slow | Small | Medium-High (credibility) | Opportunistic |
| 5. Consultancy | Low (no eng.) | Fast | Small (bandwidth-limited) | Low-Medium | Opportunistic |
| 6. Education/institutional | Medium | Slow | Medium | Medium | Later |
| 7. Enterprise licensing (supermarkets, meal-kits, hospitals, care homes) | High | Slow | Large per-deal, few deals | High | Later, needs prerequisites |
| 8. Government | High | Very slow | Large per-contract, rare | High if won, high risk | Speculative |
| 9. Supermarket/procurement partnerships | High | Slow | Large, speculative | Medium-Low near-term | Speculative |

## 1. Subscriptions — do first

**What exists**: the entitlement primitive (Phase 3.1), real tier
gating tied to genuine cost (Phase 4.4 — snapshot storage, API quota,
clinician roster size), and a tier structure already scoped
(`docs/tiered-commercial-model.md`). **What's missing**: actual billing
integration — `billing.py`'s `NoOpBillingProvider` is a deliberate stub
(Phase 3.2), and there's no payment collection anywhere. This is the
single lowest-effort-to-first-dollar stream: wire a payment provider
(Stripe or similar) behind the existing `BillingProvider` interface, and
subscriptions can start immediately. Market is large but competitive
(consumer nutrition apps); this app's real differentiation (computed
protein quality/bioavailability/complementarity vs. calorie counting) is
a genuine edge with a specific audience (serious athletes, people
managing health conditions where protein quality or micronutrient
absorption specifically matters) rather than the general fitness-app
market.

## 2. Healthcare — individual dietitians — do first

Phase 4.2's clinician dashboard is real, tested, working functionality
today — the lowest-additional-engineering-effort path to healthcare
revenue is simply *selling the Professional tier to individual
dietitians/nutritionists*, which requires no new engineering beyond
subscription billing (stream 1). This is distinct from — and much faster
than — institutional healthcare sales (hospitals, EHR integration,
compliance), which belongs under Enterprise (stream 7) instead. Real
caveat, disclosed in `docs/professional-dashboard-scope.md`: no license
verification exists, so marketing this segment honestly means being
upfront that "clinician mode" is self-declared, not credential-checked,
until/unless verification is built.

## 3. API licensing — do second

Phase 3.2's public API and Phase 4.4's plan-differentiated quotas are
built and tested. Same billing dependency as streams 1-2. Market is
smaller (developers building their own nutrition tooling who want real
DIAAS/bioavailability computation rather than building it themselves),
but marginal cost to serve is near-zero (same engine every other tier
uses) and requires no new product surface — pure incremental revenue on
top of infrastructure that already exists for other reasons.

## 4. Research partnerships — opportunistic

Academic nutrition researchers as customers/collaborators: not a
built feature (no cohort management, anonymised export, or IRB-consent
flow exists), but the barrier to a *first* research relationship is low
— the existing methodology transparency (measured/estimated labelling,
cited sources, `methodology_version`) is exactly what a researcher would
want to see before trusting a tool's numbers. Revenue itself is likely
small (grants/academic budgets are modest and slow), but the strategic
value is real: independent academic validation of the scoring/
bioavailability methodology would be a strong credibility signal for
every other stream, particularly healthcare and enterprise.

## 5. Consultancy — opportunistic

Not a software revenue stream at all — this is domain-expertise
consulting (nutrition science + the specific rigor this codebase
demonstrates) sold directly, independent of the product roadmap. Fast to
start (no engineering dependency), but doesn't scale with the product and
competes for the same time that would otherwise go into building the
product. Reasonable as an opportunistic, not primary, stream — e.g.
saying yes to an inbound request, not actively building a consulting
practice.

## 6. Education/institutional — later

Licensing to nutrition-education programs (discounted institutional
seats, curriculum alignment) is plausible given the app's real scientific
rigor, but needs relationship-building with institutions (slow) and
likely some product work (cohort/classroom management doesn't exist).
Reasonable as a later-stage stream once individual subscriptions (stream
1) and healthcare (stream 2) have validated willingness to pay at all.

## 7. Enterprise licensing — later, needs prerequisites

Supermarkets, meal-kit companies, hospitals (institutionally, as opposed
to individual dietitians), schools, care homes — scoped in
`docs/enterprise-capabilities.md`, which identifies audit logging and
multi-tenancy as real prerequisites, not parallel work. Large potential
per-deal value, but high engineering cost before a single deal is
possible, and enterprise sales cycles are inherently slow. Correctly
sequenced *after* subscriptions and healthcare (self-serve) prove the
core product's value, both because that revenue funds the prerequisite
engineering and because a validated individual-user product is a much
stronger enterprise sales pitch than an unvalidated one.

## 8. Government — speculative

School meal programs, military/institutional nutrition, public health
agencies. Blocked on the same compliance-checking capability
`docs/enterprise-capabilities.md` flags as needing *real, sourced*
standards data this app doesn't have — and government procurement is
slow and relationship-driven even once a product is ready. High value if
achieved (stable, prestigious, large contracts), but the effort-to-first-
dollar ratio is the worst of any stream here. Not a near-term priority.

## 9. Supermarket/procurement partnerships — speculative

Distinct from stream 7's supermarket-as-enterprise-customer angle — this
is deeper integration (procurement optimisation against real supplier
price feeds, per `docs/enterprise-capabilities.md`). Requires data
partnerships this app has no current relationships to build on. Genuinely
interesting long-term but entirely dependent on a specific partner
conversation that doesn't exist yet — nothing to build speculatively.

## What this audit does not do

Assign real dollar figures, conversion-rate assumptions, or a financial
model. Those require actual market research and would be fabricated
precision if produced here — same reasoning as
`docs/tiered-commercial-model.md`'s refusal to invent prices. Treat the
relative ranking above as the deliverable.
