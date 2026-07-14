import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food
from app.reference_patterns import AMINO_ACIDS


def _aa(lysine: float, others: float = 100.0) -> dict:
    return {aa: (lysine if aa == "lysine" else others) for aa in AMINO_ACIDS}


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
    # grain: low lysine (20 mg/g protein, pattern wants 48) — everything else comfortably high
    grain = Food(
        id=1,
        name="grain",
        protein_g_per_100g=20,
        amino_acids=_aa(lysine=20),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9),
        digestibility_pdcaas=0.9,
    )
    # legume: very high lysine — the strong complement
    legume = Food(
        id=2,
        name="legume",
        protein_g_per_100g=20,
        amino_acids=_aa(lysine=200),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9),
        digestibility_pdcaas=0.9,
    )
    # mediocre: slightly higher lysine than grain, but still limiting — a weaker complement
    mediocre = Food(
        id=3,
        name="mediocre",
        protein_g_per_100g=20,
        amino_acids=_aa(lysine=30),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9),
        digestibility_pdcaas=0.9,
    )
    # no digestibility data at all — shouldn't be suggested (can't itself be scored in a combo)
    unscorable = Food(
        id=4, name="unscorable", protein_g_per_100g=20, amino_acids=_aa(lysine=200)
    )
    db.add_all([grain, legume, mediocre, unscorable])
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_complement_suggests_and_ranks_by_improvement(client):
    res = client.get("/api/foods/1/complement?method=diaas")
    assert res.status_code == 200
    body = res.json()
    assert body["limiting_amino_acid"] == "lysine"
    assert body["original_score"] == pytest.approx(20 * 0.9 / 48 * 100)

    suggestions = body["suggestions"]
    assert len(suggestions) == 2  # legume and mediocre; unscorable excluded
    names = [s["food_name"] for s in suggestions]
    assert names == ["legume", "mediocre"]  # legume's bigger improvement ranked first
    assert suggestions[0]["score_improvement"] > suggestions[1]["score_improvement"] > 0
    assert suggestions[0]["combined_score"] > body["original_score"]


def test_complement_excludes_self(client):
    res = client.get("/api/foods/1/complement?method=diaas")
    ids = [s["food_id"] for s in res.json()["suggestions"]]
    assert 1 not in ids


def test_complement_pdcaas_method(client):
    res = client.get("/api/foods/1/complement?method=pdcaas")
    assert res.status_code == 200
    assert len(res.json()["suggestions"]) == 2


def test_complement_404_unknown_food(client):
    res = client.get("/api/foods/999/complement")
    assert res.status_code == 404


def test_complement_422_when_subject_unscorable(client):
    res = client.get("/api/foods/4/complement?method=diaas")
    assert res.status_code == 422


def test_complement_empty_when_nothing_improves(client):
    # a food that's already excellent in every amino acid has nothing to gain from pairing
    res = client.get("/api/foods/2/complement?method=diaas")
    assert res.status_code == 200
    assert res.json()["suggestions"] == []
