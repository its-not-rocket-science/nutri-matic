"""Tests for app.ingest_phytate (prompts.txt Prompt 3 of the phytate/
mineral-bioavailability extension) — match-confidence assignment against
the stated rules, needs-review flagging (including a deliberately
ambiguous fixture case), and idempotent re-ingestion. Exercises the app's
real food-matching infrastructure (match_ingredient/search_foods_by_name)
against a small in-memory SQLite Food set, not a mocked matcher — the
point is testing these classification rules against how matching
actually behaves.

No real PhyFoodComp data here — invented fixtures only, so this suite
stays independent of the real (non-commercial-only licensed, see
docs/phytate-evidence-review.md §1) workbook. See
test_phyfoodcomp_adapter.py for real-workbook-shaped parsing tests."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.ingest_phytate import (
    RawObservation,
    _ambiguous_candidates,
    _prefer_infant_cereal_candidate,
    classify_match,
    ingest_rows,
    load_rows,
)
from app.models import CompoundObservation, Food
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes.food_matching import MatchCandidate, MatchResult, match_ingredient


def _food(**overrides):
    defaults = dict(protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    defaults.update(overrides)
    return Food(**defaults)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


DATASET_KWARGS = dict(
    dataset_name="PhyFoodComp1.0",
    dataset_citation="FAO/INFOODS/IZiNCG. Global food composition database for phytate, version 1.0.",
    dataset_version="1.0",
    access_date=date(2026, 8, 1),
)


def _row(**overrides):
    defaults = dict(
        food_description="Wheat flour, whole grain", value=250.0, unit="mg", basis="per_100g_edible_portion",
    )
    defaults.update(overrides)
    return RawObservation(**defaults)


# ---- load_rows -------------------------------------------------------

def test_load_rows_parses_required_and_optional_columns(tmp_path):
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(
        "food_description,value,unit,basis,preparation_state,compound_fraction,analytical_method,row_identifier\n"
        "Wheat flour,250,mg,per_100g_edible_portion,raw,IP6,HPLC,PFC-001\n"
        "Chickpeas,180,mg,per_100g_edible_portion,,,,\n",
        encoding="utf-8",
    )
    rows = load_rows(csv_path)
    assert len(rows) == 2
    assert rows[0] == RawObservation(
        food_description="Wheat flour", value=250.0, unit="mg", basis="per_100g_edible_portion",
        preparation_state="raw", compound_fraction="IP6", analytical_method="HPLC", row_identifier="PFC-001",
    )
    assert rows[1].preparation_state is None
    assert rows[1].compound_fraction is None
    assert rows[1].row_identifier is None


# ---- classify_match ----------------------------------------------------

def test_classify_match_no_candidate_is_needs_review(session):
    match = match_ingredient(session, "Nonexistent Made Up Food Xyz")
    relationship, rationale = classify_match(
        match, "Nonexistent Made Up Food Xyz", None, "per_100g_edible_portion",
    )
    assert relationship == "needs_review"
    assert "no FDC candidate" in rationale


def test_classify_match_low_confidence_branded_fuzzy_match_is_needs_review(session):
    # brand-prefixed, like real branded foods (see ingest_fdc.py), so this
    # doesn't also satisfy the canonical-lookup prefix match and skip the
    # fuzzy tier entirely.
    session.add(_food(name="XyzCo Some Distant Fuzzy Branded Product", data_type="branded_food"))
    session.commit()
    match = match_ingredient(session, "Some Distant Fuzzy Branded Product")
    assert match.method == "fuzzy"
    relationship, rationale = classify_match(
        match, "Some Distant Fuzzy Branded Product", None, "per_100g_edible_portion",
    )
    assert relationship == "needs_review"
    assert "confidence" in rationale


def test_classify_match_prep_state_and_edible_basis_is_regional_equivalent(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, rationale = classify_match(
        match, "Wheat flour, whole grain", "raw", "per_100g_edible_portion",
    )
    assert relationship == "regional_equivalent"
    assert "raw" in rationale


def test_classify_match_prep_state_substring_does_not_false_positive():
    """Regression: 'raw' must not match inside 'straw' -- the prep-state
    check requires a whole-word match, not a raw substring search (a
    candidate named 'Straw mushrooms, canned' must not be treated as
    prep-state-confirmed for a source description stating 'raw')."""
    match = MatchResult(
        food=_food(name="Straw mushrooms, canned"),
        method="fuzzy",
        confidence=0.7,
        candidates=[MatchCandidate(food_id=1, name="Straw mushrooms, canned", score=0.9)],
    )
    relationship, _ = classify_match(match, "Mushrooms", "raw", "per_100g_edible_portion")
    assert relationship != "regional_equivalent"


def test_classify_match_no_prep_state_is_close_analogue_not_exact(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, _ = classify_match(match, "Wheat flour, whole grain", None, "per_100g_edible_portion")
    assert relationship == "close_analogue"


def test_classify_match_dry_matter_basis_never_reaches_regional_equivalent(session):
    """Even with a matching preparation state, a dry-matter original basis
    (not yet normalised to edible portion) must not be treated as
    confirmed-aligned — see Prompt 2's original_basis field."""
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, _ = classify_match(match, "Wheat flour, whole grain", "raw", "per_100g_dry_matter")
    assert relationship != "regional_equivalent"


