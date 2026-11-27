"""Barcode (GTIN) lookup with width-equivalence.

FDC publishes GTINs in whatever width the manufacturer submitted: UPC-A (12
digits), EAN-13, GTIN-14, GTIN-8 and odd widths, and `ingest_fdc.py` stores
them verbatim (docs/plans/canonical-foods-plan.md section 1.4). A phone
scanner reading an EAN-13 pack returns 13 digits, so the ~21k products
stored as 14 digits with a leading 0 never matched an exact comparison.

A GTIN is a number: left-padding with zeros does not change it (GS1 pads
every GTIN to 14 digits for comparison). So two all-digit codes are the
same product code when they are equal after stripping leading zeros. This
module looks a scanned or typed code up under every zero-padded width of
that number, up to GTIN-14, and picks one row deterministically
(`_collision_key`):

  1. the row stored exactly as given (so every lookup that hit before
     returns the same row as before);
  2. otherwise the equivalent stored with the least padding (shortest);
  3. then the newest fdc_id. The `gtin_upc` column is unique, so two
     equivalents always differ in width and this step cannot be reached
     today; it is kept so the rule stays total if that ever changes.

Codes that are not all digits are looked up exactly as before, with no
normalisation (they are not GTINs). Check digits are not validated: a
stored code with a wrong check digit is still the code on the pack.

Barcode lookup never consults name search or any canonical layer: an
exact barcode is always exact (plan 3.3).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Food

GTIN_MAX_WIDTH = 14


def equivalent_codes(code: str) -> list[str]:
    """Every stored form that denotes the same GTIN as `code`, the code
    itself first. Non-digit input, and all-digit input longer than
    GTIN-14, have only themselves."""
    if not code.isdigit() or not code.isascii() or len(code) > GTIN_MAX_WIDTH:
        return [code]
    core = code.lstrip("0") or "0"
    forms = [code]
    for width in range(len(core), GTIN_MAX_WIDTH + 1):
        padded = core.zfill(width)
        if padded not in forms:
            forms.append(padded)
    return forms


def _collision_key(code: str, food: Food) -> tuple:
    stored = food.gtin_upc or ""
    return (stored != code, len(stored), -(food.fdc_id or 0))


def find_food_by_barcode(db: Session, code: str) -> Food | None:
    """The food for a scanned/typed barcode, or None. See the module
    docstring for the equivalence and collision rules."""
    candidates = db.query(Food).filter(Food.gtin_upc.in_(equivalent_codes(code))).all()
    if not candidates:
        return None
    return min(candidates, key=lambda food: _collision_key(code, food))
