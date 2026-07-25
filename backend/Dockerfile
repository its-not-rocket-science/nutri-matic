FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .

# Runs migrations before serving traffic — the schema-evolution mechanism
# is now Alembic, not Base.metadata.create_all() (see docs/migrations.md).
# This is safe to run on every container start (a no-op once the database
# is already at head) EXCEPT the very first deploy of this image against
# a database that predates Alembic adoption — that database must be
# `alembic stamp`ped once, out of band, before this image ever runs
# against it, or `alembic upgrade head` will try to recreate tables that
# already exist and fail loudly (which is the correct, safe failure mode
# — see docs/migrations.md rather than silently guessing).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