@pytest.mark.parametrize("preparation_state,basis", [
    (None, "per_100g_edible_portion"),
    ("raw", "per_100g_edible_portion"),
    ("raw", "per_100g_dry_matter"),
    (None, "per_100g_dry_matter"),
])
def test_classify_match_never_returns_exact(session, preparation_state, basis):
    """Automated matching must never assign "exact" — reserved for a
    human-verified mapping this script has no way to produce on its own."""
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, _ = classify_match(match, "Wheat flour, whole grain", preparation_state, basis)
    assert relationship != "exact"


def test_classify_match_ambiguous_candidates_is_needs_review(session):
    """The deliberately-ambiguous fixture case: two foods differing only
    by a detail the description doesn't specify, similarly matching the
    query — must be flagged for a human, not silently resolved to
    whichever the matcher happens to rank first."""
    session.add(_food(name="Beans, kidney, red, mature seeds, raw"))
    session.add(_food(name="Beans, kidney, white, mature seeds, raw"))
    session.commit()
    match = match_ingredient(session, "Beans, kidney")
    relationship, rationale = classify_match(match, "Beans, kidney", None, "per_100g_edible_portion")
    assert relationship == "needs_review"
    assert "too textually similar" in rationale


def test_classify_match_exact_duplicate_candidate_names_are_not_flagged_ambiguous(session):
    """Found against the real ~1.4M-row Food catalog: two Branded Foods
    catalog rows commonly share the exact same description text (or
    differ only in case) — that's the same food twice, not a real choice
    between two different foods, and must not trip the ambiguity check
    just because both score identically against the query."""
    session.add(_food(name="Acme Foods RICE CRACKERS", data_type="branded_food"))
    session.add(_food(name="acme foods rice crackers", data_type="branded_food"))
    session.commit()
    match = match_ingredient(session, "Acme Foods RICE CRACKERS")
    relationship, rationale = classify_match(match, "Acme Foods RICE CRACKERS", None, "per_100g_edible_portion")
    assert relationship != "needs_review"
    assert "too textually similar" not in (rationale or "")


def test_classify_match_near_but_not_exact_duplicate_names_still_needs_review(session):
    """The exact-duplicate check must not overreach into masking a real
    difference: two foods differing by nearly as little text as a
    duplicate SKU pair (here, a variety/colour word) are a genuine choice
    between two different foods and must still be flagged — this is the
    same fixture as the ambiguous-candidates test above, confirming the
    exact-match check doesn't swallow it."""
    session.add(_food(name="Beans, kidney, red, mature seeds, raw"))
    session.add(_food(name="Beans, kidney, white, mature seeds, raw"))
    session.commit()
    match = match_ingredient(session, "Beans, kidney")
    relationship, _ = classify_match(match, "Beans, kidney", None, "per_100g_edible_portion")
    assert relationship == "needs_review"


