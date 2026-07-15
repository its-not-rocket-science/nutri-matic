# Live Mode vs Snapshot Mode

Formalises `methodology_version` (`backend/app/methodology.py`) into an
explicit, user-facing choice, per Prompt 2.3 of
`nutri-matic-claude-prompts.txt`. This is what makes the transparency
claims about methodology versioning auditable rather than aspirational —
previously the version stamp existed, but there was no way to actually
*compare* a past result against a current one, since every diary read
always recomputed live.

## The two modes

- **Live Mode** (`GET /api/diary?entry_date=...`, unchanged) — always
  recomputed from current code and current data. This has been, and
  remains, the only behavior of the plain diary-day endpoint.
- **Snapshot Mode** (`POST` then `GET /api/diary/snapshot?entry_date=...`)
  — a frozen copy of one day's full computed summary, taken explicitly by
  the user, immutable once taken. `GET` returns the exact JSON that was
  computed at snapshot time, plus the `drv_methodology_version` and
  `scoring_methodology_version` that were in effect then — so a caller can
  compare those against today's live values (exposed on every live
  response already) to know at a glance whether anything would compute
  differently now.

## Why snapshotting is explicit, not automatic

The obvious alternative — silently snapshot every day the moment it's
logged, or re-snapshot whenever methodology changes — was rejected for two
reasons:

1. **Retroactive coverage is impossible.** Diary entries logged before
   this feature existed have no historical methodology to snapshot against
   — there's nothing to freeze that wasn't already computed under
   whatever code existed on that day, and that code is gone. Claiming
   automatic full history coverage would overclaim what the feature
   actually does. Being explicit about "you must ask for a snapshot, and
   only snapshotted days have one" keeps the claim honest: what's
   snapshotted is real and reproducible; what isn't, just isn't — the API
   returns `None`, not a fabricated best-effort reconstruction.
2. **Automatic snapshotting on every log would silently double the
   write volume of the diary's hot path** (every `POST /api/diary` would
   need to also freeze a same-day summary) for a benefit most days don't
   need — most diary days are working data, not an audit record someone
   will want to compare later. Making it opt-in keeps the common path
   (log food, see live numbers) exactly as fast and simple as before, and
   spends the extra write only on days a user actually cares to preserve.

## Why snapshots are immutable

A mutable "snapshot" isn't a snapshot — it's just a cache that happens to
be stored differently. The whole point (per the source prompt: "reproduce
a diary day exactly as it was scored on the day it was logged") is that a
snapshot's value never changes after the fact. `POST /api/diary/snapshot`
therefore 409s if a snapshot already exists for that date rather than
silently overwriting it — including when the user logs more food for that
day afterward. Live Mode still reflects the new entries immediately;
Snapshot Mode deliberately doesn't, and the day's entry list length
diverging between the two modes is the expected, correct behavior (see
`test_create_snapshot_is_immutable` in
`backend/tests/test_diary_snapshot.py`).

## What's stored

`DiarySnapshot` (`backend/app/models.py`) stores the full
`DiarySummaryOut`-shaped payload as JSON, plus both methodology version
strings and a timestamp. This is a genuinely new table (`Base.metadata.create_all()`
picks it up automatically — no manual migration needed, consistent with
how every other new table in this codebase has been added), not a column
added to `diary_entries`, since a snapshot covers a whole day's *computed
result*, not any single entry.

## Not built (yet)

- **Frontend diffing UI** beyond showing both version strings — actually
  rendering a field-by-field "this changed" comparison between a snapshot
  and today's live numbers would be a real, separate feature once there's
  a first real methodology-version bump to diff against. Right now every
  snapshot's versions equal the current live versions (nothing has bumped
  since this shipped), so there's nothing to diff yet.
- **Bulk/scheduled snapshotting** (e.g. "auto-snapshot every day at
  midnight"). Deliberately not built per the "explicit, not automatic"
  reasoning above — if this turns out to be wanted, it should be a
  separate, clearly-labelled opt-in setting, not the default.
