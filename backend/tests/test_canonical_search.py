"""Search tier 1: reviewed canonical aliases (plan 3.3, canonical foods PR 4b).

Unit tests use a hand-written signed CSV over a few real FDC rows. The
file-wide tests load the real reviewed CSV over the golden mini catalogue
(tests/fixtures/search_golden_catalogue.json holds every anchor row).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.canonical_foods.__main__ import main as canonical_cli
from app.canonical_foods.csv_schema import COLUMNS, CanonicalCsvError, load_file, parse
from app.canonical_foods.loader import load
from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
from app.search import search_foods_by_name_hits

FIXTURES = Path(__file__).parent / "fixtures"

FOODS = [
    (1, 173800, "sr_legacy_food", "Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids"),
    (2, 173756, "sr_legacy_food", "Chickpeas (garbanzo beans, bengal gram), mature seeds, raw"),
    (3, 173757, "sr_legacy_food",
     "Chickpeas (garbanzo beans, bengal gram), mature seeds, cooked, boiled, without salt"),
    (4, 169387, "sr_legacy_food", "Arugula, raw"),
    (5, 171267, "sr_legacy_food", "Milk, reduced fat, fluid, 2% milkfat, with added vitamin A and vitamin D"),
    (6, 171265, "sr_legacy_food", "Milk, whole, 3.25% milkfat, with added vitamin D"),
    (7, 2644282, "foundation_food", "Chickpeas, (garbanzo beans, bengal gram), dry"),
    (8, 9000001, "branded_food", "ROCKET SCIENCE GAMES BBQ SAUCE"),
]


NAMES = {fdc_id: name for _, fdc_id, _, name in FOODS}


def _row(key, gb, us, anchor, alias, locale="*", relationship="exact", note="", ambiguous=""):
    concept, state = key.split(".")
    return dict(zip(COLUMNS, (concept, key, state, gb, us, str(anchor), NAMES[anchor], alias, locale,
                               relationship, note, ambiguous, "Tester", "2026-11-28", "")))


ROWS = [
    _row("chickpeas.canned_drained", "Chickpeas, tinned, drained", "Chickpeas, canned, drained", 173800, "chickpeas"),
    _row("chickpeas.canned_drained", "Chickpeas, tinned, drained", "Chickpeas, canned, drained", 173800,
         "tinned chickpeas", "en-GB"),
    _row("chickpeas.dry", "Chickpeas, dried", "Chickpeas, dry", 173756, "chickpeas"),
    _row("chickpeas.dry", "Chickpeas, dried", "Chickpeas, dry", 173756, "dried chickpeas"),
    _row("chickpeas.cooked_boiled", "Chickpeas, boiled", "", 173757, "chickpeas"),
    _row("rocket.raw", "Rocket", "Arugula", 169387, "rocket", "en-GB"),
    _row("rocket.raw", "Rocket", "Arugula", 169387, "arugula"),
    _row("milk_reduced_fat_2pct.unspecified", "Milk, 2% fat (US reduced-fat)", "", 171267, "semi-skimmed milk",
         "en-GB", "close_analogue", "approx. UK semi-skimmed"),
    _row("milk_reduced_fat_2pct.unspecified", "Milk, 2% fat (US reduced-fat)", "", 171267, "milk",
         ambiguous="yes"),
    _row("milk_whole.unspecified", "Milk, whole", "", 171265, "milk", ambiguous="yes"),
]


def _csv(rows):
    lines = [",".join(COLUMNS)]
    for r in rows:
        lines.append(",".join(f'"{r[c]}"' if "," in r[c] else r[c] for c in COLUMNS))
    return "\n".join(lines) + "\n"


def _session(rows=ROWS):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    for id_, fdc_id, data_type, name in FOODS:
        session.add(Food(id=id_, fdc_id=fdc_id, data_type=data_type, name=name, protein_g_per_100g=1.0,
                         amino_acids={}))
        session.add(FoodNutrient(food_id=id_, nutrient_key="energy", amount_per_100g=100.0))
    session.commit()
    if rows:
        load(session, parse(_csv(rows)))
        session.commit()
    return session, Session


@pytest.fixture
def db():
    session, _ = _session()
    yield session
    session.close()


def _search(db, q, locale="en-GB", limit=15):
    return search_foods_by_name_hits(db, q, limit=limit, locale=locale)


def test_exact_alias_puts_the_canonical_first_with_its_variants(db):
    hits = _search(db, "chickpeas")
    assert [h.canonical_key for h in hits[:3]] == [
        "chickpeas.canned_drained",  # UK default (owner decision): tinned first
        "chickpeas.cooked_boiled",   # then the same family (ready to eat), food_preparation.preparation_rank
        "chickpeas.dry",
    ]
    top = hits[0]
    assert top.food.fdc_id == 173800
    assert top.canonical_name == "Chickpeas, tinned, drained"
    assert top.canonical_source == "USDA SR Legacy"
    assert top.preparation_label == "Tinned, drained"


def test_token_results_follow_without_repeating_an_anchor(db):
    hits = _search(db, "chickpeas")
    fdc_ids = [h.food.fdc_id for h in hits]
    assert len(fdc_ids) == len(set(fdc_ids))
    assert 2644282 in fdc_ids[3:]  # the Foundation row is still offered, after the canonicals
    assert all(h.canonical_key is None for h in hits[3:])


def test_matched_variant_comes_before_its_siblings(db):
    hits = _search(db, "dried chickpeas")
    assert hits[0].canonical_key == "chickpeas.dry"
    assert {h.canonical_key for h in hits[1:3]} == {"chickpeas.canned_drained", "chickpeas.cooked_boiled"}


def test_plural_or_singular_of_the_alias_matches(db):
    assert _search(db, "chickpea")[0].canonical_key == "chickpeas.canned_drained"
    assert _search(db, "  Tinned   Chickpeas ")[0].canonical_key == "chickpeas.canned_drained"


def test_locale_only_alias_is_not_offered_in_other_locales(db):
    assert _search(db, "rocket")[0].canonical_key == "rocket.raw"
    us = _search(db, "rocket", locale="en-US")
    assert all(h.canonical_key is None for h in us)
    assert _search(db, "arugula", locale="en-US")[0].canonical_name == "Arugula"


def test_close_analogue_carries_its_note(db):
    top = _search(db, "semi-skimmed milk")[0]
    assert top.canonical_key == "milk_reduced_fat_2pct.unspecified"
    assert (top.relationship, top.note) == ("close_analogue", "approx. UK semi-skimmed")
    assert top.preparation_label is None  # unspecified: no badge


def test_ambiguous_alias_lists_every_concept_in_a_fixed_order(db):
    hits = _search(db, "milk")
    assert [h.canonical_key for h in hits[:2]] == ["milk_reduced_fat_2pct.unspecified", "milk_whole.unspecified"]
    assert hits[0].note is None  # the note belongs to the semi-skimmed alias, not to "milk"


def test_non_alias_query_has_no_canonical_results(db):
    assert all(h.canonical_key is None for h in _search(db, "chickpeas raw"))


def test_retired_canonical_is_not_offered():
    session, _ = _session()
    load(session, parse(_csv([r for r in ROWS if not r["canonical_key"].startswith("rocket")])))
    session.commit()
    assert all(h.canonical_key is None for h in _search(session, "rocket"))
    session.close()


def test_empty_canonical_tables_leave_search_as_before():
    with_layer, _ = _session()
    without, _ = _session(rows=[])
    plain = [h.food.fdc_id for h in _search(without, "chickpeas")]
    layered = [h.food.fdc_id for h in _search(with_layer, "chickpeas")]
    assert set(plain) == set(layered)  # same rows, canonical anchors moved to the top
    assert all(h.canonical_key is None for h in _search(without, "chickpeas"))
    with_layer.close()
    without.close()


def test_limit_counts_canonical_results(db):
    assert len(_search(db, "chickpeas", limit=2)) == 2


def test_search_by_name_api_returns_canonical_fields():
    session, Session = _session()
    session.close()

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        body = TestClient(app).get("/api/foods/search-by-name?q=semi-skimmed%20milk").json()
    finally:
        app.dependency_overrides.clear()
    top = body[0]
    assert top["name"] == "Milk, reduced fat, fluid, 2% milkfat, with added vitamin A and vitamin D"
    assert top["canonical_key"] == "milk_reduced_fat_2pct.unspecified"
    assert top["canonical_name"] == "Milk, 2% fat (US reduced-fat)"
    assert top["canonical_source"] == "USDA SR Legacy"
    assert top["search_note"] == "approx. UK semi-skimmed"


# --- validation additions -------------------------------------------------

def test_star_and_locale_alias_for_two_concepts_needs_ambiguous():
    rows = [
        _row("chickpeas.dry", "Chickpeas, dried", "", 173756, "beans"),
        _row("rocket.raw", "Rocket", "", 169387, "beans", "en-GB"),
    ]
    with pytest.raises(CanonicalCsvError, match="across en-GB and"):
        parse(_csv(rows))
    for r in rows:
        r["ambiguous"] = "yes"
    parse(_csv(rows))


def test_locale_specific_aliases_may_differ_by_locale():
    parse(_csv([
        _row("chickpeas.dry", "Chickpeas, dried", "", 173756, "chips", "en-GB"),
        _row("rocket.raw", "Rocket", "", 169387, "chips", "en-US"),
    ]))


def test_unsigned_rows_parse_only_when_asked():
    row = _row("rocket.raw", "Rocket", "", 169387, "rocket")
    row["reviewer"], row["review_date"] = "PENDING", ""
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv([row]))
    assert e.value.problems == ["line 2: reviewer is missing: the row has not been signed off"]
    assert "rocket.raw" in parse(_csv([row]), require_signoff=False)
    row["relationship"] = "close_analogue"  # other rules still apply
    with pytest.raises(CanonicalCsvError, match="alias_note"):
        parse(_csv([row]), require_signoff=False)


def test_cli_refuses_a_real_load_of_unsigned_rows():
    with pytest.raises(SystemExit):
        canonical_cli(["load", "--allow-unsigned"])


# --- the reviewed file over the golden mini catalogue ----------------------

@pytest.fixture(scope="module")
def golden_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    for row in json.loads((FIXTURES / "search_golden_catalogue.json").read_text(encoding="utf-8"))["foods"]:
        session.add(Food(id=row["id"], fdc_id=row["fdc_id"], name=row["name"], data_type=row["data_type"],
                         protein_g_per_100g=1.0, amino_acids={}))
        session.add(FoodNutrient(food_id=row["id"], nutrient_key="energy", amount_per_100g=100.0))
    session.commit()
    load(session, load_file(require_signoff=False))
    session.commit()
    yield session
    session.close()


def _file_aliases():
    out = []
    for canonical in load_file(require_signoff=False).values():
        for a in canonical.aliases:
            out.append((a.alias, a.locale, canonical.concept))
    return sorted(set(out))


@pytest.mark.parametrize("alias, locale, concept", _file_aliases(), ids=lambda v: str(v))
def test_every_alias_in_the_file_leads_to_its_concept(golden_db, alias, locale, concept):
    """Each reviewed alias, searched in its locale (en-GB for '*'), puts a
    canonical first, and one of that alias's concepts is in the canonical
    block."""
    hits = _search(golden_db, alias, locale="en-GB" if locale == "*" else locale, limit=30)
    assert hits and hits[0].canonical_key is not None
    concepts = {h.canonical_key.split(".")[0] for h in hits if h.canonical_key}
    assert concept in concepts


# The first variant shown for every alias that covers several preparation
# states of one concept. Owner decisions: PR 1 (tinned chickpeas, kidney
# beans, tomatoes, sweetcorn; dry lentils, rice, pasta, porridge oats; raw
# vegetables) and the PR 4b review (frozen peas, tinned black beans).
# A new multi-state alias must be added here, so its default is a decision.
MULTI_STATE_FIRST = {
    "chickpeas": "canned_drained", "chickpea": "canned_drained",
    "kidney beans": "canned_drained", "red kidney beans": "canned_drained",
    "tomatoes": "canned_with_liquid", "tomato": "canned_with_liquid",
    "sweetcorn": "canned_drained", "sweet corn": "canned_drained",
    "black beans": "canned_with_liquid",
    "lentils": "dry",
    "rice": "dry", "white rice": "dry", "basmati rice": "dry", "brown rice": "dry",
    "pasta": "dry", "spaghetti": "dry", "penne": "dry", "fusilli": "dry",
    "oats": "dry",
    "peas": "frozen",
}


def _multi_state_aliases():
    states: dict[tuple[str, str], set[str]] = {}
    for canonical in load_file(require_signoff=False).values():
        for a in canonical.aliases:
            states.setdefault((a.alias, a.locale), set()).add(canonical.key)
    return sorted(k for k, keys in states.items() if len({key.split(".")[0] for key in keys}) == 1 and len(keys) > 1)


def test_every_multi_state_alias_has_a_decided_default():
    undecided = sorted({alias for alias, _ in _multi_state_aliases()} - set(MULTI_STATE_FIRST))
    assert not undecided, f"decide the first preparation state for: {undecided}"


@pytest.mark.parametrize("alias, locale", _multi_state_aliases(), ids=lambda v: str(v))
def test_multi_state_alias_lists_the_decided_state_first(golden_db, alias, locale):
    hits = _search(golden_db, alias, locale="en-GB" if locale == "*" else locale)
    assert hits[0].canonical_key.split(".")[1] == MULTI_STATE_FIRST[alias], [h.canonical_key for h in hits[:4]]


@pytest.mark.parametrize("query, locale, key, note", [
    ("caster sugar", "en-GB", "sugar_white.unspecified", "US granulated sugar; caster is the same sugar, ground finer"),
    ("vegetable oil", "en-GB", "oil_rapeseed.unspecified", "UK vegetable oil is usually rapeseed oil"),
    ("vegetable oil", "en-US", "oil_soybean.unspecified", "US vegetable oil is usually soybean oil"),
    ("tea", "en-GB", "tea_black.unspecified", "brewed, without milk; add milk separately"),
    ("golden syrup", "en-GB", "syrup_cane.unspecified", "US cane syrup; golden syrup is a similar sugar syrup"),
])
def test_staple_aliases_disclose_their_approximation(golden_db, query, locale, key, note):
    top = _search(golden_db, query, locale=locale)[0]
    assert (top.canonical_key, top.note) == (key, note)
