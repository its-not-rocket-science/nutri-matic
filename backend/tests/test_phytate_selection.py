"""Tests for app.phytate_selection (prompts.txt PROMPT 6 of the
phytate/mineral-bioavailability extension) — the conservative,
deterministic phytate observation-selection service."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import CompoundObservation, Food
from app.phytate_selection import select_phytate_observations
from app.reference_patterns import AMINO_ACIDS
from app.source_licence_policy import (
    SURFACE_ENTERPRISE_BATCH,
    SURFACE_INTERNAL_RESEARCH_OR_ADMIN,
    SURFACE_PAID_EXPORT,
    SURFACE_PERSONAL_FREE_INTERNAL_API,
    SURFACE_PERSONAL_FREE_UI,
    SURFACE_PROFESSIONAL_DASHBOARD,
    SURFACE_PUBLIC_API,
    SourceLicenceError,
)

ALLOWED_SURFACE = SURFACE_PERSONAL_FREE_UI


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


@pytest.fixture
def food(session):
    f = Food(name="Test food", protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS), fdc_id=111)
    session.add(f)
    session.flush()
    return f


def _observation(food_id=None, **overrides):
    defaults = dict(
        compound="phytate", original_value=100.0, original_unit="mg", original_basis="per_100g_edible_portion",
        original_value_text="100.0", value_qualifier="measured", original_value_provenance="source_reported",
        source_food_description="Test food", source_dataset_name="PhyFoodComp1.0",
        source_dataset_citation="citation", source_dataset_version="1.0", source_access_date=date(2026, 8, 21),
        match_relationship="close_analogue", match_confidence=0.8, matched_food_id=food_id,
    )
    defaults.update(overrides)
    return CompoundObservation(**defaults)


def _censored(food_id, qualifier, **overrides):
    return _observation(
        food_id=food_id, value_qualifier=qualifier, original_value=None, original_value_provenance=None,
        original_value_text="< LOD", **overrides,
    )


# ---- no data / insufficient data -----------------------------------------

def test_no_observations_at_all_is_no_data(session, food):
    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.status == "no_data"
    assert result.selected == []


def test_all_censored_is_insufficient_data(session, food):
    session.add(_censored(food.id, "below_detection_limit", compound_fraction="IP6", source_row_identifier="1"))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.status == "insufficient_data"
    assert result.selected == []
    assert len(result.declined) == 1
    assert "below_detection_limit" in result.declined[0].reason


def test_observations_for_a_different_food_are_not_included(session, food):
    other_food = Food(name="Other", protein_g_per_100g=5.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    session.add(other_food)
    session.flush()
    session.add(_observation(food_id=other_food.id, compound_fraction="IP6", source_row_identifier="1"))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.status == "no_data"


# ---- a single family, single observation ---------------------------------

def test_single_measured_observation_is_selected(session, food):
    session.add(_observation(
        food_id=food.id, compound_fraction="PHYTCPPI", analytical_method="indirect precipitation",
        source_row_identifier="1",
    ))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.status == "selected"
    assert len(result.selected) == 1
    obs = result.selected[0]
    assert obs.compound_fraction == "PHYTCPPI"
    assert obs.family == "phytic_acid"
    assert obs.value == 100.0
    assert obs.match_relationship == "close_analogue"


def test_reported_zero_is_selected_as_a_real_value_not_missing(session, food):
    session.add(_observation(
        food_id=food.id, compound_fraction="PHYTCPPI", value_qualifier="reported_zero", original_value=0.0,
        original_value_text="0.0", source_row_identifier="1",
    ))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.status == "selected"
    assert result.selected[0].value == 0.0
    assert result.selected[0].value_qualifier == "reported_zero"


# ---- different analytical methods within one family: never averaged ----

def test_different_methods_same_family_are_both_selected_not_averaged(session, food):
    session.add(_observation(
        food_id=food.id, compound_fraction="PHYTCPPI", analytical_method="indirect precipitation",
        original_value=100.0, source_row_identifier="1",
    ))
    session.add(_observation(
        food_id=food.id, compound_fraction="PHYTCPP", analytical_method="anion exchange",
        original_value=140.0, source_row_identifier="2",
    ))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.status == "selected"
    assert len(result.selected) == 2
    values = {o.value for o in result.selected}
    assert values == {100.0, 140.0}  # neither averaged nor dropped


# ---- incompatible families: never merged, always both surfaced ----------

def test_phytic_acid_and_phytate_phosphorus_are_both_selected_and_flagged_incomparable(session, food):
    session.add(_observation(food_id=food.id, compound_fraction="PHYTCPPI", source_row_identifier="1"))
    session.add(_observation(food_id=food.id, compound_fraction="PPI", original_value=28.0, source_row_identifier="2"))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.status == "selected"
    families = {o.family for o in result.selected}
    assert families == {"phytic_acid", "phytate_phosphorus"}
    assert "not directly comparable" in result.explanation


# ---- inositol-phosphate subsumption: never double-counted ----------------

def test_ip6_alone_is_selected(session, food):
    session.add(_observation(food_id=food.id, compound_fraction="IP6", source_row_identifier="1"))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert len(result.selected) == 1
    assert result.selected[0].compound_fraction == "IP6"


def test_ip6_is_declined_when_ip5_a_ip6_also_present(session, food):
    session.add(_observation(food_id=food.id, compound_fraction="IP6", original_value=40.0, source_row_identifier="1"))
    session.add(_observation(
        food_id=food.id, compound_fraction="IP5_A_IP6", original_value=90.0, source_row_identifier="2",
    ))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    selected_fractions = {o.compound_fraction for o in result.selected}
    assert selected_fractions == {"IP5_A_IP6"}
    declined_fractions = {d.compound_fraction for d in result.declined}
    assert declined_fractions == {"IP6"}
    assert "subsumed by IP5_A_IP6" in result.declined[0].reason


def test_ip3_is_not_subsumed_by_ip5_a_ip6(session, food):
    """IP5_A_IP6 covers IP5+IP6 only -- IP3 remains independently
    informative and must stay selected."""
    session.add(_observation(food_id=food.id, compound_fraction="IP3", original_value=10.0, source_row_identifier="1"))
    session.add(_observation(
        food_id=food.id, compound_fraction="IP5_A_IP6", original_value=90.0, source_row_identifier="2",
    ))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    selected_fractions = {o.compound_fraction for o in result.selected}
    assert selected_fractions == {"IP3", "IP5_A_IP6"}
    assert result.declined == []


def test_ipsum_subsumes_everything_else_present(session, food):
    session.add(_observation(food_id=food.id, compound_fraction="IP6", original_value=40.0, source_row_identifier="1"))
    session.add(_observation(
        food_id=food.id, compound_fraction="IP5_A_IP6", original_value=90.0, source_row_identifier="2",
    ))
    session.add(_observation(food_id=food.id, compound_fraction="IPSUM", original_value=200.0, source_row_identifier="3"))
    session.commit()

    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    selected_fractions = {o.compound_fraction for o in result.selected}
    assert selected_fractions == {"IPSUM"}
    declined_fractions = {d.compound_fraction for d in result.declined}
    assert declined_fractions == {"IP6", "IP5_A_IP6"}


# ---- preparation compatibility -------------------------------------------

def test_preparation_compatible_true_when_context_matches(session, food):
    session.add(_observation(
        food_id=food.id, compound_fraction="IP6", source_preparation_state="raw", source_row_identifier="1",
    ))
    session.commit()
    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE, preparation_context="raw")
    assert result.selected[0].preparation_compatible is True


def test_preparation_compatible_false_when_context_mismatches(session, food):
    session.add(_observation(
        food_id=food.id, compound_fraction="IP6", source_preparation_state="boiled", source_row_identifier="1",
    ))
    session.commit()
    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE, preparation_context="raw")
    assert result.selected[0].preparation_compatible is False


def test_preparation_compatible_none_when_no_context_given(session, food):
    session.add(_observation(
        food_id=food.id, compound_fraction="IP6", source_preparation_state="raw", source_row_identifier="1",
    ))
    session.commit()
    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result.selected[0].preparation_compatible is None


def test_preparation_compatible_none_when_source_has_no_preparation_state(session, food):
    session.add(_observation(food_id=food.id, compound_fraction="IP6", source_row_identifier="1"))
    session.commit()
    result = select_phytate_observations(session, food.id, ALLOWED_SURFACE, preparation_context="raw")
    assert result.selected[0].preparation_compatible is None


# ---- determinism -----------------------------------------------------------

def test_selection_is_deterministic_across_repeated_calls(session, food):
    session.add(_observation(food_id=food.id, compound_fraction="PHYTCPPI", source_row_identifier="1"))
    session.add(_observation(food_id=food.id, compound_fraction="PPI", original_value=28.0, source_row_identifier="2"))
    session.commit()

    result1 = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    result2 = select_phytate_observations(session, food.id, ALLOWED_SURFACE)

    assert [o.compound_fraction for o in result1.selected] == [o.compound_fraction for o in result2.selected]


# ---- source-licence surface enforcement -----------------------------------

@pytest.mark.parametrize("surface", [SURFACE_PERSONAL_FREE_UI, SURFACE_PERSONAL_FREE_INTERNAL_API, SURFACE_INTERNAL_RESEARCH_OR_ADMIN])
def test_permitted_surfaces_can_call_the_service(session, food, surface):
    session.add(_observation(food_id=food.id, compound_fraction="IP6", source_row_identifier="1"))
    session.commit()
    result = select_phytate_observations(session, food.id, surface)
    assert result.status == "selected"


@pytest.mark.parametrize("surface", [
    SURFACE_PUBLIC_API, SURFACE_PROFESSIONAL_DASHBOARD, SURFACE_ENTERPRISE_BATCH, SURFACE_PAID_EXPORT,
])
def test_prohibited_surfaces_cannot_call_the_service(session, food, surface):
    """Required by prompts.txt PROMPT 6: paid/professional/enterprise
    consumers must not be able to call this service under a prohibited
    surface -- the exact same fail-closed gate as the raw read boundary,
    since this service is built on top of it, not around it."""
    session.add(_observation(food_id=food.id, compound_fraction="IP6", source_row_identifier="1"))
    session.commit()
    with pytest.raises(SourceLicenceError):
        select_phytate_observations(session, food.id, surface)


def test_service_does_not_bypass_the_boundary_even_with_data_present(session, food):
    """Data existing for the food must not matter -- the licence check
    happens before matched_food_id is even filtered on."""
    session.add(_observation(food_id=food.id, compound_fraction="IP6", source_row_identifier="1"))
    session.commit()
    with pytest.raises(SourceLicenceError):
        select_phytate_observations(session, food.id, "unknown_made_up_surface")


# ---- policy version --------------------------------------------------------

def test_result_always_carries_a_policy_version(session, food):
    result_no_data = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result_no_data.policy_version == "phytate-selection-v1"

    session.add(_observation(food_id=food.id, compound_fraction="IP6", source_row_identifier="1"))
    session.commit()
    result_with_data = select_phytate_observations(session, food.id, ALLOWED_SURFACE)
    assert result_with_data.policy_version == "phytate-selection-v1"
