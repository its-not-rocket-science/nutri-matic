"""Centralises the one structural rule every `DiaryEntry`/`MealPlanEntry`
mutation must follow — operational-hardening prompt 4.

`models.DiaryEntry.version`/`models.MealPlanEntry.version` are mapped
with `version_id_col`, so SQLAlchemy itself appends `WHERE version =
<loaded value>` to every UPDATE it emits for these rows and raises
`StaleDataError` when zero rows match (another write already changed
the row and bumped its version first). This module is the one place
that translates that into this app's own `EntryConflict` — callers
(currently just `routers/recommendations.py`'s `apply_substitution`,
but any future endpoint that mutates one of these rows) catch
`EntryConflict`, never SQLAlchemy's own exception type directly, so the
underlying mechanism stays swappable in one place if it ever needs to
change."""

from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError


class EntryConflict(Exception):
    """Raised by `commit_entry_mutation` when the optimistic-concurrency
    race was lost — some other write already changed the row since this
    session loaded it. Callers should respond 409."""


def commit_entry_mutation(db: Session) -> None:
    """Call this instead of a bare `db.commit()` after mutating a
    `DiaryEntry`/`MealPlanEntry` ORM object's fields. Identical to
    `db.commit()` on success; on a lost optimistic-concurrency race,
    rolls back (leaving the session usable and the database
    untouched — the failed UPDATE matched zero rows, so there was
    nothing to roll back at the database level, but the session itself
    needs resetting before it can be used again) and raises
    `EntryConflict` instead of leaking SQLAlchemy's own `StaleDataError`
    to callers outside this module."""
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise EntryConflict from None
