# Product-led growth review

Phase 4.4 of `nutri-matic-claude-prompts.txt`: review Phases 2-4's output,
identify which premium capabilities deliver genuine additional value
versus which would only be premium because of an artificial limitation.
Gate only the former; flag the rest for separate review rather than
gating them anyway.

## Gated in this pass — genuine value case

### Diary snapshot count (Phase 2.3) — Free: 5, Pro+: unlimited
Each snapshot persists a full computed `DiarySummaryOut` as a JSON row
(`DiarySnapshot.summary_json`) — a genuine, ongoing storage cost that
scales with usage, unlike almost everything else in this app (which is
computed on demand and stored nowhere). This is the same shape of limit
real storage/photo products use (a free tier with a real, disclosed cap
tied to actual infrastructure cost), not a lock on functionality that
costs nothing extra to provide. Implemented in
`routers/diary.py::create_snapshot` (`FREE_TIER_SNAPSHOT_LIMIT`, defined
in `entitlements.py`), tested in
`test_diary_snapshot.py::test_free_tier_snapshot_limit_enforced`.

### Public API request quota, by plan (Phase 3.2)
Previously a flat 1,000 requests/30 days for every key regardless of
plan — meaning the "quota" primitive existed but wasn't actually
differentiated by tier, which made it a limitation with no product logic
behind the specific number. Changed to `entitlements.API_QUOTA_BY_PLAN`
(Free: 100, Trial: 500, Pro: 5,000, Professional: 20,000, Enterprise:
100,000), set at key-creation time. Real basis: API request volume is a
direct, metered infrastructure cost (the whole reason `ApiKey.quota_limit`
existed in the first place) — differentiating it by plan is the standard,
non-artificial way API products monetize, and doesn't touch the
underlying computations (still the same free `scoring.py`/
`bioavailability.py`/`complement.py` logic for every tier).

### Clinician roster size (Phase 4.2) — already gated when built
`FREE_TIER_CLIENT_LIMIT = 3` in `routers/clinician.py`, unlimited for
Professional/Enterprise. Not new to this review — flagged here for
completeness since it's a real example of the same "scale is the premium
axis, not any specific view" reasoning applied to gating. Reasoning was
recorded at the time in `docs/professional-dashboard-scope.md`.

## Explicitly NOT gated — flagged for separate review, not implemented

### "Advanced optimisation" (meal optimiser, Phase 2.2)
There is no "basic" vs "advanced" version of the optimiser in what's
built — `suggest_meal_optimizations()` is one algorithm, used identically
by every caller. Gating some arbitrary subset of it (e.g. hiding the
budget constraint, or capping suggestion count) would be gating a feature
that costs nothing extra to serve, purely to create upgrade pressure —
exactly what this phase's ground rules say not to do. **Recommendation**:
don't gate anything here unless/until a genuinely more expensive
"advanced" mode is built (e.g. Phase 4.3's at-scale batch optimisation,
which does have a real cost basis — see `docs/enterprise-capabilities.md`).

### Historical analytics / diet trends date range (pre-existing feature)
Trends (`GET /diary/trends`) accepts any date range today, for free.
A retention-window cap (e.g. "free tier: last 3 months only") is a
pattern real analytics products use, but two things make it a weak case
here rather than a clear one: (1) the marginal cost of a longer-range
trends query is small and roughly constant (it's the same aggregation
query over more rows, not a new persisted artifact like a snapshot), so
the infrastructure-cost basis is much thinner than the snapshot case
above; (2) trends has been unrestricted since it shipped — retroactively
capping something users already rely on breaks trust in a way a
*new* feature's cap doesn't. **Recommendation**: don't gate. If a real
cost problem shows up (e.g. very old accounts with years of dense diary
data making trends queries slow), address it with query optimisation
first, and only consider a cap as a last resort with a clear
grandfathering plan for existing users.

### Clinician reporting (branded/printable PDF reports)
Not built yet (see `docs/professional-dashboard-scope.md`'s "not built in
this pass" list) — nothing to gate. When built, `docs/tiered-commercial-model.md`
already scopes it as part of the Professional tier's genuinely-new
product surface (multi-client views), which is a reasonable place for it
to land — but that's a decision for when it's actually implemented, not
speculative gating now.

### Supermarket/enterprise integrations (Phase 4.3)
Design-only (`docs/enterprise-capabilities.md`) — nothing built, nothing
to gate.

## Principle applied throughout

The dividing line used consistently above: **gate scale/volume against a
real, metered cost (storage rows, API requests, client-roster size);
never gate a capability that costs the same to serve one user or a
thousand.** The transparency/provenance layer was never a candidate for
gating (see `docs/tiered-commercial-model.md`'s "stays free forever"
list) — everything reviewed here was already outside that layer.
