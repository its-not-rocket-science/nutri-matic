"""Maintainable data for food_matching.py's alias tier (priority 1) and
manual-review fallback tier (priority 5) — see prompt section 6.

ALIASES maps a normalised recurring ingredient phrase to an AliasTarget
carrying the search phrase to run through the app's existing search
(search.search_foods_by_name) instead of the raw (often messier: "500 g 5%
lean beef mince" -> "5% lean beef mince" after quantity/unit stripping)
ingredient name. This is what fixes UK-recipe wording that the app's food
database (mostly USDA-derived, see search.py's FOOD_SYNONYMS for the
general-purpose subset of this) doesn't use verbatim — a curated shortcut,
not a replacement for search: the alias's search phrase still goes through
the real fuzzy matcher, so the food it resolves to reflects whatever's
actually loaded in the current database.

REVIEWED_FALLBACKS is the opposite kind of entry: a maintainer previously
looked at a specific ingredient name that the alias table AND fuzzy search
both failed (or matched wrongly) on, and manually pinned it to a search
phrase (or, once the exact food is known, could be extended to a food_id).
Consulted last — only when every earlier tier found nothing — precisely
because it's a record of "we already solved this one by hand", not a
general-purpose shortcut like ALIASES.

Both tables used to map straight to a bare search-phrase string. That
collapsed several genuinely different relationships between what the
recipe says and what food_matching.py actually resolves it to:

  * two entries might be the *same food*, just reworded to match the
    database's USDA-style naming ("onion" -> "onions raw")
  * or a real UK/US naming difference for an otherwise identical product
    ("plain flour" -> "wheat flour white all purpose", "double cream" ->
    "cream heavy")
  * or a nutritionally-similar but genuinely different food, chosen
    because the database has no entry for the specific thing the recipe
    means ("basmati rice" -> generic long-grain, "red lentils" -> generic
    lentils)
  * or a broad stand-in for a whole missing category, a much coarser
    approximation than the above ("garam masala" -> curry powder,
    "muesli" -> granola)
  * or (REVIEWED_FALLBACKS only, currently unpopulated — see
    docs/stock-recipes.md "troubleshooting food-match failures") a
    one-off substitution a maintainer manually reviewed and signed off,
    consulted only as the very last resort

Those are different claims about how trustworthy/exact a match is, and
conflating them made it impossible to tell, from the data alone, whether
an alias was "this is definitely the same food, just reworded" or "this
is the best approximation available." AliasTarget makes the distinction
explicit: `relationship` names which of the above applies, `confidence`
is the per-relationship default trust level (still a judgement call, not
a measurement), and `rationale`/`provenance` carry the reasoning a
maintainer would otherwise have had to leave as a code comment.

This refactor is data/metadata only — see food_matching.py, which reads
target.search_phrase exactly where it used to read the bare string, and
target.confidence in place of the old single flat _ALIAS_CONFIDENCE /
_REVIEWED_CONFIDENCE constants. Every relationship type currently in use
here resolves to the same food it did before (confidence values were
chosen so the flat constants' old value — 0.95 / 0.9 — line up with the
EXACT / REVIEWED_SUBSTITUTION defaults), so no matching outcome changes.

Add to either dict as new recurring failures/near-misses turn up in review
files — no code change needed, just a new key using whichever of exact(),
regional(), analogue(), or proxy() below fits the relationship (or, for
REVIEWED_FALLBACKS, AliasTarget(..., relationship=AliasRelationship.
REVIEWED_SUBSTITUTION, ...) directly).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AliasRelationship(str, Enum):
    """What kind of claim an alias/fallback entry is making about the
    relationship between the recipe's wording and the food it resolves to
    — see the module docstring for what each one means in practice."""

    # Same food; the search phrase is just a reworded/normalised version of
    # the ingredient name (plural stripped, USDA comma-order applied, a
    # wrong database match corrected back to the actual same food, etc).
    EXACT = "exact"
    # A real regional (chiefly UK/US) naming difference for what is, as
    # food, the same product — "courgette"/"zucchini", "mince"/"ground".
    REGIONAL_EQUIVALENT = "regional_equivalent"
    # A different food/variety, chosen because it's the closest
    # nutritional match available — e.g. a specific rice/lentil variety
    # standing in for the database's one generic entry.
    CLOSE_ANALOGUE = "close_analogue"
    # A broad stand-in for a whole category the database has no entry for
    # at all (a spice blend, a UK bread product) — the coarsest, lowest-
    # confidence kind of approximation here.
    CATEGORY_PROXY = "category_proxy"
    # A one-off substitution a maintainer manually reviewed and signed off
    # on for REVIEWED_FALLBACKS, after every earlier tier failed on it.
    REVIEWED_SUBSTITUTION = "reviewed_substitution"


# Default confidence per relationship — a starting point representing how
# much a match of that *kind* should generally be trusted, not a measured
# quantity. Individual AliasTarget entries may override it (see `analogue`/
# `proxy` below, which take an explicit confidence for the same reason).
DEFAULT_CONFIDENCE: dict[AliasRelationship, float] = {
    AliasRelationship.EXACT: 0.95,
    AliasRelationship.REGIONAL_EQUIVALENT: 0.93,
    AliasRelationship.CLOSE_ANALOGUE: 0.8,
    AliasRelationship.CATEGORY_PROXY: 0.65,
    AliasRelationship.REVIEWED_SUBSTITUTION: 0.9,
}


@dataclass(frozen=True)
class AliasTarget:
    """One ALIASES/REVIEWED_FALLBACKS entry's resolved target and the
    reasoning behind it.

    `fdc_id`/`food_id`, when set, pin this entry to a stable identifier
    rather than leaving resolution entirely to `search_phrase` re-running
    through description search every time. Descriptions drift in meaning
    as the database is re-ingested (a fuzzier phrase can start matching a
    different row once the catalog changes), but a maintainer who has
    actually reviewed and picked a specific Food row means *that row*,
    permanently — see food_matching._resolve_alias_target, which tries
    `fdc_id` first, then `food_id`, and only falls back to `search_phrase`
    if neither resolves (the food was deleted, or this database was
    re-ingested and it now has a different local id).

    `fdc_id` is preferred where available: it's USDA FoodData Central's
    own identifier for the food, stable across *any* database that
    ingests the same FDC release, not just this one — unlike a local
    `Food.id`, which is only ever a primary key assigned by this specific
    database's own auto-increment and has no meaning outside it. `food_id`
    still matters for anything that ISN'T from FDC at all (a manually
    seeded pure-fat food, or the generic-muesli composite — see
    seed_manual_foods.py), which has no fdc_id to pin to in the first
    place. Both are optional and independent; a caller with only a local
    id and no fdc_id should just leave fdc_id unset, not invent one.

    This is intended primarily for REVIEWED_FALLBACKS entries (prompt
    section 4) but isn't restricted to them — nothing stops an ALIASES
    entry from pinning an id too, once a maintainer has confirmed one.

    `expected_food_name` records the Food.name a maintainer saw at review
    time, purely so validate_reviewed_mappings can flag drift (the id
    still resolves, but to a food that's been renamed/re-described since
    review — a signal the substitution deserves a second look, not
    proof it's now wrong). Only meaningful alongside `fdc_id`/`food_id`.
    """

    # fed to food_matching._word_and_search exactly as the old bare-string
    # dict value was — plain space-separated words, not a USDA-punctuated
    # name (see food_matching.py's docstring for why). Always present, even
    # when `fdc_id`/`food_id` is set, as the fallback description search.
    search_phrase: str
    relationship: AliasRelationship
    confidence: float
    # why this target was chosen — the human-readable claim a reviewer or
    # end user should see, e.g. "UK 'courgette' is the US 'zucchini' — same
    # vegetable, different regional name."
    rationale: str
    # provenance notes: how/when this was found, what it replaced, what
    # was ruled out — the "war story" behind the entry, kept separate from
    # `rationale` so the latter can stay a single user-facing sentence.
    # None for entries with nothing more to add beyond the rationale.
    provenance: str | None = None
    food_id: int | None = None
    fdc_id: int | None = None
    expected_food_name: str | None = None


def exact(
    search_phrase: str,
    rationale: str = "Same ingredient — search phrase normalised to the app's USDA-style naming.",
    *,
    provenance: str | None = None,
) -> AliasTarget:
    return AliasTarget(search_phrase, AliasRelationship.EXACT, DEFAULT_CONFIDENCE[AliasRelationship.EXACT], rationale, provenance)


def regional(search_phrase: str, rationale: str, *, provenance: str | None = None) -> AliasTarget:
    return AliasTarget(
        search_phrase, AliasRelationship.REGIONAL_EQUIVALENT, DEFAULT_CONFIDENCE[AliasRelationship.REGIONAL_EQUIVALENT],
        rationale, provenance,
    )


def analogue(
    search_phrase: str, rationale: str, *, confidence: float | None = None, provenance: str | None = None
) -> AliasTarget:
    return AliasTarget(
        search_phrase, AliasRelationship.CLOSE_ANALOGUE,
        confidence if confidence is not None else DEFAULT_CONFIDENCE[AliasRelationship.CLOSE_ANALOGUE],
        rationale, provenance,
    )


def proxy(
    search_phrase: str, rationale: str, *, confidence: float | None = None, provenance: str | None = None
) -> AliasTarget:
    return AliasTarget(
        search_phrase, AliasRelationship.CATEGORY_PROXY,
        confidence if confidence is not None else DEFAULT_CONFIDENCE[AliasRelationship.CATEGORY_PROXY],
        rationale, provenance,
    )


def reviewed(
    search_phrase: str,
    rationale: str,
    *,
    provenance: str | None = None,
    food_id: int | None = None,
    fdc_id: int | None = None,
    expected_food_name: str | None = None,
) -> AliasTarget:
    """`search_phrase` is required regardless of whether `fdc_id`/`food_id`
    is given — it's the fallback description search used if the pinned id
    stops resolving (see AliasTarget's docstring and food_matching.
    _resolve_alias_target). Pass `fdc_id` (preferred, when the target is a
    real FDC-derived food) or `food_id` (for a manually-seeded food with no
    fdc_id at all) plus `expected_food_name` (the Food.name seen at review
    time) once a maintainer has identified the exact database row this
    substitution should target — see prompt section 4: reviewed mappings
    should primarily target a stable id, not rely solely on description
    matching."""
    return AliasTarget(
        search_phrase, AliasRelationship.REVIEWED_SUBSTITUTION, DEFAULT_CONFIDENCE[AliasRelationship.REVIEWED_SUBSTITUTION],
        rationale, provenance, food_id=food_id, fdc_id=fdc_id, expected_food_name=expected_food_name,
    )


def _duplicate_key_problems(table_name: str) -> list[str]:
    """A duplicate key in a Python dict literal is not a SyntaxError — the
    second occurrence silently overwrites the first at runtime, so nothing
    about the resulting dict object can ever reveal it happened. Parsing
    this module's own source AST is the only way to see a collision the
    runtime dict already resolved away (prompt section 2: "add validation
    for duplicate keys")."""
    import ast
    import inspect
    import sys

    tree = ast.parse(inspect.getsource(sys.modules[__name__]))
    for node in ast.walk(tree):
        target = (
            node.target if isinstance(node, ast.AnnAssign)
            else (node.targets[0] if isinstance(node, ast.Assign) else None)
        )
        if target is not None and getattr(target, "id", None) == table_name:
            keys = [k.value for k in node.value.keys]
            seen: set[str] = set()
            dupes = [k for k in keys if k in seen or seen.add(k)]
            return [f"{table_name} source literal has duplicate key(s): {dupes}"] if dupes else []
    return [f"could not find a {table_name} assignment in ingredient_aliases.py's source"]


def validate_alias_schema() -> list[str]:
    """Static (no-database) validation over ALIASES/REVIEWED_FALLBACKS —
    every entry really is a well-formed AliasTarget, and neither table's
    source literal has a duplicate key. Read-only, no database access:
    the `validate-aliases` CLI command (stock_recipes/cli.py) runs this
    alongside food_matching.validate_reviewed_mappings, which needs a live
    database to check that a pinned target id actually still resolves.
    Returns one human-readable diagnostic string per problem found, or an
    empty list if the registry is clean."""
    problems: list[str] = []
    for table_name, table in (("ALIASES", ALIASES), ("REVIEWED_FALLBACKS", REVIEWED_FALLBACKS)):
        problems.extend(_duplicate_key_problems(table_name))
        for key, target in table.items():
            label = f"{table_name}[{key!r}]"
            if not isinstance(target, AliasTarget):
                problems.append(f"{label} is not an AliasTarget")
                continue
            if not target.rationale or not target.rationale.strip():
                problems.append(f"{label} has no rationale")
            if not target.search_phrase or not target.search_phrase.strip():
                problems.append(f"{label} has no search_phrase")
            if not (0.0 < target.confidence <= 1.0):
                problems.append(f"{label}.confidence={target.confidence!r} out of range (0, 1]")
            if (target.food_id is not None or target.fdc_id is not None) and not target.expected_food_name:
                problems.append(f"{label} pins an id but has no expected_food_name")
    return problems


ALIASES: dict[str, AliasTarget] = {
    "onion": exact("onions raw"),
    "onions": exact("onions raw"),
    "red onion": exact("onions red raw"),
    "red onions": exact("onions red raw"),
    "spring onion": exact("spring onion"),
    "spring onions": exact("spring onion"),
    "garlic": exact("garlic raw"),
    "garlic clove": exact("garlic raw"),
    "garlic cloves": exact("garlic raw"),
    "cloves garlic": exact("garlic raw"),
    "chopped tomatoes": exact("tomatoes canned"),
    "tin chopped tomatoes": exact("tomatoes canned"),
    "tins chopped tomatoes": exact("tomatoes canned"),
    "plum tomatoes": analogue(
        "tomatoes canned",
        "Plum tomatoes are almost always sold/used canned in this context; the database's one generic canned-tomato entry stands in for the variety.",
    ),
    "passata": regional(
        "tomatoes canned puree",
        "Italian/UK \"passata\" (sieved tomatoes) is the same product as US \"tomato puree\" — a naming difference, not a different food.",
    ),
    "tomato puree": regional(
        "tomato paste",
        "UK \"tomato puree\" is concentrated like US \"tomato paste\", not the thinner US \"tomato puree\" — the UK term maps to the US paste product.",
    ),
    "plain flour": regional("wheat flour white all purpose", "UK \"plain flour\" is the US \"all-purpose flour\" — same product, different regional name."),
    "self-raising flour": regional(
        "wheat flour white all purpose self rising",
        "UK \"self-raising flour\" is the US \"self-rising flour\" — same product (flour pre-mixed with raising agent), different regional name.",
    ),
    "self raising flour": regional(
        "wheat flour white all purpose self rising",
        "UK \"self raising flour\" is the US \"self-rising flour\" — same product, different regional name.",
    ),
    "wholemeal flour": regional("wheat flour whole grain", "UK \"wholemeal\" is the US \"whole grain/whole wheat\" — same product, different regional name."),
    "vegetable stock": proxy(
        "soup vegetable broth",
        "Database has no dedicated \"stock\" entry for this — a prepared vegetable broth is the closest generic stand-in.",
        provenance="Was previously resolving to a branded product (\"Soup, SWANSON, vegetable broth\") — see Phase 2 Category A fix.",
    ),
    "vegetable stock cube": exact("stock vegetable"),
    "chicken stock": exact("stock chicken"),
    "chicken stock cube": exact("stock chicken"),
    "beef stock": exact("stock beef"),
    "beef stock cube": exact("stock beef"),
    "minced beef": regional("beef ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "beef mince": regional("beef ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "lean minced beef": regional("beef ground lean", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "lean beef mince": regional("beef ground lean", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "minced lamb": regional("lamb ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "lamb mince": regional("lamb ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "minced pork": regional("pork ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "pork mince": regional("pork ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "minced turkey": regional("turkey ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "turkey mince": regional("turkey ground", "UK \"mince\" is the US \"ground\" — same product, different regional name."),
    "chicken breast": exact("chicken breast raw"),
    "chicken breasts": exact("chicken breast raw"),
    "chicken thighs": exact("chicken thigh raw"),
    "chicken thigh": exact("chicken thigh raw"),
    "mixed beans": proxy(
        "beans kidney all types canned",
        "Database has no genuine mixed-bean (e.g. three-bean-salad style) product — its only \"mixed\"+\"bean\" match is a mixed VEGETABLE medley, a real category mismatch. Kidney beans are the closest single-bean stand-in with complete amino acid data.",
    ),
    "kidney beans": exact("kidney beans canned"),
    "cannellini beans": regional(
        "beans white mature seeds canned",
        "Cannellini beans are white kidney beans marketed under an Italian name — the same bean; the DB's specific \"cannellini\" entry has no amino acid data, so the white-kidney-bean entry (same species, complete data) is used instead.",
    ),
    "butter beans": regional("lima beans canned", "UK \"butter beans\" are US \"lima beans\" — same bean, different regional name."),
    "black beans": exact("black beans canned"),
    "curry powder": exact("curry powder"),
    "garam masala": proxy(
        "spices curry powder",
        "Database has no dedicated garam masala entry at all — curry powder is the closest available spice-blend proxy (both are broad Indian spice mixes).",
        provenance="Previously resolving to an unrelated branded soup product before this proxy was added.",
    ),
    "olive oil": exact("oil olive"),
    "vegetable oil": exact("oil vegetable"),
    "sunflower oil": exact("oil sunflower"),
    "rapeseed oil": regional("oil canola rapeseed", "UK \"rapeseed oil\" is the US \"canola oil\" — same oil, different regional name."),
    "coconut oil": exact("oil coconut"),
    "brown rice": exact("rice brown cooked"),
    "white rice": exact("rice white cooked"),
    "basmati rice": analogue(
        "rice white long grain cooked",
        "Basmati is a specific long-grain variety; the database has no dedicated basmati entry, so the generic long-grain white rice entry (nutritionally very similar) stands in.",
    ),
    "red lentils": analogue(
        "lentils raw",
        "Database has no per-variety lentil entries; the generic lentils entry stands in — lentil varieties are nutritionally very close to one another.",
    ),
    "green lentils": analogue(
        "lentils raw",
        "Database has no per-variety lentil entries; the generic lentils entry stands in — lentil varieties are nutritionally very close to one another.",
    ),
    "puy lentils": analogue(
        "lentils raw",
        "Database has no per-variety lentil entries; the generic lentils entry stands in — lentil varieties are nutritionally very close to one another.",
    ),
    "chickpeas": exact("chickpeas canned"),
    "tinned chickpeas": exact("chickpeas canned"),
    "double cream": regional("cream heavy", "UK \"double cream\" is the US \"heavy cream\" — same product, different regional name."),
    "single cream": regional("cream light", "UK \"single cream\" is the US \"light cream\" — same product, different regional name."),
    "greek yoghurt": exact("yogurt greek plain", "Same product; \"yoghurt\" is the UK spelling of \"yogurt\"."),
    "greek yogurt": exact("yogurt greek plain"),
    "natural yoghurt": regional("yogurt plain", "UK \"natural yog(h)urt\" is the US \"plain yogurt\" — same product, different regional name."),
    "natural yogurt": regional("yogurt plain", "UK \"natural yogurt\" is the US \"plain yogurt\" — same product, different regional name."),
    "cheddar cheese": exact("cheddar cheese"),
    "grated cheddar": exact("cheddar cheese", "Same product; the grated form isn't a separate database entry."),
    "mature cheddar": exact("cheddar cheese", "Same product; maturity isn't a separate database entry."),
    "cheddar": exact("cheddar cheese"),
    "celery sticks": exact("celery raw"),
    "celery stick": exact("celery raw"),
    "mozzarella": exact("mozzarella cheese"),
    "parmesan": exact("parmesan cheese"),
    "wholemeal bread": regional("bread whole wheat", "UK \"wholemeal\" is the US \"whole wheat\" — same product, different regional name."),
    "white bread": exact("bread white"),
    "spaghetti": exact("pasta spaghetti dry"),
    "penne": exact("pasta penne dry"),
    "brown sugar": exact("sugar brown"),
    "caster sugar": regional(
        "sugar white granulated",
        "UK \"caster sugar\" (finely ground) is closest to US \"granulated sugar\" — treated as the same product for matching purposes.",
    ),
    "icing sugar": regional("sugar powdered", "UK \"icing sugar\" is the US \"powdered/confectioners' sugar\" — same product, different regional name."),
    "worcestershire sauce": exact("worcestershire sauce"),
    "soy sauce": exact(
        "soy sauce wheat shoyu",
        "Same food (soy sauce); this specific database entry has complete amino acid data.",
        provenance="Was previously resolving to \"Sauce, peanut, made from peanut butter, water, soy sauce\" — see Phase 2 Category A fix.",
    ),
    "fish sauce": exact("fish sauce"),
    "black olives": exact("olives ripe canned"),
    "olives": exact("olives ripe canned"),
    "salt": exact("salt table"),
    "salt and pepper": proxy(
        "salt table",
        "A compound seasoning phrase reduced to its dominant ingredient (salt) — the pepper component isn't separately represented, a deliberate simplification rather than a claim these are nutritionally equivalent.",
    ),
    "black pepper": exact("spices pepper black"),
    "pepper": exact("spices pepper black", "Assumes the common recipe sense (ground black pepper seasoning), not bell/chilli pepper."),
    "chilli flakes": analogue("spices pepper red or cayenne", "Chilli flakes are close to, but not identical to, ground cayenne/red pepper — the closest entry available."),
    "bagel": exact("bagels plain"),
    "bread roll": analogue("bread white", "A generic bread roll has no dedicated entry; white bread is the closest available stand-in in the same food class."),
    "pitta": exact("bread pita", "Same product; \"pitta\" is the UK spelling of \"pita\"."),
    "cauliflower": exact("cauliflower raw"),
    "butternut squash": exact("squash butternut raw"),
    "milk": exact(
        "milk whole milkfat",
        "Same intent (bare \"milk\" means dairy cow's milk in these recipes); fixes a wrong canonical match, not a substitution.",
        provenance="Bare \"milk\" was previously resolving to \"Milk, sheep, fluid\" (canonical tier's shortest-non-branded-name tiebreak) — affected 26 imported recipes.",
    ),
    "lemon": exact(
        "lemons raw without peel",
        "Same food; fixes a wrong canonical match.",
        provenance="Was previously resolving to \"Lemon peel, raw\" instead of the fruit itself.",
    ),
    "courgette": regional("squash summer zucchini raw", "UK \"courgette\" is the US \"zucchini\" — same vegetable, different regional name."),
    "mixed salad leaves": proxy(
        "lettuce raw",
        "Database has no \"mixed salad leaves\"/mesclun entry at all — plain lettuce is the broad stand-in.",
        provenance="Was previously resolving to \"Fireweed, leaves, raw\", a foraged wild plant.",
    ),
    "salad leaves": proxy("lettuce raw", "Database has no salad-leaf-mix entry at all — plain lettuce is the broad stand-in."),
    "herbes de provence": proxy(
        "spices thyme dried",
        "Database has no herbes de Provence blend entry at all — dried thyme (a major component of the blend) is the single-herb proxy for the whole mix.",
        provenance="Was previously resolving to \"Pepeao, dried\", an unrelated dried mushroom.",
    ),
    "mustard powder": exact(
        "spices mustard seed ground",
        "Same food (ground mustard seed); fixes a wrong canonical match.",
        provenance="Was previously resolving to \"Gravy, mushroom, dry, powder\", which also had no amino acid data.",
    ),
    "cherry tomatoes": analogue(
        "tomatoes red ripe raw",
        "Cherry tomatoes are a small-fruited variety of the same species; the generic raw-tomato entry stands in since the database has no cherry-tomato-specific entry.",
        provenance="Was previously resolving to \"Tomatoes, crushed, canned\".",
    ),
    "beef sirloin steaks": exact("beef top sirloin steak raw"),
    "beef sirloin": exact("beef top sirloin steak raw"),
    "rolled oats": exact(
        "oats",
        "Same food; the plain \"oats\" entry has complete amino acid data the more specific \"rolled, old fashioned\" entry lacks.",
    ),
    "red peppers": exact(
        "peppers sweet red raw",
        "Same food; fixes an incomplete-duplicate match — this entry has full amino acid data.",
    ),
    "baking potatoes": exact(
        "potatoes flesh and skin raw",
        "Same food; the fuzzy-tier pick (\"Potatoes, raw, skin\") had no amino acid data.",
    ),
    "egg": exact(
        "egg whole raw fresh",
        "Same food (whole egg); fixes a serious category mismatch.",
        provenance="Bare \"egg\" was previously resolving to \"Eggnog\" — found while chasing the highest-impact remaining DIAAS/PDCAAS blocker.",
    ),
    "eggs": exact(
        "egg whole raw fresh",
        "Same food (whole egg); fixes a serious category mismatch.",
        provenance="Bare \"eggs\" was previously resolving to \"Eggs, Grade A, Large, egg yolk\" — yolk-only nutrition for a whole-egg ingredient, affecting 24 recipes.",
    ),
    "large egg": exact("egg whole raw fresh"),
    "large eggs": exact("egg whole raw fresh"),
    "egg whites": exact("egg white raw fresh"),
    "egg white": exact("egg white raw fresh"),
    "egg yolks": exact(
        "egg yolk raw fresh",
        "Same food (egg yolk only); must outrank the bare \"egg\" pattern, or \"egg yolks\" wrongly matches whole egg.",
    ),
    "egg yolk": exact("egg yolk raw fresh"),
    "green beans": exact(
        "beans snap green raw",
        "Same food; fixes a wrong match to a toddler babyfood product.",
    ),
    "crusty bread": analogue(
        "bread french vienna toasted",
        "Crusty bread has no dedicated entry; a French/Vienna-style loaf is the closest available bread in the same crusty-loaf class.",
        provenance="Was previously resolving to \"Bread, cheese\", an unrelated product.",
    ),
    "granola": exact(
        "cereals granola homemade",
        "Same food (granola cereal); fixes a wrong match to a chocolate-coated granola BAR.",
    ),
    "firm tofu": exact(
        "tofu raw firm calcium sulfate",
        "Same food; fixes a match to a specific branded product.",
    ),
    "braising steak": regional(
        "beef chuck raw",
        "UK \"braising steak\" is a butchery term for what US butchery calls \"chuck\" — the same cut, different regional name.",
        provenance="Was previously resolving to \"Sauce, steak, tomato based\".",
    ),
    "sardines in tomato sauce": exact(
        "sardine pacific tomato sauce",
        "Same food; fixes a match to the same wrong steak-sauce product as \"braising steak\" above.",
    ),
    "english muffin": exact("muffins english plain enriched"),
    "smooth peanut butter": exact(
        "peanut butter smooth style without salt",
        "Same food; the plain complete-data entry, not the \"reduced fat\" product the fuzzy tier picked.",
    ),
    "peanut butter": exact("peanut butter smooth style without salt"),
    "walnuts": exact(
        "nuts walnuts english",
        "Same food; fixes a match to \"Nuts, walnuts, glazed\", which has no amino acid data.",
    ),
    "walnut": exact("nuts walnuts english"),
    "tahini": exact(
        "sesame butter tahini roasted toasted",
        "Same food; the roasted/toasted (\"most common type\") entry has amino acid data the unspecified-kernel entry lacks.",
    ),
    "pork chop": exact(
        "pork fresh loin blade chops or roasts bone-in separable lean and fat raw",
        "Same food; the bare \"pork chop\" fuzzy match had no amino acid data at all.",
    ),
    "pork chops": exact("pork fresh loin blade chops or roasts bone-in separable lean and fat raw"),
    "romaine lettuce": exact("lettuce cos or romaine raw"),
    "black-eyed beans": exact(
        "cowpeas common blackeyes crowder southern canned plain",
        "Black-eyed beans are cowpeas — this fixes a match to ordinary black beans, a genuinely different bean, not just a missing-data problem.",
    ),
    "black eyed beans": exact("cowpeas common blackeyes crowder southern canned plain"),
    "white wine": exact(
        "alcoholic beverage wine table white",
        "Same food (white wine); fixes a serious mismatch to \"Wheat, hard white\" purely on the shared word \"white\".",
        provenance="Wrongly credited the recipe with wheat's ~13g/100g protein instead of wine's actual ~0.07g/100g.",
    ),
    "split peas": exact(
        "peas split mature seeds cooked boiled without salt",
        "Same food (raw legume); fixes a match to \"Split pea soup, canned\", a completely different prepared product.",
    ),
    "bran flakes": analogue(
        "cereals ready-to-eat ralston enriched wheat bran flakes",
        "Generic/other-brand bran flakes has no complete-data entry; a different brand (Ralston) in the same product category stands in.",
        provenance="Was previously resolving to a POST-branded product with no amino acid data.",
    ),
    "bran flakes cereal": analogue(
        "cereals ready-to-eat ralston enriched wheat bran flakes",
        "Generic/other-brand bran flakes has no complete-data entry; a different brand (Ralston) in the same product category stands in.",
    ),
    # Borderline call, resolved as close_analogue rather than category_proxy:
    # a crumpet is a specific yeasted-batter griddle bread, not a stand-in
    # for a whole missing food *category* the way "garam masala" -> curry
    # powder is (there, no blend at all exists in this database). English
    # muffins are the closest specific analogue in the same bread class —
    # different product, same nutritional ballpark — which is exactly what
    # close_analogue is for.
    "crumpet": analogue(
        "english muffins plain enriched without calcium propionate",
        "Database has no UK crumpet entry at all — English muffins are the closest USDA analogue (same yeasted-batter griddle-bread class), with complete amino acid + digestibility data.",
    ),
    "crumpets": analogue(
        "english muffins plain enriched without calcium propionate",
        "Database has no UK crumpet entry at all — English muffins are the closest USDA analogue (same yeasted-batter griddle-bread class), with complete amino acid + digestibility data.",
    ),
    "muesli": reviewed(
        "muesli generic composite",
        "Muesli has no single FDC entry, so this targets a purpose-built composite food "
        "(50% rolled oats / 20% dried fruit / 20% mixed nuts / 10% seeds by mass) computed "
        "from real component foods already in this database — a manually curated stand-in "
        "for the category, not a proxy for a different cereal.",
        provenance=(
            "Previously proxied to homemade granola (a different, if adjacent, cereal — "
            "same rolled-oats+dried-fruit+nuts class, but not muesli). See "
            "app/seed_manual_foods.py's COMPOSITE_FOODS for exactly how the composite's "
            "nutrients/amino acids were built, and prompt section 7."
        ),
    ),
}

REVIEWED_FALLBACKS: dict[str, AliasTarget] = {
    # populated over time from review-file corrections — see
    # docs/stock-recipes.md "troubleshooting food-match failures". Use
    # reviewed(search_phrase, rationale, provenance=...) for new entries.
}
