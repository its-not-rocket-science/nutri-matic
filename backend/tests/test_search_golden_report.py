"""The golden search report as the deploy's rehearse job runs it (plan Q6):
exit status, GitHub annotations, and the non-blocking workflow step."""

import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database, search_golden_report
from app.canonical_foods.csv_schema import load_file
from app.canonical_foods.loader import load
from app.models import Food, FoodNutrient

FIXTURES = Path(__file__).parent / "fixtures"
WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


@pytest.fixture
def catalogue(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    for row in json.loads((FIXTURES / "search_golden_catalogue.json").read_text(encoding="utf-8"))["foods"]:
        session.add(Food(id=row["id"], fdc_id=row["fdc_id"], name=row["name"], data_type=row["data_type"],
                         protein_g_per_100g=1.0, amino_acids={}))
        session.add(FoodNutrient(food_id=row["id"], nutrient_key="energy", amount_per_100g=100.0))
    session.commit()
    load(session, load_file())
    session.commit()
    session.close()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    return engine


def test_all_golden_queries_pass_and_exit_zero(catalogue, capsys):
    assert search_golden_report.main(["--github"]) == 0
    out = capsys.readouterr().out
    assert "After:             34 ✓, 0 ~, 0 ✗" in out
    assert "::warning" not in out


def test_a_regression_exits_one_and_is_annotated(catalogue, capsys, tmp_path):
    golden = json.loads((FIXTURES / "search_golden_en_gb.json").read_text(encoding="utf-8"))
    rocket = next(e for e in golden["queries"] if e["query"] == "rocket")
    rocket["top1"] = {"fdc_ids": [1]}  # nothing in the catalogue has fdc_id 1
    rocket["must_not_in_top5"] = ["arugula"]
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(golden), encoding="utf-8")

    assert search_golden_report.main(["--golden", str(path), "--github"]) == 1
    out = capsys.readouterr().out
    warnings = [line for line in out.splitlines() if line.startswith("::warning")]
    assert any("'rocket': top result is" in w for w in warnings)
    assert any("'rocket': must-not hit" in w for w in warnings)
    assert "**Regressions:**" in out
    assert all("\n" not in w for w in warnings)


def test_slow_queries_warn_but_do_not_fail(catalogue, capsys, monkeypatch):
    monkeypatch.setattr(search_golden_report, "SLOW_QUERY_SECONDS", 0.0)
    assert search_golden_report.main(["--github"]) == 0
    out = capsys.readouterr().out
    assert "**Slow queries:**" in out
    assert sum(1 for line in out.splitlines() if line.startswith("::warning")) == 34


def test_without_github_flag_no_annotations(catalogue, capsys, monkeypatch):
    monkeypatch.setattr(search_golden_report, "SLOW_QUERY_SECONDS", 0.0)
    search_golden_report.main([])
    assert "::warning" not in capsys.readouterr().out


# --- the deploy workflow step ----------------------------------------------

def _rehearse_steps():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["rehearse-migration"]["steps"]


def test_rehearse_job_runs_the_report_last_and_non_blocking():
    steps = _rehearse_steps()
    names = [s.get("name") for s in steps]
    report = next(i for i, n in enumerate(names) if n and n.startswith("Golden search report"))
    assert report == len(steps) - 1
    assert names.index("Rehearse downgrade and re-upgrade") < report  # measures the final migrated state
    step = steps[report]
    assert step["continue-on-error"] is True
    assert step.get("timeout-minutes")
    assert step["env"]["DATABASE_URL"].endswith("/rehearsal")  # the throwaway copy, never production
    assert "app.search_golden_report --github" in step["run"]
    assert "GITHUB_STEP_SUMMARY" in step["run"]
    assert 'exit "$status"' in step["run"]


def test_report_is_read_only_against_postgres():
    source = Path(search_golden_report.__file__).read_text(encoding="utf-8")
    assert "SET default_transaction_read_only = on" in source
