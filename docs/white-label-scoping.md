# White-label configuration scoping

Phase 3.4 of `nutri-matic-claude-prompts.txt`: what would changing
branding, scoring weights, and nutrient targets per organisation actually
require, given `models.py`'s current single-tenant assumptions? Scoping
document only, per the prompt's own instruction — implementation is
deferred until Phase 4's enterprise work (`docs/enterprise-capabilities.md`)
defines real requirements to build against, not assumed ones.

## The current single-tenant assumption, concretely

Every table in `models.py` that holds user-generated data
(`DiaryEntry`, `Recipe`, `MealPlanEntry`, `FoodPrice`, `ApiKey`, etc.) has
a `user_id` foreign key straight to `User` — there is no `Organization` or
`Tenant` table, and no `organization_id` anywhere. `Food`, `FoodNutrient`,
`RecipeIngredient`'s reference data, `nutrients.py`'s DRV matrix, and
`reference_patterns.py`'s amino acid scoring patterns are all **global
constants or global tables**, shared identically by every user. There is
currently exactly one branding surface, exactly one DRV matrix, exactly
one scoring pattern set, for the whole deployment.

## Three different things "white-label" could mean here

They have very different costs, and the prompt bundles them together as
if they're one feature. They aren't:

### 1. Branding (name, logo, colour)

**Cheapest, and does NOT require multi-tenancy** — if "white-label" means
"one organisation runs their own deployment with their own branding" (the
common pattern for smaller B2B products: one Docker image, one
customer, redeployed per customer with different config), this is just
making today's hardcoded strings configurable:

- `app = FastAPI(title="Nutri-Matic API", description=...)` (`main.py`)
  and the frontend's `<title>`/meta description (`+layout.svelte`) would
  read from environment variables (`BRAND_NAME`, `BRAND_TAGLINE`) instead
  of literals.
- Logo/favicon and theme colour (`frontend/static/manifest.webmanifest`,
  `frontend/src/lib/assets/favicon.svg`) would need to become
  build-time-swappable assets, not database config — there's no per-request
  branding decision to make if it's one deployment per brand.
- **Effort: small.** No schema change, no migration, no multi-tenancy.
  Not implemented in this pass because there is no second brand asking
  for it yet — see Decision below.

If instead "white-label" means "one deployment serves many organisations,
each seeing their own branding" (true multi-tenant SaaS), that's a
different and much larger feature: it needs an `Organization` table,
`organization_id` added to `User` (and a decision about whether existing
data — foods, recipes — stays global/shared or becomes org-scoped), and
every request needs to resolve "which org is this" (subdomain routing,
a header, or an org-scoped login) before rendering anything. This is the
expensive path, and nothing in the current architecture supports it
without that foundational work first.

### 2. Nutrient targets (DRV matrix)

**Also cheap for the single-deployment-per-brand model, for a different
reason**: `nutrients.py`'s `NUTRIENTS` dict and `resolve_drv()` are
already parameterised by profile (sex, pregnancy, lactation) — they are
*not* parameterised by organisation, but making the whole matrix
loadable from a config file/environment instead of a hardcoded Python
dict would let one deployment use different reference values (e.g. an
occupational-health customer wanting their own internal targets instead
of UK RNI) without touching multi-tenancy at all — it's a data-loading
change, not a schema change. **Real risk to flag**: this is exactly the
"transparency and scientific integrity" surface Phase 4.1 explicitly says
must stay free/uncompromised — swappable DRVs must never be used to make
a paying customer's numbers look better than the UK RNI/EFSA-sourced
defaults without equally rigorous sourcing and equally honest confidence
labelling. Any implementation of this must carry the same `drv_source`/
`drv_confidence` discipline `nutrients.py` already has, not a shortcut
around it.

For true per-organisation targets within one multi-tenant deployment
(different orgs, same deployment, different DRVs), this needs the same
`organization_id` foundation as branding's multi-tenant case above, plus
`resolve_drv()` gaining an org parameter and an org-scoped override table.

### 3. Scoring weights (DIAAS/PDCAAS reference patterns, digestibility
   coefficients)

**Not recommended at all, regardless of tenancy model.**
`reference_patterns.py`'s amino acid patterns are FAO/WHO published
science (FAO 2013, Table 4.1), and `digestibility_reference.py`'s
coefficients are traced to specific cited studies. These aren't "brand
configuration" — they're the scientific methodology itself. Letting an
organisation customise them would mean two customers' DIAAS scores for
the *same food* could legitimately disagree, with no way for a user to
know which figure (if either) reflects the actual FAO/WHO standard. This
directly conflicts with this app's stated differentiator (computed,
citable nutrition science, not a black box) and with the ground rule that
the transparency/provenance layer must never be weakened for a commercial
feature. If a customer's genuine ask is "we want to add our own
supplementary targets alongside the standard ones" (e.g. an internal
protein-quality minimum on top of DIAAS, not instead of it), that's an
additive feature, not a scoring-weights override, and should be scoped
separately if it comes up for real.

## Decision

**Scoping only — nothing implemented in this pass.** Branding
(single-deployment model) and DRV-matrix data-loading are both genuinely
cheap and don't require multi-tenancy, but building either now would be
configuration surface with no real customer to validate it against —
exactly the speculative-scaffolding this phase's ground rules warn
against. Revisit branding/DRV configurability once Phase 4.3's enterprise
work identifies a real first customer with real requirements; build
against those requirements, not a guess. Multi-tenant (one deployment,
many orgs) white-labelling is a substantially larger foundational change
and should not be started without a specific, confirmed need for it.
