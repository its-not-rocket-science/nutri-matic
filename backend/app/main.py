import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .monitoring import init_monitoring
from .routers import (
    account,
    api_keys,
    auth,
    clinician,
    collections,
    diary,
    diary_meal_templates,
    entitlements,
    food_prices,
    foods,
    health,
    meal_plan,
    meal_plan_templates,
    presets,
    profiles,
    public_api,
    recipes,
    recommendations,
    search,
    weight,
)

# Schema creation/evolution is Alembic's job now (see docs/migrations.md),
# not this module's — `alembic upgrade head` (run before this process
# starts; see the Dockerfile) creates every table and the pg_trgm
# extension search.py's fuzzy fallback needs. Production-hardening
# prompt 1 replaced the previous `Base.metadata.create_all()` +
# opportunistic `CREATE EXTENSION` pair that used to live here.

# No-op unless SENTRY_DSN is set — see app/monitoring.py and
# docs/monitoring.md (operational-hardening prompt 5).
init_monitoring()

app = FastAPI(
    title="Nutri-Matic API",
    description=(
        "Nutrition analysis and optimisation engine — protein quality (DIAAS/PDCAAS), "
        "micronutrient sufficiency against personalized DRVs, bioavailability-adjusted iron "
        "absorption, and computed (not folk-wisdom) food complementarity. Not a calorie counter: "
        "energy tracking exists, but every endpoint here is built around nutritional quality, not "
        "quantity."
    ),
)


def _parse_cors_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


# CORS_ORIGINS: comma-separated allowlist. Defaults to the SvelteKit dev
# server's origin so local development needs no configuration; a real
# deployment must set this to its actual frontend origin(s) — see
# DEPLOYMENT.md.
CORS_ORIGINS = _parse_cors_origins(os.environ.get("CORS_ORIGINS", "http://localhost:5173"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_request_logger = logging.getLogger("app.requests")


def _recommendation_mode(path: str) -> str:
    """Public-launch hardening prompt 6 item 2: "recommendation latency
    and error rates BY MODE" — the prior log line had path/status/
    duration but never pulled out which of the four recommendation
    modes a request was for, leaving that buried in the path string
    rather than a queryable field."""
    suffix = path.removeprefix("/api/recommendations").lstrip("/")
    return suffix.split("/")[0] if suffix else "unknown"


@app.middleware("http")
async def log_recommendation_endpoint_latency(request: Request, call_next):
    """Operational-hardening prompt 5: "recommendation endpoint latency"
    and "recommendation endpoint error rate". Scoped to `/api/
    recommendations/*` specifically rather than every request — that's
    the one prompt actually asks to be watched closely (it's the
    heaviest read path and the one write path this feature has), not a
    general-purpose request logger. A plain stdlib logger call, so it's
    useful in self-hosted logs with or without Sentry configured; when
    Sentry is active its own performance monitoring
    (`traces_sample_rate`, see app/monitoring.py) captures per-request
    timing for every endpoint independently of this.

    Public-launch hardening prompt 6: also tags `mode`
    (ingredients/recipes/pairs/substitutions — see `_recommendation_mode`),
    and logs at ERROR (not INFO) when the response is a server error.
    ERROR, not WARNING: `init_monitoring()`'s `LoggingIntegration` is
    configured with `event_level=logging.ERROR` — a WARNING here would
    only ever become a breadcrumb attached to some later, unrelated
    captured event, never a Sentry event/alert of its own (caught by
    review; verified directly against the `LoggingIntegration` config
    rather than assumed)."""
    if not request.url.path.startswith("/api/recommendations"):
        return await call_next(request)

    started_at = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - started_at) * 1000
    log_extra = {
        "path": request.url.path,
        "method": request.method,
        "mode": _recommendation_mode(request.url.path),
        "status_code": response.status_code,
        "duration_ms": round(duration_ms, 1),
    }
    if response.status_code >= 500:
        _request_logger.error("recommendation_request", extra=log_extra)
    else:
        _request_logger.info("recommendation_request", extra=log_extra)
    return response


@app.middleware("http")
async def log_elevated_status_responses(request: Request, call_next):
    """Public-launch hardening prompt 6 item 2: "elevated 5xx responses"
    — general, app-wide (unlike the recommendation-specific middleware
    above), but deliberately silent on success: logging every request at
    INFO app-wide would be pure noise at real traffic volume with no
    signal this app's own telemetry needs. Only a 5xx gets a log line
    here, at ERROR (not WARNING) — `LoggingIntegration`'s `event_level`
    is ERROR, so this is what actually reaches Sentry as an event when
    monitoring is active; WARNING would only ever be a breadcrumb."""
    response = await call_next(request)
    if response.status_code >= 500:
        _request_logger.error(
            "elevated_status_response",
            extra={"path": request.url.path, "method": request.method, "status_code": response.status_code},
        )
    return response


app.include_router(foods.router)
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(profiles.router)
app.include_router(recipes.router)
app.include_router(diary.router)
app.include_router(search.router)
app.include_router(presets.router)
app.include_router(collections.router)
app.include_router(meal_plan.router)
app.include_router(food_prices.router)
app.include_router(meal_plan_templates.router)
app.include_router(diary_meal_templates.router)
app.include_router(weight.router)
app.include_router(entitlements.router)
app.include_router(api_keys.router)
app.include_router(public_api.router)
app.include_router(clinician.router)
app.include_router(recommendations.router)
app.include_router(health.router)
