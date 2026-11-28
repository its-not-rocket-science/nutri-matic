"""Golden en-GB food-search tests (SQLite, no catalogue needed).

The 34 queries from docs/plans/canonical-foods-plan.md section 1.2 run
against a mini catalogue of real public FDC names and fdc_ids
(fixtures/search_golden_catalogue.json): the generic rows a good answer
needs plus the branded rows that beat them before (Rocket Science Games,
Wasabrod Ab Sweden, Artforum EGGPLANT DIP, HOUSE KOMBUCHA, Double Cream
Brie, SUGAR COOKIES, six versions of Ahold BAKED BEANS, ...).

The plan's 1.2 table is the "before"; these assert the "after". The same
grading (`app.search_golden_report.judge`) drives the full-catalogue
report, `python -m app.search_golden_report`.

Every golden query runs twice: on the token-ranked search alone (empty
canonical tables, as on a database whose canonical load was skipped), and
with the reviewed canonical CSV loaded (search tier 1, PR 4b). The fixture
holds every canonical anchor row, so the real file loads.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.canonical_foods.csv_schema import load_file
from app.canonical_foods.loader import load
from app.database import Base
from app.models import Food
from app.search import search_foods_by_name_hits
from app.search_golden_report import judge, load_golden, must_not_violations

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = load_golden(FIXTURES / "search_golden_en_gb.json")


def _catalogue_session(with_canonical: bool):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    catalogue = json.loads((FIXTURES / "search_golden_catalogue.json").read_text(encoding="utf-8"))
    for row in catalogue["foods"]:
        session.add(Food(
            id=row["id"], fdc_id=row["fdc_id"], name=row["name"], data_type=row["data_type"],
            protein_g_per_100g=1.0, amino_acids={},
        ))
    session.commit()
    if with_canonical:
        # sign-off is gated separately (test_canonical_foods); this tests
        # what the file does to search
        load(session, load_file(require_signoff=False))
        session.commit()
    return session


@pytest.fixture(scope="module")
def db():
    session = _catalogue_session(with_canonical=False)
    yield session
    session.close()


@pytest.fixture(scope="module")
def canonical_db():
    session = _catalogue_session(with_canonical=True)
    yield session
    session.close()


@pytest.fixture(params=["token", "canonical"])
def golden_db(request, db, canonical_db):
    return db if request.param == "token" else canonical_db


def _search(db, query):
    return search_foods_by_name_hits(db, query, limit=15, locale=GOLDEN["locale"])


def test_golden_file_covers_the_plans_34_queries():
    queries = [e["query"] for e in GOLDEN["queries"]]
    assert len(queries) == 34
    assert len(set(queries)) == 34


@pytest.mark.parametrize("entry", GOLDEN["queries"], ids=lambda e: f"{e['n']}-{e['query']}")
def test_golden_query(golden_db, entry):
    hits = _search(golden_db, entry["query"])
    names = [h.food.name for h in hits]

    assert not must_not_violations(entry, names), names[:5]

    if entry.get("known_gap"):
        return

    top = hits[0]
    assert judge(entry, [(h.food.fdc_id, h.food.name, h.food.data_type) for h in hits]) == "ok", names[:5]
    if "state" in entry:
        assert top.preparation_state == entry["state"], (top.food.name, top.preparation_state)
    if "note" in entry:
        assert top.note == entry["note"]


def test_branded_versions_collapse_to_one_newest_result(db):
    """Ahold BAKED BEANS has six FDC versions in the fixture; search shows
    one, the newest (highest fdc_id)."""
    hits = _search(db, "baked beans")
    ahold = [h.food for h in hits if h.food.name == "Ahold Usa, Inc. BAKED BEANS"]
    assert len(ahold) == 1
    assert ahold[0].fdc_id == 1658677


def test_every_result_shows_preparation_where_it_matters(db):
    """Dry and tinned chickpeas must be told apart in the result list: each
    generic row carries a state label, and a branded row that does not
    state one is labelled as such rather than left blank."""
    hits = _search(db, "chickpeas")
    labels = {h.food.name: h.preparation_label for h in hits}
    assert labels["Chickpeas, (garbanzo beans, bengal gram), dry"] == "Dry"
    assert labels["Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids"] == "Tinned, drained"
    assert labels["13 Foods LLC CHICKPEAS"] == "Preparation not stated"


def test_preparation_default_is_a_tie_break_not_a_filter(db):
    """Chickpeas default to tinned for UK users, but the dry and cooked rows
    are still returned."""
    states = {h.preparation_state for h in _search(db, "chickpeas")}
    assert {"canned_drained", "dry", "cooked_boiled"} <= states


def test_semi_skimmed_note_shown_on_every_result_it_resolves(db):
    hits = _search(db, "semi-skimmed milk")
    via_synonym = [h for h in hits if "2%" in h.food.name]
    assert via_synonym
    assert all(h.note == "approx. UK semi-skimmed" and h.relationship == "close_analogue" for h in via_synonym)


def test_chips_and_biscuit_keep_us_meaning_under_en_us(db):
    chips = search_foods_by_name_hits(db, "chips", limit=15, locale="en-US")
    assert "french fr" not in chips[0].food.name.lower()
    biscuit = search_foods_by_name_hits(db, "biscuit", limit=15, locale="en-US")
    assert biscuit[0].food.name.lower().startswith("biscuits")


def test_literal_meaning_still_reachable_after_locale_meaning(db):
    """en-GB 'chips' ranks fries first but taro chips etc. are still in the
    list (ranked after), never hidden."""
    names = [h.food.name for h in search_foods_by_name_hits(db, "chips", limit=200, locale="en-GB")]
    assert any("taro chips" in n for n in names)
    first_taro = next(i for i, n in enumerate(names) if "taro chips" in n)
    assert all("french fr" in n.lower() or "french fries" in n.lower() for n in names[:3])
    assert first_taro > 3
