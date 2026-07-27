"""Public-launch hardening prompt 6: request-level telemetry in
app/main.py — recommendation mode tagging, elevated-status logging for
both the recommendation-specific and the general middleware."""

import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.main import _recommendation_mode, log_elevated_status_responses, log_recommendation_endpoint_latency


@pytest.mark.parametrize(
    "path,expected_mode",
    [
        ("/api/recommendations/ingredients", "ingredients"),
        ("/api/recommendations/recipes", "recipes"),
        ("/api/recommendations/pairs", "pairs"),
        ("/api/recommendations/substitutions", "substitutions"),
        ("/api/recommendations/substitutions/apply", "substitutions"),
        ("/api/recommendations", "unknown"),
    ],
)
def test_recommendation_mode_parses_the_path_suffix(path, expected_mode):
    assert _recommendation_mode(path) == expected_mode


@pytest.fixture
def test_client():
    test_app = FastAPI()
    test_app.middleware("http")(log_elevated_status_responses)
    test_app.middleware("http")(log_recommendation_endpoint_latency)

    @test_app.get("/api/recommendations/ingredients")
    def ok_recommendation():
        return {"ok": True}

    @test_app.get("/api/recommendations/recipes")
    def failing_recommendation():
        raise HTTPException(status_code=500, detail="boom")

    @test_app.get("/api/other")
    def failing_other():
        raise HTTPException(status_code=500, detail="boom")

    @test_app.get("/api/other-ok")
    def ok_other():
        return {"ok": True}

    return TestClient(test_app, raise_server_exceptions=False)


def test_recommendation_request_logs_mode_and_duration_at_info_on_success(test_client, caplog):
    with caplog.at_level(logging.INFO, logger="app.requests"):
        res = test_client.get("/api/recommendations/ingredients")
    assert res.status_code == 200
    records = [r for r in caplog.records if r.message == "recommendation_request"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].mode == "ingredients"
    assert records[0].status_code == 200
    assert hasattr(records[0], "duration_ms")


def test_recommendation_request_logs_at_error_on_5xx(test_client, caplog):
    # ERROR, not WARNING: LoggingIntegration's event_level=ERROR is what
    # actually turns this into a Sentry event rather than a breadcrumb.
    with caplog.at_level(logging.INFO, logger="app.requests"):
        res = test_client.get("/api/recommendations/recipes")
    assert res.status_code == 500
    records = [r for r in caplog.records if r.message == "recommendation_request"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].mode == "recipes"


def test_general_elevated_status_middleware_logs_5xx_for_any_path(test_client, caplog):
    with caplog.at_level(logging.INFO, logger="app.requests"):
        res = test_client.get("/api/other")
    assert res.status_code == 500
    records = [r for r in caplog.records if r.message == "elevated_status_response"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].path == "/api/other"


def test_general_elevated_status_middleware_is_silent_on_success(test_client, caplog):
    """Deliberately no INFO-level logging for every successful request
    app-wide — that would be pure noise at real traffic volume."""
    with caplog.at_level(logging.INFO, logger="app.requests"):
        res = test_client.get("/api/other-ok")
    assert res.status_code == 200
    records = [r for r in caplog.records if r.message == "elevated_status_response"]
    assert records == []
