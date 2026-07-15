# Engine/app separation assessment

Phase 3.3 of `nutri-matic-claude-prompts.txt`: could `scoring.py`,
`optimizer.py`, `bioavailability.py`, `complement.py`, and
`methodology.py` be packaged as an installable library independent of the
web app? Assessed by reading each module's actual imports (not guessing)
— see the table below. Conclusion: **defer extraction**. Two of the five
are genuinely standalone already; the other two are entangled with the
ORM/database in a way that's fixable, but the fix is a real refactor with
no confirmed consumer waiting for the result — exactly the "scaffolding
for unconfirmed demand" this phase's own ground rules say to avoid.

## What each module actually imports

| Module | Internal imports | SQLAlchemy `Session`? | ORM models? | FastAPI/schemas? |
|---|---|---|---|---|
| `methodology.py` | none | No | No | No |
| `bioavailability.py` | none | No | No | No |
| `scoring.py` | `reference_patterns.py` (pure data) | No | No | No |
| `complement.py` | `aggregation.py`, `models.Food`, `scoring.py` | **Yes** — `suggest_complements(..., db: Session)` | **Yes** | No |
| `optimizer.py` | `aggregation.py`, `models.{Food,FoodNutrient,FoodPrice}` | **Yes** — `suggest_meal_optimizations(..., db: Session)` | **Yes** | No |

(`reference_patterns.py`, which `scoring.py` depends on, was checked too:
zero internal imports, pure data — no separate row needed above.)

None of the five import `schemas.py` or anything from `fastapi` directly —
the web-framework layer is cleanly kept in `routers/`, one level up from
all of this. That part of the architecture is already separation-ready.

## Genuinely separable today, no changes needed

**`methodology.py`, `bioavailability.py`, `scoring.py`** (plus
`reference_patterns.py`, which `scoring.py` needs). These operate
entirely on plain Python values — floats, dicts, dataclasses — passed in
by the caller. `bioavailability.py`'s `split_food_iron()` and
`estimate_meal_iron_absorption()` take a food *name* (string) and
already-computed amounts, never a `Food` row. `scoring.py`'s
`compute_diaas`/`compute_pdcaas` take amino-acid dicts and a digestibility
value/dict, never touch the database. These three files (four counting
`reference_patterns.py`) could be copied into a standalone package
verbatim today and would import and run with zero changes.

## Genuinely entangled: `complement.py` and `optimizer.py`

Both take a live `db: Session` and run their own queries — this isn't
incidental, it's their core mechanism:

- `complement.py::suggest_complements()` queries `Food` directly
  (`db.query(Food).filter(Food.id != food.id, digestibility_column.isnot(None))`)
  to build its candidate shortlist before simulating pairings.
- `optimizer.py::suggest_meal_optimizations()` does the same for
  same-family swap candidates (`db.query(Food).filter(Food.name.ilike(...))`)
  and lazy-loads each candidate's `FoodNutrient` rows on demand.

Both also depend on `aggregation.py` (`WeightedFood`,
`aggregate_amino_acids`/`aggregate_nutrients`), which is itself ORM-bound
— `expand_entries_to_weighted_foods()` takes a live `Session` to expand a
recipe entry into its ingredients on demand.

This is a real architectural choice, not an accident: candidate search
*needs* to query the whole food database (which could be hundreds of
thousands of rows from USDA FDC), so "pass in the candidate pool as a
plain argument" would just move the query to the caller — every caller
would have to know how to do that query correctly (same-family name
matching, digestibility-not-null filtering), which is exactly the kind of
duplicated domain logic this codebase's own architecture review
(`nutri-matic-claude-prompts.txt`'s earlier prompt set, Phase 0) already
flagged as a problem to avoid.

## What extraction would actually require (not attempted)

To make `complement.py`/`optimizer.py` engine-library-clean, the DB-query
parts would need to split out from the pure-simulation parts:

1. A repository-style interface (e.g. `CandidateSource` protocol with a
   `find_same_family(name) -> list[FoodLike]` method) that the web app
   implements with real SQLAlchemy queries, and a library consumer could
   implement however fits their own data layer.
2. `FoodLike`/`WeightedFoodLike` structural types (`Protocol`s, matching
   `aggregation.py`'s existing `QuantifiedEntry` Protocol pattern) instead
   of concrete `Food`/`FoodNutrient` ORM classes, so the simulation math
   doesn't care whether its input came from SQLAlchemy or an in-memory
   list.
3. `aggregation.py`'s `expand_entries_to_weighted_foods()` would need the
   same treatment — it's the shared root of the entanglement, used by
   `complement.py`, `optimizer.py`, and every router.

This is a real, doable refactor — `aggregation.py` already has one
Protocol (`QuantifiedEntry`) showing the pattern works in this codebase —
but it touches five-plus call sites across `routers/` for no behavior
change, purely to enable a use case (installable standalone library) that
nobody has asked for yet.

## Decision

**Defer.** Package nothing as a separate library right now. If real
demand shows up (e.g. Phase 3.2's public API growing a client SDK that
wants the scoring logic without a network round-trip, or an actual
external team asking to embed this), start with the three
already-separable files — `methodology.py`, `bioavailability.py`,
`scoring.py` — since those need zero changes and would deliver real value
immediately. Only take on the `complement.py`/`optimizer.py`/
`aggregation.py` refactor once there's a specific consumer whose
requirements can validate the abstraction (a `CandidateSource` protocol
designed against zero real callers is exactly the kind of speculative
scaffolding this phase's ground rules warn against).
