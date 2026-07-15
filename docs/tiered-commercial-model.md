# Tiered commercial model

Phase 4.1 of `nutri-matic-claude-prompts.txt`. Grounded in what Phases 2-3
actually built (meal optimisation, protein complementation UX, Live/Snapshot
Mode, the public API + entitlement primitive) rather than invented
features. Pricing figures below are **illustrative placeholders, not
market research** — flagged explicitly rather than presented with false
precision, matching this codebase's own house rule against fabricated
confidence (see `nutrients.py`'s confidence-tier discipline). A real
pricing decision needs actual market research this document doesn't
attempt.

## What stays free forever, non-negotiably

Per this phase's own ground rule and `entitlements.py`'s design comment:
the **provenance/transparency layer** never gets paywalled, on any tier:

- The Data & Methodology page in full (`/methodology`), including every
  confidence-tier explanation and cited source.
- Measured-vs-estimated labelling on every digestibility/DRV figure.
- `methodology_version` stamping on every score and DRV comparison.
- Live Mode (recomputed, current-methodology diary viewing) — the default
  experience for everyone, not a downgraded free-tier view.

This is the app's stated differentiator from a calorie counter. Gating it
would directly contradict the positioning work done in Phase 1.

## Free

**Audience:** individuals tracking their own nutrition — the app's
original and still-primary use case.

**Included** (everything built in the original feature set plus Phases
1-2, all ungated today, and staying that way):
diary logging, DIAAS/PDCAAS protein quality scoring, full micronutrient
tracking against personalised DRVs, iron bioavailability estimates,
protein complementation UI, the meal optimisation engine (diary + weekly
meal-plan), recipe builder/sharing/rating/collections, diet trends, meal
planning with shopping lists and budget estimates, barcode scanning, PWA
install, print/export, and the full transparency layer above.

**Rationale:** this is not a stripped-down trial — it's the real,
complete personal-use product. The commercial surface (below) is
additive capability for people needing more than personal tracking, not
a crippled version of what already exists. Free-to-Pro conversion has to
be earned by genuinely new capability, not by artificially removing
something that already works.

## Pro

**Audience:** power users and people who've outgrown single-day/single-
device tracking — the "I want to keep receipts" segment.

**Included:**
- **Unlimited diary snapshots** (Phase 2.3's Live/Snapshot Mode) — Free
  tier gets a small number (e.g. 5) of snapshots to try the feature;
  Pro removes the cap. This is a real, already-built feature with a
  natural usage-based limit — the cleanest fit for a Free→Pro line in
  what exists today.
- **Public API access** (Phase 3.2) at a modest quota (the entitlement
  primitive's `quota_limit`, e.g. 1,000 requests/30 days by default) —
  for a Pro user building their own tooling against their own data.
- Priority on the meal-optimiser/shopping-list budget-constrained
  suggestions (no functional difference today — the optimiser has no
  rate-based degradation to lift — noted honestly as a placeholder
  differentiator until a real one exists).

**Rationale:** low price, individual self-serve, no sales process. Value
is "more of what already works," not new functionality — appropriate for
a tier that shouldn't require a sales conversation.

**Upgrade path:** self-service, in-app, immediately after hitting the
Free-tier snapshot cap or wanting API access — the natural moments Free
users would encounter a real limit.

## Professional

**Audience:** dietitians, nutritionists, and other individual
professionals managing multiple clients — scoped in
`docs/professional-dashboard-scope.md` (Phase 4.2, built alongside this
doc).

**Included:** everything in Pro, plus the clinician-facing dashboard
(client roster, at-a-glance micronutrient gaps and protein quality across
clients, longitudinal comparison, branded/printable client reports) —
see the Phase 4.2 doc for exactly which of those are Professional-only
versus available to any registered account claiming a professional role.

**Rationale:** priced for a working professional's practice-management
spend, not a consumer impulse purchase — this is the first tier requiring
functionality that doesn't exist for individuals at all (multi-client
views), so it's the first tier with genuinely new product surface, not
just higher limits.

**Upgrade path:** self-service is plausible (a solo dietitian doesn't
need a sales call), but likely benefits from a light-touch onboarding
conversation given the professional-liability context (see Phase 4.2's
disclaimers around clinical use).

## Enterprise

**Audience:** supermarkets, meal-kit companies, hospitals, schools, care
homes — scoped in `docs/enterprise-capabilities.md` (Phase 4.3).

**Included:** batch analysis, recipe optimisation at scale, compliance
checking, procurement optimisation, reporting APIs — plus the operational
requirements that audience actually needs (higher/custom API quotas,
audit logging, SLA). Explicitly **not** included until scoped separately:
true multi-tenant white-labelling (see `docs/white-label-scoping.md` —
the current single-tenant `models.py` doesn't support it without a real
foundational change).

**Rationale:** priced per negotiated contract, not a published number —
the standard model for this audience size, and honest about the fact this
tier's actual feature set depends on enterprise customers' operational
requirements more than a fixed feature list.

**Upgrade path:** sales-led, not self-service — this audience expects a
contract and an SLA conversation, not a credit-card signup.

## What this document deliberately does not do

Assign real prices. Every commercial SaaS pricing decision needs actual
market research (competitor pricing, willingness-to-pay data, unit
economics) that a documentation pass inside a coding session cannot
responsibly produce. Treat the tier *boundaries* (what's in each) as the
deliverable here; treat prices as a placeholder for whoever does that
research.
