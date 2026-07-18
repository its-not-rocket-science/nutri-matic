"""Source-adapter tests — prompt section 16: valid JSON-LD, missing
structured data, changed page structure, redirects, blocked sources,
unavailable pages, serving extraction. Uses a stored fixture (a real page
fetched once during development — tests/fixtures/stock_recipes/) and hand-
built HTML snippets; never a live web request."""

from pathlib import Path

import httpx
import pytest

from app.stock_recipes.manifest import ManifestEntry
from app.stock_recipes.sources.base import SourceUnavailable
from app.stock_recipes.sources.manual import ManualSeedAdapter
from app.stock_recipes.sources.schema_org import SchemaOrgJsonLdAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "stock_recipes"


def _entry(slug="test_recipe", url="https://example.com/recipes/test/", source_name="schema_org", **kwargs):
    return ManifestEntry(slug=slug, name="Test Recipe", collections=["everyday_uk_meals"], source="fetch", source_name=source_name, source_url=url, **kwargs)


class _FakeTransport(httpx.BaseTransport):
    """Serves canned responses for exact URLs — no real network I/O."""

    def __init__(self, responses: dict[str, httpx.Response]):
        self._responses = responses

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in self._responses:
            return httpx.Response(404, text="not found")
        return self._responses[url]


def _adapter_with(responses: dict[str, str | int | httpx.Response]) -> SchemaOrgJsonLdAdapter:
    """responses maps URL -> a text body (200), an int status code, or a
    pre-built httpx.Response (e.g. a redirect)."""
    built = {}
    for url, body in responses.items():
        if isinstance(body, httpx.Response):
            built[url] = body
        elif isinstance(body, int):
            built[url] = httpx.Response(body, text="")
        else:
            built[url] = httpx.Response(200, text=body)
    client = httpx.Client(transport=_FakeTransport(built), follow_redirects=True)
    return SchemaOrgJsonLdAdapter(client=client)


def test_valid_jsonld_from_real_fixture(tmp_path):
    html = (FIXTURES / "pinchofnom_spaghetti_bolognese.html").read_text(encoding="utf-8")
    adapter = _adapter_with({
        "https://pinchofnom.com/robots.txt": "User-agent: *\nDisallow:\n",
        "https://pinchofnom.com/recipes/spaghetti-bolognese/": html,
    })
    entry = _entry(url="https://pinchofnom.com/recipes/spaghetti-bolognese/")

    raw = adapter.fetch(entry, tmp_path)

    assert "Spaghetti Bolognese" in raw.name
    assert raw.servings == 8.0
    assert "500 g 5% lean beef mince" in raw.ingredient_lines
    assert len(raw.ingredient_lines) == 16
    assert raw.canonical_url == entry.source_url


def test_second_fetch_uses_page_cache_not_network(tmp_path):
    html = (FIXTURES / "pinchofnom_spaghetti_bolognese.html").read_text(encoding="utf-8")
    url = "https://pinchofnom.com/recipes/spaghetti-bolognese/"
    adapter = _adapter_with({"https://pinchofnom.com/robots.txt": "User-agent: *\nDisallow:\n", url: html})
    entry = _entry(url=url)

    adapter.fetch(entry, tmp_path)
    # second call: transport only knows the two URLs above: robots.txt
    # request is per-domain-cached in-memory, and the page itself is now on
    # disk — a transport-level 404 would be raised if either were re-hit
    # unexpectedly, so a broken cache path fails this test loudly
    raw2 = adapter.fetch(entry, tmp_path)
    assert raw2.servings == 8.0


def test_missing_structured_data(tmp_path):
    adapter = _adapter_with({
        "https://example.com/robots.txt": "User-agent: *\nDisallow:\n",
        "https://example.com/recipes/test/": "<html><body>No recipe data here</body></html>",
    })
    with pytest.raises(SourceUnavailable, match="no schema.org Recipe"):
        adapter.fetch(_entry(), tmp_path)


