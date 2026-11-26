import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://nutrimatic:nutrimatic@localhost:5432/nutrimatic"
)

# pool_pre_ping checks each pooled connection before handing it out, so a
# postgres restart (see docs/runbooks/rotate-db-password.md, Step 4) doesn't
# fail the first request that picks up a connection the restart killed.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
