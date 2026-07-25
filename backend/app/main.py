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
    timing for every endpoint independently of this."""
    if not request.url.path.startswith("/api/recommendations"):
        return await call_next(request)

    started_at = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - started_at) * 1000
    _request_logger.info(
        "recommendation_request",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 1),
        },
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