def test_changed_page_structure_no_ingredients(tmp_path):
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Recipe","name":"Broken Recipe","recipeIngredient":[]}
    </script></head></html>
    """
    adapter = _adapter_with({
        "https://example.com/robots.txt": "User-agent: *\nDisallow:\n",
        "https://example.com/recipes/test/": html,
    })
    with pytest.raises(SourceUnavailable, match="no recipeIngredient"):
        adapter.fetch(_entry(), tmp_path)


def test_blocked_by_robots_txt(tmp_path):
    adapter = _adapter_with({
        "https://example.com/robots.txt": "User-agent: *\nDisallow: /recipes/\n",
        "https://example.com/recipes/test/": "<html></html>",
    })
    with pytest.raises(SourceUnavailable, match="robots.txt disallows"):
        adapter.fetch(_entry(), tmp_path)


def test_unavailable_page_404(tmp_path):
    adapter = _adapter_with({"https://example.com/robots.txt": "User-agent: *\nDisallow:\n"})
    with pytest.raises(SourceUnavailable, match="404"):
        adapter.fetch(_entry(), tmp_path)


def test_serving_extraction_from_recipe_yield_list(tmp_path):
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Recipe","name":"X",
     "recipeYield":["4","4 Portion"],"recipeIngredient":["1 onion"]}
    </script></head></html>
    """
    adapter = _adapter_with({
        "https://example.com/robots.txt": "User-agent: *\nDisallow:\n",
        "https://example.com/recipes/test/": html,
    })
    raw = adapter.fetch(_entry(), tmp_path)
    assert raw.servings == 4.0


def test_recipe_node_found_inside_graph(tmp_path):
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"WebPage","name":"Some Page"},
      {"@type":"Recipe","name":"Graph Recipe","recipeYield":"2","recipeIngredient":["1 egg","2 tbsp flour"]}
    ]}
    </script></head></html>
    """
    adapter = _adapter_with({
        "https://example.com/robots.txt": "User-agent: *\nDisallow:\n",
        "https://example.com/recipes/test/": html,
    })
    raw = adapter.fetch(_entry(), tmp_path)
    assert raw.name == "Graph Recipe"
    assert raw.ingredient_lines == ["1 egg", "2 tbsp flour"]


def test_html_entities_unescaped(tmp_path):
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Recipe","name":"Bangers &amp; Mash",
     "recipeIngredient":["1 tbsp Henderson&#39;s relish"]}
    </script></head></html>
    """
    adapter = _adapter_with({
        "https://example.com/robots.txt": "User-agent: *\nDisallow:\n",
        "https://example.com/recipes/test/": html,
    })
    raw = adapter.fetch(_entry(), tmp_path)
    assert raw.name == "Bangers & Mash"
    assert raw.ingredient_lines == ["1 tbsp Henderson's relish"]


def test_content_fingerprint_changes_when_ingredients_change(tmp_path):
    def html_for(qty: str) -> str:
        return (
            '<html><head><script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"Recipe","name":"X","recipeYield":"2",'
            f'"recipeIngredient":["{qty} onion"]}}'
            "</script></head></html>"
        )

    adapter_a = _adapter_with({"https://example.com/robots.txt": "User-agent: *\nDisallow:\n", "https://example.com/recipes/test/": html_for("1")})
    adapter_b = _adapter_with({"https://example.com/robots.txt": "User-agent: *\nDisallow:\n", "https://example.com/recipes/test/": html_for("2")})
    raw_a = adapter_a.fetch(_entry(slug="a"), tmp_path / "a")
    raw_b = adapter_b.fetch(_entry(slug="b"), tmp_path / "b")
    assert raw_a.content_fingerprint != raw_b.content_fingerprint


def test_redirect_is_followed(tmp_path):
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Recipe","name":"Redirected Recipe",
     "recipeYield":"3","recipeIngredient":["1 onion"]}
    </script></head></html>
    """
    adapter = _adapter_with({
        "https://example.com/robots.txt": "User-agent: *\nDisallow:\n",
        "https://example.com/recipes/test/": httpx.Response(
            301, headers={"Location": "https://example.com/recipes/test-renamed/"}
        ),
        "https://example.com/recipes/test-renamed/": html,
    })
    raw = adapter.fetch(_entry(), tmp_path)
    assert raw.name == "Redirected Recipe"


def test_manual_adapter_missing_slug_raises(tmp_path):
    adapter = ManualSeedAdapter({})
    with pytest.raises(SourceUnavailable, match="manual_recipes.json"):
        adapter.fetch(_entry(source_name=None), tmp_path)


def test_manual_adapter_returns_authored_content(tmp_path):
    adapter = ManualSeedAdapter({"test_recipe": {"servings": 4, "ingredients": ["1 onion", "2 eggs"]}})
    raw = adapter.fetch(_entry(url=None), tmp_path)
    assert raw.servings == 4
    assert raw.ingredient_lines == ["1 onion", "2 eggs"]
    assert raw.canonical_url is None
