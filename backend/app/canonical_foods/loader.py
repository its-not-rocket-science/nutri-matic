"""Loads the reviewed canonical-foods CSV into the canonical_* tables.

    python -m app.canonical_foods validate          # file only, no database
    python -m app.canonical_foods load --dry-run    # full checks, then roll back
    python -m app.canonical_foods load

In production the load runs from an Alembic data migration (owner's
decision on plan Q5), so it is rehearsed against the restored production
dump before the deploy approval gate. The CLI is for local use.

Checks, all before anything is written (plan 3.4):
  * the file passes csv_schema.parse (closed vocabularies, reviewer and
    date on every row, no conflicting aliases, ...);
  * every anchor_fdc_id exists, is a Foundation or SR Legacy row, has the
    exact name the file's anchor_fdc_name says (so the id a reviewer
    signed off is the row they read), reports energy (plan 1.3: many
    Foundation rows do not), and its classified preparation state equals
    the canonical's (the plan 3.1 invariant). A branded or derived default
    needs PR 5.

The load is one transaction and all-or-nothing. It is idempotent and
replaces canonical rows by key: a key's fields, aliases and anchor are
rewritten from the file; a key no longer in the file is marked `retired`
(its aliases are removed so search stops offering it), never deleted. It
reads `foods` and never writes it, so the FDC catalogue checksum does not
change. It never reads or writes any phytate table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..food_preparation import classify_preparation
from ..fdc_staples import STAPLES
from ..models import CanonicalAlias, CanonicalFood, CanonicalMember, Food, FoodNutrient
from .csv_schema import CSV_PATH, CanonicalCsvError, CanonicalRow

_GENERIC_TYPES = ("foundation_food", "sr_legacy_food")


@dataclass
class LoadResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    def summary(self) -> str:
        if self.skipped_reason:
            return f"canonical foods: skipped ({self.skipped_reason})"
        return (
            f"canonical foods: {len(self.created)} created, {len(self.updated)} updated, "
            f"{len(self.unchanged)} unchanged, {len(self.retired)} retired"
        )


def catalogue_is_empty(db: Session) -> bool:
    """True when no FDC row has been ingested (CI, a fresh dev database).
    There is nothing to anchor to, so a load is skipped rather than failed."""
    return db.execute(select(Food.id).where(Food.fdc_id.isnot(None)).limit(1)).first() is None


def resolve_anchors(db: Session, canonicals: dict[str, CanonicalRow]) -> dict[str, Food]:
    """The anchor Food for every canonical key. Raises CanonicalCsvError
    listing every anchor that is missing, branded or in the wrong state."""
    fdc_ids = {c.anchor_fdc_id for c in canonicals.values()}
    foods = {f.fdc_id: f for f in db.execute(select(Food).where(Food.fdc_id.in_(fdc_ids))).scalars()}
    with_energy = set(db.execute(
        select(FoodNutrient.food_id).where(
            FoodNutrient.food_id.in_([f.id for f in foods.values()]),
            FoodNutrient.nutrient_key == "energy",
            FoodNutrient.amount_per_100g.isnot(None),
        )
    ).scalars())
    problems, anchors = [], {}
    for key, canonical in sorted(canonicals.items()):
        food = foods.get(canonical.anchor_fdc_id)
        if food is None:
            hint = (" (a protein-free SR staple: run python -m app.fdc_staples load first)"
                    if canonical.anchor_fdc_id in STAPLES else "")
            problems.append(f"{key}: anchor fdc_id {canonical.anchor_fdc_id} is not in the catalogue{hint}")
            continue
        if food.data_type not in _GENERIC_TYPES:
            problems.append(
                f"{key}: anchor fdc_id {canonical.anchor_fdc_id} ({food.name!r}) is {food.data_type}, "
                "not Foundation or SR Legacy"
            )
            continue
        if food.name != canonical.anchor_fdc_name:
            problems.append(
                f"{key}: anchor fdc_id {canonical.anchor_fdc_id} is {food.name!r} in the catalogue, "
                f"but the file says {canonical.anchor_fdc_name!r}"
            )
            continue
        if food.id not in with_energy:
            problems.append(f"{key}: anchor {food.name!r} reports no energy value")
            continue
        state = classify_preparation(food.name, food.data_type)
        if state != canonical.preparation_state:
            problems.append(
                f"{key}: anchor {food.name!r} is classified {state!r}, not {canonical.preparation_state!r}"
            )
            continue
        anchors[key] = food
    if problems:
        raise CanonicalCsvError(problems)
    return anchors


def _desired_aliases(canonical: CanonicalRow) -> set[tuple]:
    return {(a.alias, a.locale, a.relationship, a.note) for a in canonical.aliases}


def apply(db: Session, canonicals: dict[str, CanonicalRow], *, source_name: str = CSV_PATH.name) -> LoadResult:
    """Validates anchors, then writes. The caller owns the transaction:
    commit to keep the result, roll back for a dry run. Raises
    CanonicalCsvError, before writing anything, if any check fails."""
    result = LoadResult()
    anchors = resolve_anchors(db, canonicals)
    now = datetime.now(timezone.utc)
    existing = {c.key: c for c in db.execute(select(CanonicalFood)).scalars()}

    for key, canonical in sorted(canonicals.items()):
        anchor = anchors[key]
        fields = {
            "concept": canonical.concept,
            "preparation_state": canonical.preparation_state,
            "display_name_en_gb": canonical.display_name_en_gb,
            "display_name_en_us": canonical.display_name_en_us,
            "default_food_id": anchor.id,
            "status": "active",
            "review_ref": f"{source_name}#{key}",
        }
        row = existing.get(key)
        if row is None:
            row = CanonicalFood(key=key, created_at=now, updated_at=now, **fields)
            db.add(row)
            db.flush()
            result.created.append(key)
            changed = True
        else:
            changed = any(getattr(row, name) != value for name, value in fields.items())
            current_aliases = {
                (a.alias, a.locale, a.relationship, a.display_note)
                for a in db.execute(select(CanonicalAlias).where(CanonicalAlias.canonical_food_id == row.id)).scalars()
            }
            current_anchor = db.execute(
                select(CanonicalMember.food_id).where(
                    CanonicalMember.canonical_food_id == row.id, CanonicalMember.role == "anchor"
                )
            ).scalars().all()
            changed = changed or current_aliases != _desired_aliases(canonical) or current_anchor != [anchor.id]
            if not changed:
                result.unchanged.append(key)
                continue
            for name, value in fields.items():
                setattr(row, name, value)
            row.updated_at = now
            result.updated.append(key)

        db.execute(delete(CanonicalAlias).where(CanonicalAlias.canonical_food_id == row.id))
        db.execute(delete(CanonicalMember).where(
            CanonicalMember.canonical_food_id == row.id, CanonicalMember.role == "anchor"
        ))
        db.add_all(
            CanonicalAlias(canonical_food_id=row.id, alias=a.alias, locale=a.locale,
                           relationship=a.relationship, display_note=a.note)
            for a in canonical.aliases
        )
        db.add(CanonicalMember(canonical_food_id=row.id, food_id=anchor.id, match_method="reviewed",
                               confidence="high", role="anchor"))

    for key, row in sorted(existing.items()):
        if key not in canonicals and row.status != "retired":
            row.status = "retired"
            row.updated_at = now
            db.execute(delete(CanonicalAlias).where(CanonicalAlias.canonical_food_id == row.id))
            result.retired.append(key)

    db.flush()
    return result


def load(db: Session, canonicals: dict[str, CanonicalRow], *, skip_if_catalogue_empty: bool = True) -> LoadResult:
    """apply(), but skipped on a database with no FDC catalogue."""
    if skip_if_catalogue_empty and catalogue_is_empty(db):
        return LoadResult(skipped_reason="no FDC catalogue rows to anchor to")
    return apply(db, canonicals)
