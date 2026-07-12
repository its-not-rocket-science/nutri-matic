from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import foods

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Nutri-Matic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(foods.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
