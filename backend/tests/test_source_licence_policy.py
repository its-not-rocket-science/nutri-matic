"""Tests for app.source_licence_policy (prompts.txt PROMPT 4 of the
phytate/mineral-bioavailability extension) — the fail-closed source-
licence policy and free-surface boundary, separate from
app.entitlements' product-plan gating."""

from datetime import date

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import CompoundObservation
from app.source_licence_policy import (
    KNOWN_SURFACES,
    PHYFOODCOMP_1_0,
    SURFACE_CLINICIAN_REPORT,
    SURFACE_ENTERPRISE_BATCH,
    SURFACE_INTERNAL_RESEARCH_OR_ADMIN,
    SURFACE_PAID_EXPORT,
    SURFACE_PERSONAL_FREE_INTERNAL_API,
    SURFACE_PERSONAL_FREE_UI,
    SURFACE_PROFESSIONAL_DASHBOARD,
    SURFACE_PUBLIC_API,
    SourceLicenceError,
    check_deployment_permits_write,
    check_surface_allowed,
    deployment_permitted_surfaces,
    get_policy,
    load_compound_observations,
    require_surface,
    source_key_for_compound,
    validate_source_licence_policy_coverage,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


def _observation(**overrides):
    defaults = dict(
        compound="phytate", original_value=100.0, original_unit="mg",
        original_basis="per_100g_edible_portion", original_value_text="100.0", value_qualifier="measured",
        original_value_provenance="source_reported", source_food_description="Test food",
        source_dataset_name="PhyFoodComp1.0", source_dataset_citation="citation",
        source_dataset_version="1.0", source_access_date=date(2026, 8, 21),
        match_relationship="needs_review",
    )
    defaults.update(overrides)
    return CompoundObservation(**defaults)


# ---- get_policy / source_key_for_compound ---------------------------------

def test_get_policy_returns_registered_phyfoodcomp_policy():
    policy = get_policy(PHYFOODCOMP_1_0)
    assert policy.licence_status == "pending_commercial_permission"


def test_get_policy_unknown_source_fails_closed():
    with pytest.raises(SourceLicenceError):
        get_policy("some_unregistered_source")


def test_source_key_for_known_compound():
    assert source_key_for_compound("phytate") == PHYFOODCOMP_1_0


def test_source_key_for_unknown_compound_fails_closed():
    with pytest.raises(SourceLicenceError):
        source_key_for_compound("oxalate")


# ---- check_surface_allowed: the actual policy matrix ----------------------

@pytest.mark.parametrize("surface", [
    SURFACE_PERSONAL_FREE_UI, SURFACE_PERSONAL_FREE_INTERNAL_API, SURFACE_INTERNAL_RESEARCH_OR_ADMIN,
])
def test_permitted_surfaces_pass(surface):
    check_surface_allowed(PHYFOODCOMP_1_0, surface)  # must not raise


@pytest.mark.parametrize("surface", [
    SURFACE_PUBLIC_API, SURFACE_PROFESSIONAL_DASHBOARD, SURFACE_CLINICIAN_REPORT,
    SURFACE_ENTERPRISE_BATCH, SURFACE_PAID_EXPORT,
])
def test_prohibited_surfaces_are_denied(surface):
    """Required by prompts.txt PROMPT 4: exclude PhyFoodComp-derived
    fields from public API keys, professional/clinician outputs,
    enterprise/batch, and paid exports while FAO permission is pending."""
    with pytest.raises(SourceLicenceError):
        check_surface_allowed(PHYFOODCOMP_1_0, surface)


def test_unknown_surface_string_fails_closed():
    with pytest.raises(SourceLicenceError):
        check_surface_allowed(PHYFOODCOMP_1_0, "some_made_up_surface")


def test_every_known_surface_has_an_explicit_allow_or_deny_for_phyfoodcomp():
    """No surface is left in limbo -- every one of the 8 known surfaces
    is either permitted or prohibited for PhyFoodComp, never silently
    absent from both."""
    policy = get_policy(PHYFOODCOMP_1_0)
    covered = policy.permitted_surfaces | policy.prohibited_surfaces
    assert covered == KNOWN_SURFACES


# ---- plan independence: the core of "not a paid/free boolean" -----------

@pytest.mark.parametrize("surface", [SURFACE_PERSONAL_FREE_UI, SURFACE_PERSONAL_FREE_INTERNAL_API])
def test_allowed_surface_check_takes_no_plan_argument_at_all(surface):
    """check_surface_allowed's signature has no user/plan parameter --
    structurally, a free vs. paid vs. professional vs. enterprise account
    cannot produce a different outcome here, because nothing about the
    caller is ever passed in. This is the regression prompts.txt asks
    for: identical behaviour across every plan on the allowed surface."""
    import inspect
    params = inspect.signature(check_surface_allowed).parameters
    assert "user" not in params and "plan" not in params
    check_surface_allowed(PHYFOODCOMP_1_0, surface)  # must not raise, for any caller


# ---- load_compound_observations: the mandatory read boundary -------------

def test_load_compound_observations_returns_filtered_query_on_allowed_surface(session):
    session.add(_observation(source_row_identifier="1"))
    session.add(_observation(source_row_identifier="2", compound="oxalate_placeholder_never_registered"))
    session.commit()

    # only "phytate" is registered; the second row's compound is a stand-in
    # for "some other compound this policy doesn't cover yet" and is
    # excluded by the query filter regardless.
    query = load_compound_observations(session, "phytate", SURFACE_PERSONAL_FREE_UI)
    results = query.all()

    assert len(results) == 1
    assert results[0].source_row_identifier == "1"


def test_load_compound_observations_refuses_prohibited_surface_before_querying(session):
    with pytest.raises(SourceLicenceError):
        load_compound_observations(session, "phytate", SURFACE_PUBLIC_API)


def test_load_compound_observations_refuses_unregistered_compound(session):
    with pytest.raises(SourceLicenceError):
        load_compound_observations(session, "totally_unregistered_compound", SURFACE_PERSONAL_FREE_UI)


# ---- require_surface: FastAPI dependency, no user/plan dependency chain --

def _build_test_app(surface: str) -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(_=Depends(require_surface(PHYFOODCOMP_1_0, surface))):
        return {"ok": True}

    return app


def test_require_surface_allows_personal_free_ui_with_no_auth_header_needed():
    client = TestClient(_build_test_app(SURFACE_PERSONAL_FREE_UI))
    response = client.get("/probe")
    assert response.status_code == 200


@pytest.mark.parametrize("surface", [SURFACE_PUBLIC_API, SURFACE_ENTERPRISE_BATCH, SURFACE_PAID_EXPORT])
def test_require_surface_403s_prohibited_surfaces(surface):
    client = TestClient(_build_test_app(surface))
    response = client.get("/probe")
    assert response.status_code == 403


def _build_test_app_with_plan(surface: str, plan: str) -> FastAPI:
    """Same probe endpoint, but with a plan carried alongside the request
    (as a header) purely to prove the surface check's outcome doesn't
    vary with it -- require_surface never reads this header at all."""
    app = FastAPI()

    @app.get("/probe")
    def probe(_plan_header: str | None = None, __=Depends(require_surface(PHYFOODCOMP_1_0, surface))):
        return {"ok": True, "plan_seen_by_endpoint": plan}

    return app


@pytest.mark.parametrize("plan", ["free", "trial", "paid", "professional", "enterprise"])
def test_personal_free_ui_response_is_identical_across_every_plan(plan):
    """Required by prompts.txt PROMPT 4: regression tests comparing free,
    trial, paid, professional, and enterprise accounts on the ordinary
    personal surface -- the response must not vary by plan."""
    client = TestClient(_build_test_app_with_plan(SURFACE_PERSONAL_FREE_UI, plan))
    response = client.get("/probe")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.parametrize("plan", ["free", "trial", "paid", "professional", "enterprise"])
def test_prohibited_surface_is_denied_regardless_of_plan(plan):
    """The mirror image: a paid/professional/enterprise account gets no
    better access to a prohibited surface than a free account does --
    plan membership alone must never be the licensing control."""
    client = TestClient(_build_test_app_with_plan(SURFACE_ENTERPRISE_BATCH, plan))
    response = client.get("/probe")
    assert response.status_code == 403


# ---- startup/coverage check -------------------------------------------

def test_coverage_check_passes_when_every_compound_is_registered(session):
    session.add(_observation(source_row_identifier="1"))  # compound="phytate", registered
    session.commit()
    assert validate_source_licence_policy_coverage(session) == []


def test_coverage_check_flags_an_unregistered_compound(session):
    session.add(_observation(source_row_identifier="1", compound="some_new_compound_nobody_registered"))
    session.commit()
    warnings = validate_source_licence_policy_coverage(session)
    assert len(warnings) == 1
    assert "some_new_compound_nobody_registered" in warnings[0]


def test_coverage_check_flags_a_known_compound_with_unregistered_source_dataset_name(session):
    """PROMPT 13 requirement 3: coverage is keyed on (compound,
    source_dataset_name), not compound alone -- a registered compound
    stored under a dataset name nobody registered a policy for must still
    fail closed, not silently pass because "phytate" alone is known."""
    session.add(_observation(source_row_identifier="1", source_dataset_name="SomeOtherPhytateDataset"))
    session.commit()
    warnings = validate_source_licence_policy_coverage(session)
    assert len(warnings) == 1
    assert "SomeOtherPhytateDataset" in warnings[0]


def test_coverage_check_evaluates_a_second_source_for_the_same_compound_separately(session):
    """A second, unregistered source for "phytate" must not inherit
    PhyFoodComp's coverage just because the first source for that
    compound is registered -- each (compound, source_dataset_name) pair
    stands on its own."""
    session.add(_observation(source_row_identifier="1"))  # registered: phytate / PhyFoodComp1.0
    session.add(_observation(source_row_identifier="2", source_dataset_name="SecondPhytateSource"))
    session.commit()
    warnings = validate_source_licence_policy_coverage(session)
    assert len(warnings) == 1
    assert "SecondPhytateSource" in warnings[0]


def test_coverage_check_flags_prohibited_surface_exposed_by_deployment_config(session, monkeypatch):
    """Requirement 2's second clause: healthy compound/source coverage
    isn't enough if this deployment's own DEPLOYMENT_PERMITTED_SURFACES
    declares a surface PhyFoodComp's policy prohibits."""
    session.add(_observation(source_row_identifier="1"))
    session.commit()
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", SURFACE_ENTERPRISE_BATCH)
    warnings = validate_source_licence_policy_coverage(session)
    assert len(warnings) == 1
    assert SURFACE_ENTERPRISE_BATCH in warnings[0]


def test_coverage_check_passes_on_a_permitted_deployment_profile(session, monkeypatch):
    session.add(_observation(source_row_identifier="1"))
    session.commit()
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", SURFACE_PERSONAL_FREE_UI)
    assert validate_source_licence_policy_coverage(session) == []


# ---- source_key_for_compound: fails closed on ambiguity too ---------------

def test_source_key_for_compound_fails_closed_when_two_sources_registered(monkeypatch):
    """PROMPT 13: if a future second phytate source is ever added to
    COMPOUND_SOURCE_KEYS without updating every compound-only call site,
    this must become an explicit failure, never a silent pick of
    whichever entry happens to be registered first."""
    import app.source_licence_policy as policy_module

    monkeypatch.setitem(policy_module.COMPOUND_SOURCE_KEYS, ("phytate", "SecondPhytateSource"), "second_phytate_source_1_0")
    with pytest.raises(SourceLicenceError):
        source_key_for_compound("phytate")


# ---- deployment-level write safeguard (prompts.txt PROMPT 10) -------------

def test_deployment_permitted_surfaces_is_empty_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("DEPLOYMENT_PERMITTED_SURFACES", raising=False)
    assert deployment_permitted_surfaces() == frozenset()


def test_deployment_permitted_surfaces_parses_comma_separated_list(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", f" {SURFACE_PERSONAL_FREE_UI} ,{SURFACE_PERSONAL_FREE_INTERNAL_API},")
    assert deployment_permitted_surfaces() == {SURFACE_PERSONAL_FREE_UI, SURFACE_PERSONAL_FREE_INTERNAL_API}


def test_deployment_write_check_fails_closed_when_env_var_unset(monkeypatch):
    """Unset must mean "no surfaces declared", never "assume the policy's
    permitted set" or "assume everything" -- a deployment must explicitly
    opt in."""
    monkeypatch.delenv("DEPLOYMENT_PERMITTED_SURFACES", raising=False)
    with pytest.raises(SourceLicenceError):
        check_deployment_permits_write(PHYFOODCOMP_1_0, SURFACE_PERSONAL_FREE_UI)


def test_deployment_write_check_fails_when_deployment_declares_a_different_surface(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", SURFACE_PERSONAL_FREE_INTERNAL_API)
    with pytest.raises(SourceLicenceError):
        check_deployment_permits_write(PHYFOODCOMP_1_0, SURFACE_PERSONAL_FREE_UI)


def test_deployment_write_check_fails_when_policy_prohibits_the_surface_even_if_deployment_declares_it(monkeypatch):
    """The deployment-level check is additive, not a replacement -- a
    surface SOURCE_LICENCE_POLICIES prohibits stays refused even if this
    deployment's own configuration (incorrectly) declares it."""
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", SURFACE_ENTERPRISE_BATCH)
    with pytest.raises(SourceLicenceError):
        check_deployment_permits_write(PHYFOODCOMP_1_0, SURFACE_ENTERPRISE_BATCH)


def test_deployment_write_check_passes_when_both_policy_and_deployment_agree(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", SURFACE_PERSONAL_FREE_UI)
    check_deployment_permits_write(PHYFOODCOMP_1_0, SURFACE_PERSONAL_FREE_UI)  # does not raise
