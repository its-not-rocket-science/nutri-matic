"""A real, working source adapter for any site publishing schema.org/Recipe
JSON-LD — checked live against pinchofnom.com for this project (open
robots.txt, no anti-scraping/anti-AI Terms-of-Use clause, valid Recipe
JSON-LD on its recipe pages), but nothing here is pinchofnom-specific: any
compliant site with the same structured data works.

Compliance is enforced at fetch time, not assumed from a prior check:

    1. robots.txt for the target domain is fetched and consulted (via the
       stdlib urllib.robotparser) for our own User-Agent — a candidate
       whose path is disallowed raises SourceUnavailable rather than being
       fetched. robots.txt itself is cached in-memory per domain for the
       life of one CLI run (repeated recipes from the same domain don't
       each cost a robots.txt round-trip).
    2. USER_AGENT identifies this bot and links back to the project, per
       prompt section 3's "use a descriptive user agent".
    3. A conservative per-domain rate limit is enforced before every live
       request — MIN_REQUEST_INTERVAL_SECONDS by default, or robots.txt's
       own Crawl-delay for our UA/wildcard if it asks for something slower.
    4. Every successfully fetched page is cached to disk under
       <cache_dir>/pages/<domain>/<sha256(url)>.html — a second `fetch`
       call for the same URL (without --force-refresh) never hits the
       network at all, satisfying "avoid repeated downloads" for free.
    5. Transient failures (timeouts, connection errors, 5xx) are retried
       with exponential backoff (RETRY_BACKOFF_SECONDS); anything else
       (404, robots disallow, no Recipe JSON-LD found) fails immediately
       as SourceUnavailable — retrying a 404 just wastes the site's time.

Only recipeIngredient / recipeYield / name / the canonical URL / an
explicit license are ever extracted — recipeInstructions, images, and any
descriptive/editorial text in the JSON-LD are read (they're often
interleaved in the same @graph node) but discarded, never stored.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from .base import RawRecipe, SourceUnavailable

if TYPE_CHECKING:
    from ..manifest import ManifestEntry

NAME = "schema_org"
USER_AGENT = (
    "NutriMaticStockRecipeBot/1.0 "
    "(+https://github.com/its-not-rocket-science/nutri-matic; ingredient-data only, "
    "no method/image/text stored; see docs/stock-recipes.md)"
)
MIN_REQUEST_INTERVAL_SECONDS = 5.0
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
REQUEST_TIMEOUT_SECONDS = 15.0

logger = logging.getLogger(__name__)

_LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)


@dataclass
class _DomainState:
    robots: urllib.robotparser.RobotFileParser
    crawl_delay: float | None
    last_request_at: float = 0.0


class SchemaOrgJsonLdAdapter:
    name = NAME

    def __init__(self, client: httpx.Client | None = None):
        # a caller (tests) can inject a client; the default is real httpx,
        # which is already a project dependency (used elsewhere for the
        # FastAPI test client) — no new dependency added for live fetching
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        )
        self._domains: dict[str, _DomainState] = {}

    # --- robots.txt / rate limiting ------------------------------------

    def _domain_state(self, url: str) -> _DomainState:
        domain = urlparse(url).netloc
        if domain not in self._domains:
            robots = urllib.robotparser.RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
            try:
                resp = self._client.get(robots_url)
                robots.parse(resp.text.splitlines() if resp.status_code < 400 else [])
            except httpx.HTTPError as e:
                logger.warning("could not fetch robots.txt for %s (%s) — treating as disallow-all", domain, e)
                robots.parse(["User-agent: *", "Disallow: /"])
            crawl_delay = robots.crawl_delay(USER_AGENT) or robots.crawl_delay("*")
            self._domains[domain] = _DomainState(robots=robots, crawl_delay=crawl_delay)
        return self._domains[domain]

    def _check_allowed(self, url: str) -> None:
        state = self._domain_state(url)
        if not state.robots.can_fetch(USER_AGENT, url):
            raise SourceUnavailable(f"robots.txt disallows fetching {url} for {USER_AGENT!r}")

    def _wait_for_rate_limit(self, url: str) -> None:
        state = self._domain_state(url)
        interval = max(MIN_REQUEST_INTERVAL_SECONDS, state.crawl_delay or 0.0)
        elapsed = time.monotonic() - state.last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)
        state.last_request_at = time.monotonic()

    # --- caching --------------------------------------------------------

    @staticmethod
    def _cache_path(cache_dir: Path, url: str) -> Path:
        domain = urlparse(url).netloc
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return cache_dir / "pages" / domain / f"{digest}.html"

    def _get_html(self, url: str, cache_dir: Path, force_refresh: bool) -> str:
        cache_path = self._cache_path(cache_dir, url)
        if cache_path.exists() and not force_refresh:
            logger.debug("cache hit for %s", url)
            return cache_path.read_text(encoding="utf-8")

        self._check_allowed(url)
        self._wait_for_rate_limit(url)

        last_error: Exception | None = None
        for attempt, backoff in enumerate((0.0, *RETRY_BACKOFF_SECONDS), start=1):
            if backoff:
                time.sleep(backoff)
            try:
                response = self._client.get(url)
            except httpx.HTTPError as e:
                last_error = e
                logger.warning("fetch attempt %d/%d for %s failed: %s", attempt, RETRY_ATTEMPTS + 1, url, e)
                continue
            if response.status_code == 404:
                raise SourceUnavailable(f"{url} returned 404")
            if response.status_code >= 500:
                last_error = SourceUnavailable(f"{url} returned HTTP {response.status_code}")
                continue
            if response.status_code >= 400:
                raise SourceUnavailable(f"{url} returned HTTP {response.status_code}")

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(response.text, encoding="utf-8")
            return response.text

        raise SourceUnavailable(f"{url} failed after {RETRY_ATTEMPTS + 1} attempts: {last_error}")

    # --- JSON-LD extraction ----------------------------------------------

    @staticmethod
    def _find_recipe_node(html: str) -> dict | None:
        for match in _LD_JSON_RE.finditer(html):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            nodes = data.get("@graph", [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_type = node.get("@type")
                types = node_type if isinstance(node_type, list) else [node_type]
                if "Recipe" in types:
                    return node
        return None

    @staticmethod
    def _parse_servings(recipe_yield) -> float | None:
        if recipe_yield is None:
            return None
        values = recipe_yield if isinstance(recipe_yield, list) else [recipe_yield]
        for value in values:
            match = re.search(r"\d+(?:\.\d+)?", str(value))
            if match:
                return float(match.group(0))
        return None

    def fetch(self, entry: "ManifestEntry", cache_dir: Path, force_refresh: bool = False) -> RawRecipe:
        if not entry.source_url:
            raise SourceUnavailable(f"manifest entry {entry.slug!r} has source=\"fetch\" but no source_url")

        page_html = self._get_html(entry.source_url, cache_dir, force_refresh)
        recipe_node = self._find_recipe_node(page_html)
        if recipe_node is None:
            raise SourceUnavailable(f"no schema.org Recipe JSON-LD found at {entry.source_url}")

        ingredient_lines = [
            html.unescape(str(line)).strip() for line in recipe_node.get("recipeIngredient", []) if str(line).strip()
        ]
        if not ingredient_lines:
            raise SourceUnavailable(f"schema.org Recipe at {entry.source_url} has no recipeIngredient list")

        name = html.unescape(str(recipe_node.get("name") or entry.name))
        servings = self._parse_servings(recipe_node.get("recipeYield"))
        licence = recipe_node.get("license")

        fingerprint_payload = json.dumps(
            {"name": name, "servings": servings, "ingredient_lines": ingredient_lines}, sort_keys=True
        )
        return RawRecipe(
            name=name,
            servings=servings,
            ingredient_lines=ingredient_lines,
            canonical_url=entry.source_url,
            source_licence=str(licence) if licence else None,
            content_fingerprint=hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest(),
        )