# ---- PROMPT 3B bug 1: top_similarity mislabeling ------------------------

def test_ambiguous_candidates_reports_true_best_not_just_selected_candidate():
    """Regression for PROMPT 3B bug 1, using the exact fixture from
    docs/phytate-review/prompt3b_bug_evidence_and_fixtures.csv row
    02010020:PHYTCPPI ("Potato, raw" selected to a sweet-potato entry at
    0.23 similarity, while the runner-up "Potatoes, raw, skin" scores
    0.73 — a higher score that the old code's "top_similarity" label
    hid). The trigger condition (still comparing candidates[0] vs [1], so
    which rows get flagged is unchanged) is not what's under test here —
    what's under test is that the rationale correctly attributes each
    score to the right candidate instead of calling the selected (lower)
    score "top"."""
    description = "Potato, raw"
    selected_name = "Sweet potato, raw, unprepared (Includes foods for USDA's Food Distribution Program)"
    runner_up_name = "Potatoes, raw, skin"
    match = MatchResult(
        food=_food(name=selected_name),
        method="fuzzy",
        confidence=0.65,
        candidates=[
            MatchCandidate(food_id=1, name=selected_name, score=1.0),
            MatchCandidate(food_id=2, name=runner_up_name, score=0.92),
        ],
    )
    ambiguous, rationale = _ambiguous_candidates(match, description)

    assert ambiguous is True
    # both scores must appear, correctly attributed...
    assert "selected candidate similarity: 0.23" in rationale
    assert "runner-up similarity: 0.73" in rationale
    # ...and the higher (runner-up's) score must be identified as the best
    # one, not silently reported only under the selected candidate's label.
    assert f"best candidate similarity: 0.73, held by {runner_up_name!r}" in rationale
    assert "selected candidate is NOT the highest-similarity one" in rationale


def test_ambiguous_candidates_notes_nothing_extra_when_selected_is_already_best():
    """When the selected candidate genuinely is the higher-similarity one,
    the rationale must not claim otherwise — the "selected is not best"
    note is conditional, not always appended."""
    description = "Beans, kidney"
    match = MatchResult(
        food=_food(name="Beans, kidney, red, mature seeds, raw"),
        method="fuzzy",
        confidence=0.65,
        candidates=[
            MatchCandidate(food_id=1, name="Beans, kidney, red, mature seeds, raw", score=1.0),
            MatchCandidate(food_id=2, name="Beans, kidney, white, mature seeds, raw", score=0.92),
        ],
    )
    ambiguous, rationale = _ambiguous_candidates(match, description)

    assert ambiguous is True
    assert "NOT the highest-similarity one" not in rationale


# ---- PROMPT 3B bug 2: infant/baby cereal category retrieval -------------

def test_infant_cereal_override_prefers_babyfood_cereal_over_wrong_category(session):
    """Regression for PROMPT 3B bug 2 (see
    docs/phytate-review/review_5_infant_flour_cluster.csv): a raw fuzzy
    match on "Infant flour, cereal-based, commercially produced,
    fortified" picks a wrong-category food (finger snacks, pie) purely
    because it shares the incidental phrase "commercially produced" with
    the description. When a real "Babyfood, cereal, ..., dry fortified"
    candidate exists, it must be preferred instead."""
    session.add(_food(name="Babyfood, baked product, finger snacks cereal fortified"))
    session.add(_food(name="Pie, apple, commercially prepared, enriched flour"))
    session.add(_food(name="Babyfood, cereal, barley, dry fortified"))
    session.add(_food(name="Babyfood, cereal, rice, dry fortified"))
    session.commit()

    description = "Infant flour, cereal-based, commercially produced, fortified"
    # the wrong-category match this reproduces from the real ~1.4M-row
    # catalog (see review_5_infant_flour_cluster.csv) — built directly
    # rather than relying on a toy in-memory DB's fuzzy-search ranking to
    # happen to reproduce the same wrong pick.
    finger_snack = session.query(Food).filter_by(name="Babyfood, baked product, finger snacks cereal fortified").one()
    wrong_match = MatchResult(
        food=finger_snack, method="fuzzy", confidence=0.65,
        candidates=[MatchCandidate(food_id=finger_snack.id, name=finger_snack.name, score=1.0)],
    )
    assert not wrong_match.food.name.startswith("Babyfood, cereal,")

    corrected = _prefer_infant_cereal_candidate(session, description, wrong_match)

    assert corrected.food.name.startswith("Babyfood, cereal,")
    assert corrected.food.name.endswith("dry fortified")
    assert corrected.confidence >= 0.7


