"""Maintainable data for food_matching.py's alias tier (priority 1) and
manual-review fallback tier (priority 5) — see prompt section 6.

ALIASES maps a normalised recurring ingredient phrase to a cleaner search
phrase to run through the app's existing search.search_foods_by_name
instead of the raw (often messier: "500 g 5% lean beef mince" ->
"5% lean beef mince" after quantity/unit stripping) ingredient name.
This is what fixes UK-recipe wording that the app's food database (mostly
USDA-derived, see search.py's FOOD_SYNONYMS for the general-purpose subset
of this) doesn't use verbatim — a curated shortcut, not a replacement for
search: the alias's search phrase still goes through the real fuzzy
matcher, so the food it resolves to reflects whatever's actually loaded in
the current database.

REVIEWED_FALLBACKS is the opposite kind of entry: a maintainer previously
looked at a specific ingredient name that the alias table AND fuzzy search
both failed (or matched wrongly) on, and manually pinned it to a search
phrase (or, once the exact food is known, could be extended to a food_id).
Consulted last — only when every earlier tier found nothing — precisely
because it's a record of "we already solved this one by hand", not a
general-purpose shortcut like ALIASES.

Add to either dict as new recurring failures/near-misses turn up in review
files — no code change needed.
"""

ALIASES: dict[str, str] = {
    "onion": "onions raw",
    "onions": "onions raw",
    "red onion": "onions red raw",
    "red onions": "onions red raw",
    "spring onion": "spring onion",
    "spring onions": "spring onion",
    "garlic": "garlic raw",
    "garlic clove": "garlic raw",
    "garlic cloves": "garlic raw",
    "cloves garlic": "garlic raw",
    "chopped tomatoes": "tomatoes canned",
    "tin chopped tomatoes": "tomatoes canned",
    "tins chopped tomatoes": "tomatoes canned",
    "plum tomatoes": "tomatoes canned",
    "passata": "tomatoes canned puree",
    "tomato puree": "tomato paste",
    "plain flour": "wheat flour white all purpose",
    "self-raising flour": "wheat flour white all purpose self rising",
    "self raising flour": "wheat flour white all purpose self rising",
    "wholemeal flour": "wheat flour whole grain",
    "vegetable stock": "stock vegetable",
    "vegetable stock cube": "stock vegetable",
    "chicken stock": "stock chicken",
    "chicken stock cube": "stock chicken",
    "beef stock": "stock beef",
    "beef stock cube": "stock beef",
    "minced beef": "beef ground",
    "beef mince": "beef ground",
    "lean minced beef": "beef ground lean",
    "lean beef mince": "beef ground lean",
    "minced lamb": "lamb ground",
    "lamb mince": "lamb ground",
    "minced pork": "pork ground",
    "pork mince": "pork ground",
    "minced turkey": "turkey ground",
    "turkey mince": "turkey ground",
    "chicken breast": "chicken breast raw",
    "chicken breasts": "chicken breast raw",
    "chicken thighs": "chicken thigh raw",
    "chicken thigh": "chicken thigh raw",
    "mixed beans": "beans mixed canned",
    "kidney beans": "kidney beans canned",
    "cannellini beans": "cannellini beans canned",
    "butter beans": "lima beans canned",
    "black beans": "black beans canned",
    "curry powder": "curry powder",
    "garam masala": "garam masala",
    "olive oil": "oil olive",
    "vegetable oil": "oil vegetable",
    "sunflower oil": "oil sunflower",
    "rapeseed oil": "oil canola rapeseed",
    "coconut oil": "oil coconut",
    "brown rice": "rice brown cooked",
    "white rice": "rice white cooked",
    "basmati rice": "rice white long grain cooked",
    "red lentils": "lentils raw",
    "green lentils": "lentils raw",
    "puy lentils": "lentils raw",
    "chickpeas": "chickpeas canned",
    "tinned chickpeas": "chickpeas canned",
    "double cream": "cream heavy",
    "single cream": "cream light",
    "greek yoghurt": "yogurt greek plain",
    "greek yogurt": "yogurt greek plain",
    "natural yoghurt": "yogurt plain",
    "natural yogurt": "yogurt plain",
    "cheddar cheese": "cheddar cheese",
    "grated cheddar": "cheddar cheese",
    "mozzarella": "mozzarella cheese",
    "parmesan": "parmesan cheese",
    "wholemeal bread": "bread whole wheat",
    "white bread": "bread white",
    "spaghetti": "pasta spaghetti dry",
    "penne": "pasta penne dry",
    "brown sugar": "sugar brown",
    "caster sugar": "sugar white granulated",
    "icing sugar": "sugar powdered",
    "worcestershire sauce": "worcestershire sauce",
    "soy sauce": "soy sauce",
    "fish sauce": "fish sauce",
}

REVIEWED_FALLBACKS: dict[str, str] = {
    # populated over time from review-file corrections — see
    # docs/stock-recipes.md "troubleshooting food-match failures"
}
