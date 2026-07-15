import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .database import Base, engine
from .routers import (
    api_keys,
    auth,
    clinician,
    collections,
    diary,
    diary_meal_templates,
    entitlements,
    food_prices,
    foods,
    meal_plan,
    meal_plan_templates,
    presets,
    profile,
    public_api,
    recipes,
    search,
    weight,
)

Base.metadata.create_all(bind=engine)

# pg_trgm powers search.py's typo-tolerant fuzzy fallback for food-name
# search — Postgres-only (no SQLite equivalent, which is why that code path
# is gated on the live dialect rather than assumed available). A no-op on
# non-Postgres engines, and idempotent, so safe to run on every startup.
if engine.dialect.name == "postgresql":
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.commit()

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

app.include_router(foods.router)
app.include_router(auth.router)
app.include_router(profile.router)
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


@app.get("/api/health")
def health():
    return {"status": "ok"}
