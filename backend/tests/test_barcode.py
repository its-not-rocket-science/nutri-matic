import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.barcode import equivalent_codes, find_food_by_barcode
from app.database import Base, get_db
from app.main import app
from app.models import Food
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestSession()
    db.add(
        Food(
            id=1,
            name="Acme Cereal Bar",
            protein_g_per_100g=8,
            amino_acids=dict.fromkeys(AMINO_ACIDS, None),
            data_type="branded_food",
            gtin_upc="012345678905",
        )
    )
    db.add(
        Food(
            id=2,
            name="chicken breast, raw",
            protein_g_per_100g=23,
            amino_acids=dict.fromkeys(AMINO_ACIDS, 20),
            data_type="foundation_food",
        )
    )
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lookup_by_barcode_finds_food(client):
    res = client.get("/api/foods/barcode/012345678905")
    assert res.status_code == 200
    assert res.json()["name"] == "Acme Cereal Bar"


def test_lookup_unknown_barcode_404s(client):
    res = client.get("/api/foods/barcode/999999999999")
    assert res.status_code == 404


def test_food_without_barcode_has_null_gtin_upc(client):
    res = client.get("/api/foods/2")
    assert res.status_code == 200
    assert res.json()["gtin_upc"] is None


# --- width equivalence (canonical-foods plan PR 2, section 3.6 #4) -------


def _branded(db, id_, gtin, fdc_id=None, name=None):
    db.add(Food(
        id=id_, fdc_id=fdc_id or id_, name=name or f"Product {id_}", protein_g_per_100g=1,
        amino_acids=dict.fromkeys(AMINO_ACIDS, None), data_type="branded_food", gtin_upc=gtin,
    ))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_equivalent_codes_cover_every_padded_width_up_to_gtin14():
    assert equivalent_codes("5034660520665") == ["5034660520665", "05034660520665"]
    assert equivalent_codes("012345678905") == [
        "012345678905", "12345678905", "0012345678905", "00012345678905",
    ]
    assert equivalent_codes("00012345678905")[0] == "00012345678905"
    assert set(equivalent_codes("00012345678905")) == set(equivalent_codes("12345678905"))


@pytest.mark.parametrize("code", ["ABC123", "5000-183", "５０００１８３", "123456789012345"])
def test_non_gtin_input_is_only_itself(code):
    """Non-digit (including full-width digits) and over-14-digit input is
    not normalised."""
    assert equivalent_codes(code) == [code]


@pytest.mark.parametrize("scanned", ["5034660520665", "05034660520665"])
def test_ean13_scan_finds_row_stored_as_gtin14(db, scanned):
    """Hand-test list rows 7-12: the pack's EAN-13 vs FDC's zero-padded 14."""
    _branded(db, 1, "05034660520665", name="CADBURY CREME EGG")
    db.commit()
    assert find_food_by_barcode(db, scanned).name == "CADBURY CREME EGG"


@pytest.mark.parametrize("scanned", ["012345678905", "12345678905", "0012345678905", "00012345678905"])
def test_upc_a_ean13_gtin14_and_short_forms_are_equivalent(db, scanned):
    _branded(db, 1, "012345678905")
    db.commit()
    assert find_food_by_barcode(db, scanned).id == 1


def test_gtin8_padded_to_wider_widths(db):
    _branded(db, 1, "96385074")
    db.commit()
    assert find_food_by_barcode(db, "0000096385074").id == 1
    assert find_food_by_barcode(db, "00000096385074").id == 1


def test_collision_exact_width_wins(db):
    """904 products have both a 13-digit and a 0-padded 14-digit row. Each
    exact form keeps returning its own row."""
    _branded(db, 1, "5000183036853", fdc_id=100)
    _branded(db, 2, "05000183036853", fdc_id=200)
    db.commit()
    assert find_food_by_barcode(db, "5000183036853").id == 1
    assert find_food_by_barcode(db, "05000183036853").id == 2


def test_collision_without_exact_takes_least_padding(db):
    _branded(db, 1, "0012345678905", fdc_id=900)
    _branded(db, 2, "012345678905", fdc_id=100)
    db.commit()
    assert find_food_by_barcode(db, "00012345678905").id == 2
    assert find_food_by_barcode(db, "12345678905").id == 2


def test_different_numbers_never_match(db):
    _branded(db, 1, "012345678905")
    db.commit()
    assert find_food_by_barcode(db, "112345678905") is None
    assert find_food_by_barcode(db, "01234567890") is None  # a digit dropped, not padding


def test_non_digit_stored_code_still_needs_exact_match(db):
    _branded(db, 1, "ABC123")
    db.commit()
    assert find_food_by_barcode(db, "ABC123").id == 1
    assert find_food_by_barcode(db, "0ABC123") is None


def test_api_non_digit_input_still_404s(client):
    res = client.get("/api/foods/barcode/not-a-barcode")
    assert res.status_code == 404
    assert res.json() == {"detail": "No food found for that barcode"}


def test_api_existing_exact_hit_unchanged(client):
    res = client.get("/api/foods/barcode/012345678905")
    assert res.status_code == 200
    assert res.json()["gtin_upc"] == "012345678905"


def test_api_ean13_scan_of_upc_a_row(client):
    res = client.get("/api/foods/barcode/0012345678905")
    assert res.status_code == 200
    assert res.json()["name"] == "Acme Cereal Bar"
    assert res.json()["gtin_upc"] == "012345678905"
