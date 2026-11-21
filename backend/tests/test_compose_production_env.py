"""Run the backend's production startup checks with exactly the
environment the production container receives.

That environment is docker-compose.yml's backend `environment:` block,
interpolated against the server's .env. The server .env is simulated here
with the variables it holds (JWT_SECRET, DATABASE_URL, CORS_ORIGINS), plus
RELEASE_VERSION, which the deploy wrapper exports. The app is then
imported in a subprocess whose environment is that mapping and nothing
else (bar the few OS variables Python itself needs), so nothing from the
developer's or CI's own environment can mask a missing variable.
"""

import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

_INTERPOLATION = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?:(?P<op>:-|:\?)(?P<arg>[^}]*))?\}")


class ComposeInterpolationError(Exception):
    pass


def _interpolate(value: str, dotenv: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        name, op, arg = match["name"], match["op"], match["arg"]
        current = dotenv.get(name, "")
        if op is None:
            return current
        if op == ":-":
            return current or arg
        if not current:  # ":?"
            raise ComposeInterpolationError(f"{name}: {arg}")
        return current

    if "$" in _INTERPOLATION.sub("", value):
        raise AssertionError(f"unsupported compose interpolation in {value!r}; extend this test")
    return _INTERPOLATION.sub(replace, value)


def production_container_env(dotenv: dict[str, str]) -> dict[str, str]:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    raw = compose["services"]["backend"]["environment"]
    assert isinstance(raw, dict), "backend environment must be a mapping"
    return {key: _interpolate(str(value), dotenv) for key, value in raw.items()}


def server_dotenv() -> dict[str, str]:
    return {
        "JWT_SECRET": secrets.token_hex(32),
        "DATABASE_URL": "postgresql://nutrimatic:not-the-real-one@postgres:5432/nutrimatic",
        "CORS_ORIGINS": "https://nutri-matic.uk",
        "RELEASE_VERSION": "0" * 40,
    }


_PROBE = """
import json, os
import app.main  # runs every import-time startup check
from app import monitoring
print("PROBE" + json.dumps({
    "app_env": os.environ.get("APP_ENV"),
    "monitoring_initialised": monitoring.is_initialized(),
}))
"""


def run_startup(container_env: dict[str, str]) -> subprocess.CompletedProcess:
    # Only what the interpreter needs to run at all on this OS.
    os_needs = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ}
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(BACKEND_DIR),
        env={**os_needs, **container_env},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_compose_runs_the_backend_in_production_mode():
    assert production_container_env(server_dotenv())["APP_ENV"] == "production"


def test_production_startup_validation_passes_with_exactly_the_compose_environment():
    env = production_container_env(server_dotenv())

    result = run_startup(env)

    assert result.returncode == 0, result.stderr
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("PROBE"))
    assert json.loads(line[len("PROBE"):]) == {"app_env": "production", "monitoring_initialised": False}
    # Monitoring is intentionally unconfigured: no ERROR on every start.
    assert "monitoring_not_configured" not in result.stderr


def test_production_startup_refuses_without_redis_url():
    env = production_container_env(server_dotenv())
    env.pop("REDIS_URL")

    result = run_startup(env)

    assert result.returncode != 0
    assert "REDIS_URL is not set and APP_ENV=production" in result.stderr


def test_compose_refuses_to_build_the_environment_without_jwt_secret():
    dotenv = server_dotenv()
    del dotenv["JWT_SECRET"]
    with pytest.raises(ComposeInterpolationError, match="JWT_SECRET"):
        production_container_env(dotenv)
