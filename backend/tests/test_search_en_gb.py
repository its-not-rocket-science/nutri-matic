"""en-GB search pieces: locale seam, preparation classifier, synonym table,
token-AND matching, and the search-by-name API fields (PR 1 of
docs/plans/canonical-foods-plan.md)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.food_preparation import (
    PREPARATION_STATES,
    classify_preparation,
    preferred_preparation,
    preparation_label,
    preparation_rank,
)
from app.main import app
from app.models import Food
from app.search import expand_food_query, search_foods_by_name, search_foods_by_name_hits
from app.search_locale import DEFAULT_SEARCH_LOCALE, SUPPORTED_SEARCH_LOCALES, search_locale
from app.search_synonyms import PHRASE_SYNONYMS, RELATIONSHIPS, TOKEN_SYNONYMS


def test_locale_is_en_gb_for_everyone_for_now():
    assert DEFAULT_SEARCH_LOCALE == "en-GB"
    assert search_locale() == "en-GB"
    assert search_locale(object()) == "en-GB"
    assert DEFAULT_SEARCH_LOCALE in SUPPORTED_SEARCH_LOCALES


@pytest.mark.parametrize("name, state", [
    ("Chickpeas, (garbanzo beans, bengal gram), dry", "dry"),
    ("Chickpeas (garbanzo beans, bengal gram), mature seeds, raw", "dry"),
    ("Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids", "canned_drained"),
    ("Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, solids and liquids", "canned_with_liquid"),
    ("Chickpeas (garbanzo beans, bengal gram), mature seeds, cooked, boiled, with salt", "cooked_boiled"),
    ("Lentils, raw", "dry"),
    ("Lentils, sprouted, raw", "sprouted"),
    ("Rice, white, long-grain, regular, raw, enriched", "dry"),
    ("Rice, white, long-grain, regular, enriched, cooked", "cooked_boiled"),
    ("Rice crackers", "unspecified"),
    ("Oats, whole grain, rolled, old fashioned", "dry"),
    ("Eggplant, raw", "raw"),
    ("Spices, coriander leaf, dried", "dehydrated"),
    ("Potatoes, french fried, cross cut, frozen, unprepared", "fried"),
    ("Squash, summer, zucchini, includes skin, frozen, unprepared", "frozen"),
    ("Beans, baked, canned, plain or vegetarian", "canned_with_liquid"),
    ("Biscuits, plain or buttermilk, dry mix", "unspecified"),
    ("13 Foods LLC CHICKPEAS", "unspecified"),
])
def test_classify_preparation(name, state):
    assert classify_preparation(name) == state
    assert state in PREPARATION_STATES


@pytest.mark.parametrize("name, state", [
    # fresh legumes and sweetcorn: "raw" means raw
    ("Peas, edible-podded, raw", "raw"),
    ("Peas, green, raw", "raw"),
    ("Beans, snap, green, raw", "raw"),
    ("Corn, sweet, yellow, raw", "raw"),
    ("Lima beans, immature seeds, raw", "raw"),
    ("Soybeans, green, raw", "raw"),
    # dry pulses and grains: FDC's "raw" is the dry product
    ("Chickpeas (garbanzo beans, bengal gram), mature seeds, raw", "dry"),
    ("Beans, kidney, all types, mature seeds, raw", "dry"),
    ("Lentils, raw", "dry"),
    ("Peas, split, mature seeds, raw", "dry"),
    ("Rice, white, long-grain, raw", "dry"),
    # a pulse name with neither cue is not guessed
    ("Chickpeas, raw", "unknown"),
    ("Beans, pinto, raw", "unknown"),
])
def test_raw_means_dry_only_for_dry_pulses_and_grains(name, state):
    """Codex review on #124: "raw" was turned into "dry" for every pulse
    head, so fresh peas and green beans were labelled Dry."""
    assert classify_preparation(name) == state


def test_unknown_state_has_no_badge_and_no_tie_break():
    assert "unknown" in PREPARATION_STATES
    assert preparation_label("unknown", "en-GB") is None
    # same rank whatever is preferred as an unstated row: no promotion or demotion
    for preferred in (None, "dry", "canned_drained", "raw"):
        assert preparation_rank("unknown", preferred) == preparation_rank("unspecified", preferred)


def test_unknown_rows_are_not_flagged_preparation_not_stated(db):
    _food(db, 1, "Chickpeas, raw")
    _food(db, 2, "13 FOODS CHICKPEAS", data_type="branded_food")
    db.commit()
    labels = {h.food.name: h.preparation_label for h in search_foods_by_name_hits(db, "chickpeas", locale="en-GB")}
    assert labels["Chickpeas, raw"] is None
    assert labels["13 FOODS CHICKPEAS"] == "Preparation not stated"


def test_mangetout_shows_raw_not_dry(db):
    _food(db, 1, "Peas, edible-podded, raw")
    db.commit()
    (hit,) = search_foods_by_name_hits(db, "mangetout", locale="en-GB")
    assert (hit.preparation_state, hit.preparation_label) == ("raw", "Raw")


def test_preparation_labels_follow_locale():
    assert preparation_label("canned_drained", "en-GB") == "Tinned, drained"
    assert preparation_label("canned_drained", "en-US") == "Canned, drained"
    assert preparation_label("unspecified", "en-GB") is None


@pytest.mark.parametrize("query, state", [
    ("chickpeas", "canned_drained"),
    ("kidney beans", "canned_drained"),
    ("baked beans", "canned_drained"),
    ("tomatoes", "canned_drained"),
    ("sweetcorn", "canned_drained"),
    ("lentils", "dry"),
    ("rice", "dry"),
    ("pasta", "dry"),
    ("porridge oats", "dry"),
    ("dried chickpeas", "dry"),
    ("cooked rice", "cooked_boiled"),
    ("carrots", None),
])
def test_uk_default_preparation(query, state):
    assert preferred_preparation(query, "en-GB") == state


def test_preparation_rank_never_excludes():
    ranks = {s: preparation_rank(s, "canned_drained") for s in PREPARATION_STATES}
    assert ranks["canned_drained"] == 0
    assert ranks["canned_with_liquid"] == 1
    assert all(r <= 3 for r in ranks.values())


def test_synonym_table_uses_closed_relationship_vocabulary():
    for table in PHRASE_SYNONYMS.values():
        for key, synonyms in table.items():
            assert key == key.lower().strip()
            for synonym in synonyms:
                assert synonym.relationship in RELATIONSHIPS
    for table in TOKEN_SYNONYMS.values():
        assert all(k == k.lower() for k in table)


def test_plan_en_gb_words_all_have_synonyms():
    """Every word the plan lists for PR 1 is covered (phrase or token)."""
    phrase, token = PHRASE_SYNONYMS["en-GB"], {**TOKEN_SYNONYMS["*"], **TOKEN_SYNONYMS["en-GB"]}
    any_phrase = PHRASE_SYNONYMS["*"]
    for word in ["rocket", "swede", "crisps", "chips", "biscuit", "double cream", "single cream",
                 "caster sugar", "icing sugar", "plain flour", "self-raising flour", "semi-skimmed milk",
                 "wholemeal", "mince", "houmous", "tinned", "rapeseed", "porridge oats", "aubergine",
                 "courgette", "coriander", "spring onion"]:
        assert word in phrase or word in token or word in any_phrase, word


def test_semi_skimmed_is_a_flagged_close_analogue():
    (synonym,) = PHRASE_SYNONYMS["en-GB"]["semi-skimmed milk"]
    assert synonym.relationship == "close_analogue"
    assert synonym.note == "approx. UK semi-skimmed"


def test_chips_and_biscuit_are_locale_rules_only():
    assert "chips" in PHRASE_SYNONYMS["en-GB"] and "chips" not in PHRASE_SYNONYMS["*"]
    assert "biscuit" in PHRASE_SYNONYMS["en-GB"] and "biscuit" not in PHRASE_SYNONYMS["*"]
    assert [v.relationship for v in expand_food_query("chips", "en-US")] == [None]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _food(db, id_, name, data_type="sr_legacy_food", fdc_id=None):
    db.add(Food(id=id_, fdc_id=fdc_id or id_, name=name, data_type=data_type,
                protein_g_per_100g=1.0, amino_acids={}))


def test_token_and_matches_words_in_any_order(db):
    _food(db, 1, "Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids")
    _food(db, 2, "Chicken, canned, no broth")
    db.commit()
    assert [f.id for f in search_foods_by_name(db, "canned chickpeas")] == [1]


def test_generic_ranks_before_branded_even_with_a_closer_name(db):
    _food(db, 1, "CHICKPEAS", data_type="branded_food")
    _food(db, 2, "Chickpeas (garbanzo beans, bengal gram), mature seeds, raw")
    db.commit()
    assert [f.id for f in search_foods_by_name(db, "chickpeas")] == [2, 1]


def test_like_wildcards_in_query_are_literal(db):
    _food(db, 1, "Milk, reduced fat, fluid, 2% milkfat")
    _food(db, 2, "Milk, whole, 3.25% milkfat")
    _food(db, 3, "Milk 200 brand", data_type="branded_food")
    db.commit()
    assert [f.id for f in search_foods_by_name(db, "2% milk")] == [1]


def test_fresh_finds_fdc_raw_rows(db):
    """Recipe lines say "fresh ginger"; FDC says "Ginger root, raw"."""
    _food(db, 1, "Ginger root, raw")
    _food(db, 2, "SESAME GINGER SEAFOOD SALAD, FRESH", data_type="branded_food")
    db.commit()
    assert search_foods_by_name(db, "fresh ginger")[0].id == 1


def test_dried_seeds_are_not_outranked_by_a_paste(db):
    _food(db, 1, "Seeds, sesame butter, paste")
    _food(db, 2, "Seeds, sesame seeds, whole, dried")
    db.commit()
    assert search_foods_by_name(db, "sesame seeds")[0].id == 2


def test_usda_boilerplate_does_not_penalise_the_standard_row(db):
    _food(db, 1, "Peas, edible-podded, frozen, unprepared")
    _food(db, 2, "Peas, green, frozen, unprepared (Includes foods for USDA's Food Distribution Program)")
    db.commit()
    assert search_foods_by_name(db, "frozen peas")[0].id == 2


def test_short_query_still_returns_nothing(db):
    _food(db, 1, "Chickpeas, dry")
    db.commit()
    assert search_foods_by_name_hits(db, "c") == []


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    session = TestSession()
    _food(session, 1, "Milk, reduced fat, fluid, 2% milkfat, with added vitamin A and vitamin D", fdc_id=171267)
    _food(session, 2, "Chickpeas, (garbanzo beans, bengal gram), dry", fdc_id=2644282)
    _food(session, 3, "Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids", fdc_id=173800)
    session.commit()
    session.close()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_search_by_name_returns_preparation_and_note(client):
    res = client.get("/api/foods/search-by-name?q=chickpeas")
    assert res.status_code == 200
    body = res.json()
    assert [r["preparation_label"] for r in body] == ["Tinned, drained", "Dry"]
    assert body[0]["preparation_state"] == "canned_drained"
    assert body[0]["search_note"] is None

    res = client.get("/api/foods/search-by-name?q=semi-skimmed milk")
    (milk,) = res.json()
    assert milk["search_note"] == "approx. UK semi-skimmed"
    assert milk["search_relationship"] == "close_analogue"


def test_other_food_endpoints_leave_search_fields_null(client):
    res = client.get("/api/foods/1")
    assert res.status_code == 200
    assert res.json()["preparation_label"] is None
    assert res.json()["search_note"] is None
