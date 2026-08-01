# Professional dashboard (clinician mode) — scope

Phase 4.2 of `nutri-matic-claude-prompts.txt`. Documents what was actually
built (`backend/app/routers/clinician.py`) and, per the prompt's own
question, which parts are Professional-plan-only versus available to any
registered account.

## Important disclosed limitation

**This app has no license-verification mechanism.** "Clinician" here
means "any registered user who invites another user and gets accepted,"
not a verified dietitian/nutritionist credential. Nothing in this feature
checks a professional registration number or license. This is disclosed
explicitly here (and should be disclosed in-product) rather than implied
— a feature named "clinician mode" that doesn't verify clinicians is a
real trust gap for a health-adjacent product, and pretending otherwise
would be dishonest. Real license verification (e.g. checking against a
professional register) is a separate, unscoped feature.

## What was built

- **Consent-gated client access** (`ClinicianClientLink`): a clinician
  invites a client by email; access only becomes active once the client
  explicitly accepts. Either party can revoke at any time. This is
  deliberately *not* the direct-grant model `RecipeShare` uses elsewhere
  in this codebase — sharing a recipe you own is low-stakes; granting
  access to someone else's private health data is not, so it requires
  affirmative consent rather than a unilateral grant.
- **Invite by email, even without an account yet**: if `client_email`
  doesn't match a registered user, `POST /invites` sends that address a
  join-link email instead of rejecting the request — via
  `app/email_sender.py` (plain SMTP, disabled with a `503` unless
  `SMTP_HOST` is configured; see `DEPLOYMENT.md`). The clinician's own
  wording is sent verbatim (a default is offered, not enforced). This
  never skips the consent step above: the link's target still has to
  explicitly accept from their own account once they register — see
  `ClinicianClientLink`'s own docstring. Rate-limited per-clinician and
  globally (`app/invite_protection.py`) — caught by PR review: without
  this, any registered account could use the relay as an open spam/
  phishing channel. A clinician can also cancel a still-unresolved
  invite (`POST /invites/{id}/cancel`) — otherwise a typoed or
  changed-mind invite's join link would stay valid indefinitely, since
  nobody has an account yet to decline it from the client side.
- **Micronutrient gaps, protein quality, and bioavailability at a
  glance** (`GET /clients/{id}/summary`): reuses the exact same
  `_compute_day_summary()` the client's own diary page calls — not a
  separate, simplified computation. What a clinician sees for a client's
  day is the same real, live-computed data the client sees for
  themselves, with the same measured/estimated labelling.
- **Longitudinal comparisons** (`GET /clients/{id}/trends`): same
  reuse pattern, against the newly-extracted `_compute_trends()`.
- **Clinician notes**: private, clinician-only text notes per client.
  No endpoint exposes a clinician's notes to the client they're about —
  verified by `test_notes_private_to_clinician` in
  `backend/tests/test_clinician.py`.
- **Client roster**, capped at 3 active clients for accounts without a
  Professional/Enterprise plan (`FREE_TIER_CLIENT_LIMIT` in
  `clinician.py`) — enforced at invite time, not accept time, so a free
  account can't stack unlimited pending invites to work around the cap.

## What was not built in this pass

- **Branded/printable PDF reports.** The existing print/CSV export
  pattern (`PrintButton`, `print.css`) could be extended to a
  `/clinician/clients/{id}` detail page the same way every other
  printable page in this app works — genuinely low effort given the
  precedent already exists, but not wired up here; the frontend build in
  this pass covers the interactive dashboard (invite/accept/roster/
  summary/notes), not a dedicated print layout.
- **"Nutrient interactions"** beyond what `bioavailability.py` already
  computes (iron/vitamin-C, Ca:P ratio, sodium:potassium). The prompt
  names this as a capability but doesn't specify which interactions
  beyond what's already modelled — rather than invent new interaction
  science not backed by a citation (this app's consistent rule), the
  clinician summary surfaces the same real bioavailability/food-chemistry
  data already computed elsewhere, not a new "interactions" analysis.
- **License verification** (see disclosed limitation above).

## Free vs Professional-plan-only

| Capability | Free (any account) | Professional/Enterprise |
|---|---|---|
| Invite/accept/decline/revoke clients | Yes | Yes |
| Client roster size | Up to 3 active | Unlimited |
| Per-client day summary & trends | Yes, for linked clients | Yes |
| Clinician notes | Yes, for linked clients | Yes |

The rationale for capping roster size rather than gating any specific
view: everything a clinician can see for one client is real, already-
built functionality (Phase 2's work) — there's no honest basis to call
any single *view* premium. Scale (managing more than a handful of
clients) is the genuine professional-vs-hobbyist line, so that's what's
metered, matching `docs/tiered-commercial-model.md`'s Professional-tier
rationale ("new product surface," here specifically roster scale).
