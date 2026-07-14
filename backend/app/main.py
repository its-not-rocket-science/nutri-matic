from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .database import Base, engine
from .routers import (
    auth,
    collections,
    diary,
    diary_meal_templates,
    food_prices,
    foods,
    meal_plan,
    meal_plan_templates,
    presets,
    profile,
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

app = FastAPI(title="Nutri-Matic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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


@app.get("/api/health")
def health():
    return {"status": "ok"}
