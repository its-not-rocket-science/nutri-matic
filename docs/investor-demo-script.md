# Investor demo script — first 10 minutes

A run-of-show for a live walkthrough, timed to ~10 minutes. Every screen
referenced below exists and works today — this is a script for the real
product, not a mockup. No traction/revenue numbers are asserted here; this
is a product-and-strategy walkthrough, not a metrics deck.

## 0:00–1:00 — The problem

Open the landing page (logged out, `/`). Lead with the headline, not a
slide: *"Know exactly what's in your next meal — down to the limiting
amino acid."*

Say: every mainstream nutrition app counts calories. None of them tell you
whether the protein you ate was actually usable, whether your iron intake
was absorbable, or what specific, costed change would fix it. That gap is
the whole product.

## 1:00–3:00 — The solution, live

Click **Try the demo** — a fresh, pre-seeded account in ~7 seconds, no
signup form on screen. This alone is worth dwelling on: a prospective user
never fills in a blank state before seeing value.

Land on the dashboard. Point at the four cards in order — they *are* the
pitch:
1. **Today's nutrition** — real energy vs. a personalised target.
2. **Biggest gap** — the single worst nutrient today, with a named food
   that fixes it (not a generic "eat more vitamin D" tip).
3. **Highest-impact recommendation** — the optimiser's actual top
   suggestion: add/swap X, quantified before → after, with real cost.
4. **Optimiser** — the entry point to run this against any meal.

Click into a food (e.g. the seeded chicken). Show the DIAAS/PDCAAS gauge,
the limiting amino acid called out, and the "measured vs. estimated"
badge on the digestibility source.

## 3:00–5:00 — Why this is hard to copy

Open `/methodology`. This is the moat, not an appendix: every number
traces to a named USDA dataset, a cited study, or an explicitly-labelled
category estimate — "we don't know" is a real, frequent, visible answer
in this app, not a gap competitors would casually replicate, because it's
a discipline, not a feature.

Open `/profile`'s dietary-requirements section. Show adding a peanut
allergy and the honesty note next to it: this is a *name-based* match
against USDA descriptions, explicitly caveated as unreliable for branded
products, never silently presented as verified. That caveat is itself the
differentiator — a competitor that overclaims safety here is one bad
allergic reaction away from a real problem; this product is built not to
make that mistake.

## 5:00–7:00 — Commercial model

Reference `docs/tiered-commercial-model.md` verbally rather than reading
it: Free is a genuinely complete personal product (diary, scoring,
optimiser, recipes) — not a crippled trial. Pro and Professional gate only
on real metered cost (snapshot storage, API quota, clinician roster size),
never on a capability that costs the same at 1 user or 1,000. The
provenance/transparency layer is free forever, on every tier, by design —
it's the trust mechanism the rest of the pricing depends on.

If there's a healthcare/B2B angle to the room: open `/clinician` and show
the consent-gated client-invite flow and the multi-client dashboard —
this is real, tested code today, not a roadmap slide (see
`docs/revenue-opportunities-audit.md`, ranked as the second highest-value
build already largely done).

## 7:00–9:00 — What's already real vs. what's next

Be direct about the line between built and planned:
- **Built and tested**: entitlement/plan primitive, versioned public API
  with per-key quotas, clinician dashboard, dietary-constraint filtering
  across search/recipes/meal-planning/the optimiser.
- **Explicitly not built yet**: billing integration (the entitlement
  system has a `NoOpBillingProvider` stub waiting on a real processor),
  audit logging, and multi-tenancy — both named in
  `docs/enterprise-capabilities.md` as the two prerequisites that block
  enterprise features, in that order, not built in parallel.

This candour is deliberate: an investor who later checks the codebase
should find the pitch matched reality.

## 9:00–10:00 — Close

Return to the dashboard. Close on the thesis one more time: this is the
only nutrition product where every number is either sourced or explicitly
flagged as an estimate — that's the product, the moat, and the reason the
free tier can stay this generous without cannibalising the paid one.