def test_infant_cereal_override_picks_matching_grain_when_stated(session):
    session.add(_food(name="Babyfood, cereal, barley, dry fortified"))
    session.add(_food(name="Babyfood, cereal, rice, dry fortified"))
    session.commit()

    description = "Infant flour, cereal-based, rice, commercial, fortified"
    match = match_ingredient(session, description)
    corrected = _prefer_infant_cereal_candidate(session, description, match)

    assert corrected.food.name == "Babyfood, cereal, rice, dry fortified"


def test_infant_cereal_override_defaults_to_mixed_when_no_grain_stated(session):
    """Regression: with no grain word in the description, the fallback
    must be the honest mixed-grain candidate, not whichever candidate
    happens to sort first alphabetically (barley) -- see
    review_5_infant_flour_cluster.csv/review_6_accepted_sample.csv/
    review_6b_accepted_remainder.csv, where dozens of these arbitrary
    barley defaults were caught and replaced by hand."""
    session.add(_food(name="Babyfood, cereal, barley, dry fortified"))
    session.add(_food(name="Babyfood, cereal, mixed, dry fortified"))
    session.add(_food(name="Babyfood, cereal, rice, dry fortified"))
    session.commit()

    description = "Infant flour, cereal-based, commercially produced"
    match = match_ingredient(session, description)
    corrected = _prefer_infant_cereal_candidate(session, description, match)

    assert corrected.food.name == "Babyfood, cereal, mixed, dry fortified"


def test_infant_cereal_override_defaults_to_mixed_when_stated_grain_has_no_candidate(session):
    """Regression: FDC has no corn/maize/millet-specific babyfood-cereal
    entry (only barley/mixed/oatmeal/rice/multigrain). A description
    naming one of those grains must still fall back to mixed, not the
    alphabetically-first candidate (barley)."""
    session.add(_food(name="Babyfood, cereal, barley, dry fortified"))
    session.add(_food(name="Babyfood, cereal, mixed, dry fortified"))
    session.commit()

    description = "Infant flour, cereal-based, maize based, commercially produced"
    match = match_ingredient(session, description)
    corrected = _prefer_infant_cereal_candidate(session, description, match)

    assert corrected.food.name == "Babyfood, cereal, mixed, dry fortified"


def test_infant_cereal_override_is_noop_for_non_infant_descriptions(session):
    """The category preference must not fire for unrelated descriptions
    just because a babyfood-cereal row happens to exist in the catalog."""
    session.add(_food(name="Babyfood, cereal, rice, dry fortified"))
    session.add(_food(name="Rice flour, white, raw"))
    session.commit()

    description = "Rice flour, white, raw"
    match = match_ingredient(session, description)
    corrected = _prefer_infant_cereal_candidate(session, description, match)

    assert corrected is match


