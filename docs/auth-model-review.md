# Auth model review

Revisits the access-token-only, 7-day JWT design (`backend/app/auth.py`)
now that commercial/multi-tenant use is on the table (Phase 3+ of
`nutri-matic-claude-prompts.txt`). Decision recorded here so it's a
documented tradeoff, not an unreviewed leftover from the personal-use era.

## What changed as a result of this review

- **Token lifetime cut from 7 days to 24 hours** (`JWT_EXPIRY` in
  `backend/app/auth.py`). This is the one concrete change from this
  review — see "Decision" below for why.
- **Frontend now handles a 401 by logging out and redirecting to
  `/login`** (`frontend/src/lib/api.ts`), rather than surfacing a raw
  "Invalid or expired token" error. This was needed *because* of the
  shorter expiry — at 7 days a user essentially never hit it organically;
  at 24 hours, an open tab left overnight will.

## What did NOT change, and why

**No refresh-token rotation.** The standard reason to want refresh tokens
is revocability — being able to end a session before its token naturally
expires (ban a user, respond to a stolen token, force logout on password
change). Refresh-token rotation is one way to get that, but it's not the
only way, and it's the most complex one: rotating refresh tokens, storing
them, detecting reuse (a stolen-and-replayed old refresh token has to be
treated as a signal the whole token family is compromised), plus a new
endpoint and frontend refresh-scheduling logic.

The key thing that makes this less urgent than it first looks: **this
app's JWT only ever encodes identity** (`sub: user_id`), never
tier/permissions/entitlements. Phase 3's entitlement layer
(`docs/` — see the feature-flags work) checks a user's tier against live
database state on every request, not against anything embedded in the
token. That means a stale-but-unexpired token doesn't grant stale
*privileges* — a downgraded or banned user's access changes immediately
regardless of how long their token has left to live. The remaining
exposure from a long-lived token is narrower than "this user has stale
elevated access forever until the token expires": it's "a stolen token
lets someone act as this user, for up to the token's remaining lifetime."
That's still worth minimizing, which is what the lifetime cut addresses —
just with a one-line change instead of a new subsystem.

**No per-tier session limits** (e.g. "Free tier: 1 concurrent device").
Nothing about the current architecture prevents adding this later, but
building it now would be speculative — there's no tier system live yet
(that's Phase 3.1's job), and "how many concurrent sessions should a Pro
user get" is a product decision that should follow from actual tier
definitions (Phase 4.1), not precede them. Revisit alongside Phase 4.1.

## Decision

Keep access-token-only. Shorten the token lifetime (done: 7 days → 24h)
as the cheap, immediate mitigation for the lack of revocation. Do not
build refresh-token rotation now.

**Revisit refresh tokens when either of these becomes true, not before:**

1. A genuinely long-lived client shows up that needs to avoid re-prompting
   login on every session — e.g. a mobile app, or telemetry showing the
   24h cutoff meaningfully hurts retention/usability. (If that happens,
   the fix might just be "extend to 72h" before jumping to refresh
   tokens — try the cheap lever again first.)
2. An enterprise customer's security requirements (Phase 4.3 — audit
   logging, session control) explicitly need real-time session
   revocation, not just a bounded exposure window.

**Cheap, deferred but recommended follow-up** (not implemented in this
review — a schema change, better scoped to when there's a real "revoke
this user's access" flow to build it against): a `sessions_invalid_after`
timestamp column on `User`, checked in `get_current_user` alongside the
JWT's own expiry, bumped on password change or an explicit "log out
everywhere" action. This gives real, immediate revocation without any
refresh-token infrastructure — it's a much smaller change than rotation,
and worth building before refresh tokens if revocation turns out to be
the actual need (rather than long-lived sessions).