def test_infant_flour_cluster_never_matches_finger_snack_or_pie(session):
    """End-to-end regression across the full confirmed cluster pattern
    from review_5_infant_flour_cluster.csv: both wording variants
    ("commercially produced" and "commercial") must resolve to a real
    babyfood-cereal-dry-fortified candidate, never the finger-snack or
    pie candidates that outrank it on raw text similarity alone."""
    session.add(_food(name="Babyfood, baked product, finger snacks cereal fortified"))
    session.add(_food(name="Pie, apple, commercially prepared, enriched flour"))
    session.add(_food(name="Babyfood, cereal, barley, dry fortified"))
    session.add(_food(name="Babyfood, cereal, rice, dry fortified"))
    session.commit()

    descriptions = [
        "Infant flour, cereal-based, commercially produced, fortified",
        "Infant flour, cereal-based, commercial, fortified",
    ]
    for description in descriptions:
        match = match_ingredient(session, description)
        corrected = _prefer_infant_cereal_candidate(session, description, match)
        relationship, _ = classify_match(corrected, description, None, "per_100g_edible_portion")

        assert "finger snacks" not in corrected.food.name.lower()
        assert not corrected.food.name.lower().startswith("pie,")
        assert corrected.food.name.startswith("Babyfood, cereal,")
        assert relationship != "needs_review"


# ---- ingest_rows ---------------------------------------------------------

def test_ingest_rows_end_to_end_counts_and_needs_review_sample(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.add(_food(name="Beans, kidney, red, mature seeds, raw"))
    session.add(_food(name="Beans, kidney, white, mature seeds, raw"))
    session.commit()

    rows = [
        _row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="PFC-001"),
        _row(food_description="Beans, kidney", row_identifier="PFC-002"),
    ]
    stats, samples = ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)

    assert stats == {"considered": 2, "inserted": 2, "updated": 0, "needs_review": 1}
    assert len(samples) == 1
    assert samples[0]["food_description"] == "Beans, kidney"

    observations = {o.source_row_identifier: o for o in session.query(CompoundObservation).all()}
    assert observations["PFC-001"].match_relationship == "regional_equivalent"
    assert observations["PFC-002"].match_relationship == "needs_review"


def test_reingesting_the_same_rows_is_idempotent(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()

    rows = [_row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="PFC-001")]
    stats1, _ = ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)
    stats2, _ = ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)

    assert stats1["inserted"] == 1
    assert stats2["inserted"] == 0
    assert stats2["updated"] == 1
    assert session.query(CompoundObservation).count() == 1


def test_duplicate_row_identifier_within_one_batch_dedupes_not_double_inserts(session):
    """Regression: db (SessionLocal in production, see database.py) runs
    with autoflush=False, so the existing-row query can't see a
    db.add() queued earlier in this same call -- two input rows sharing
    a row_identifier (duplicate/malformed source data) would otherwise
    both be treated as new, and the second insert would violate
    uq_compound_observation_source_row at commit time and roll back the
    whole batch instead of updating in place."""
    session.autoflush = False
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()

    rows = [
        _row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="DUP-1"),
        _row(
            food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="DUP-1",
            value=999.0,
        ),
    ]
    stats, _ = ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)

    assert stats["inserted"] == 1
    assert stats["updated"] == 1
    saved = session.query(CompoundObservation).filter_by(source_row_identifier="DUP-1").all()
    assert len(saved) == 1
    assert saved[0].original_value == 999.0


def test_rows_without_row_identifier_are_always_inserted(session):
    """No natural key to dedupe on — see uq_compound_observation_source_row
    (Prompt 2). A source with no native row identifier needs its own
    dedup strategy; this script's job is just not to silently corrupt
    what it can't tell apart."""
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()

    rows = [_row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier=None)]
    ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)
    ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)

    assert session.query(CompoundObservation).count() == 2


def test_dry_run_does_not_write_to_the_database(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()

    rows = [_row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="PFC-001")]
    stats, _ = ingest_rows(session, rows, dry_run=True, **DATASET_KWARGS)

    assert stats["considered"] == 1  # classified, but nothing actually persisted
    assert stats["inserted"] == 0
    assert session.query(CompoundObservation).count() == 0
