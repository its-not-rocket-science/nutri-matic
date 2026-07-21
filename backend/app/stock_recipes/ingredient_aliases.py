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
    # no genuine "mixed beans" (e.g. three-bean-salad style) product exists
    # in this database at all -- the only "mixed"+"bean" match is a mixed
    # VEGETABLE medley (corn/lima beans/peas/carrots), a real category
    # mismatch for a recipe that means an actual tin of mixed beans, and it
    # also lacks amino acid data. Kidney beans (complete data) are used as
    # the closest single-bean stand-in, matching the garam-masala/curry-
    # powder precedent below: a documented approximation, not the wrong
    # food entirely.
    "mixed beans": "beans kidney all types canned",
    "kidney beans": "kidney beans canned",
    "cannellini beans": "beans white mature seeds canned",  # "Beans, cannellini, canned..." (fuzzy pick) has no amino acid data; white kidney beans are the same bean, complete data already in DB
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
    "mature cheddar": "cheddar cheese",
    "cheddar": "cheddar cheese",
    "celery sticks": "celery raw",
    "celery stick": "celery raw",
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
    # found matching real branded products instead of the generic
    # ingredient while running the real pipeline against a full FDC catalog
    "black olives": "olives ripe canned",
    "olives": "olives ripe canned",
    "salt": "salt table",
    "salt and pepper": "salt table",
    "black pepper": "spices pepper black",
    "pepper": "spices pepper black",
    "chilli flakes": "spices pepper red or cayenne",
    "bagel": "bagels plain",
    "bread roll": "bread white",
    "pitta": "bread pita",
    "cauliflower": "cauliflower raw",
    "butternut squash": "squash butternut raw",
    # bare "milk" was resolving to "Milk, sheep, fluid" (canonical tier's
    # shortest-non-branded-name tiebreak, not wrong exactly, just not what
    # any of these recipes mean) — affected 26 imported recipes when found
    # running the real pipeline
    "milk": "milk whole milkfat",
    # more real fuzzy-tier mismatches found the same way — a bare "lemon"
    # (not juice) was resolving to "Lemon peel, raw"; "courgette" to a
    # frozen/unprepared zucchini; "mixed salad leaves" to a foraged wild
    # plant ("Fireweed, leaves, raw"); "herbes de Provence" (not in this
    # catalog as a blend at all) to a dried mushroom ("Pepeao, dried")
    "lemon": "lemons raw without peel",
    "courgette": "squash summer zucchini raw",
    "mixed salad leaves": "lettuce raw",
    "salad leaves": "lettuce raw",
    "herbes de provence": "spices thyme dried",
    # "mustard powder" was resolving to "Gravy, mushroom, dry, powder" (no
    # amino acid data at all, blocking DIAAS/PDCAAS for the whole recipe)
    "mustard powder": "spices mustard seed ground",
    "cherry tomatoes": "tomatoes red ripe raw",  # was matching "Tomatoes, crushed, canned" (!)
    "beef sirloin steaks": "beef top sirloin steak raw",
    "beef sirloin": "beef top sirloin steak raw",
    "rolled oats": "oats",  # "Oats, whole grain, rolled, old fashioned" (fuzzy tier's pick) has no amino acid data
    "red peppers": "peppers sweet red raw",  # was resolving to an incomplete duplicate; this name has full amino acid data
    "baking potatoes": "potatoes flesh and skin raw",  # "Potatoes, raw, skin" (fuzzy pick) has no amino acid data
    # bare "egg"/"eggs" was a serious mismatch, not just an amino acid gap:
    # "egg" (canonical tier) resolved to "Eggnog" and "eggs" resolved to
    # "Eggs, Grade A, Large, egg yolk" (yolk-only nutrition for a whole-egg
    # ingredient) — found while chasing the highest-impact remaining
    # DIAAS/PDCAAS blocker (24 recipes on the yolk mismatch alone)
    "egg": "egg whole raw fresh",
    "eggs": "egg whole raw fresh",
    "large egg": "egg whole raw fresh",
    "large eggs": "egg whole raw fresh",
    "egg whites": "egg white raw fresh",
    "egg white": "egg white raw fresh",
    "egg yolks": "egg yolk raw fresh",  # must outrank the bare "egg" pattern below, or "egg yolks" wrongly matches whole egg
    "egg yolk": "egg yolk raw fresh",
    # Phase 2 "Category A" — real branded/wrong-category mismatches found
    # against the real live database, each recovering a generic entry
    # with a complete amino acid profile that was already sitting in the
    # database, unused, in favour of a branded or flatly wrong product:
    "vegetable stock": "soup vegetable broth",  # was "Soup, SWANSON, vegetable broth"
    "soy sauce": "soy sauce wheat shoyu",  # was "Sauce, peanut, made from peanut butter, water, soy sauce"
    "green beans": "beans snap green raw",  # was a toddler babyfood product
    "crusty bread": "bread french vienna toasted",  # was "Bread, cheese" (unrelated)
    "granola": "cereals granola homemade",  # was a chocolate-coated granola BAR, not the cereal
    "firm tofu": "tofu raw firm calcium sulfate",  # was a specific branded product
    "braising steak": "beef chuck raw",  # was "Sauce, steak, tomato based" (!)
    "sardines in tomato sauce": "sardine pacific tomato sauce",  # was the same wrong steak sauce
    "english muffin": "muffins english plain enriched",
    # no dedicated "garam masala" entry exists in this database at all —
    # curry powder is the closest available spice-blend proxy (both are
    # broad Indian spice mixes), a documented approximation rather than
    # the completely unrelated branded soup this was resolving to before
    "garam masala": "spices curry powder",
    # bare "smooth peanut butter" (no "reduced fat"/"chunky" wording at all
    # in the raw text) was resolving via fuzzy match to "Peanut butter,
    # smooth, reduced fat" -- a different specific product with no amino
    # acid data -- instead of the plain complete-data entry
    "smooth peanut butter": "peanut butter smooth style without salt",
    "peanut butter": "peanut butter smooth style without salt",
    # bare "walnuts" (no "glazed" wording in the raw text) was resolving to
    # "Nuts, walnuts, glazed" -- no amino acid data at all
    "walnuts": "nuts walnuts english",
    "walnut": "nuts walnuts english",
    # bare "tahini" was resolving to the "type of kernels unspecified" FDC
    # entry, which has no amino acid data at all -- the "most common type"
    # entry (roasted/toasted kernels) does
    "tahini": "sesame butter tahini roasted toasted",
    # "2 pork chops" (bare, no cut specified) was resolving to "Pork, chop,
    # center cut, raw", which has no amino acid data at all
    "pork chop": "pork fresh loin blade chops or roasts bone-in separable lean and fat raw",
    "pork chops": "pork fresh loin blade chops or roasts bone-in separable lean and fat raw",
    "romaine lettuce": "lettuce cos or romaine raw",
    # "black-eyed beans" (a cowpea) was resolving to "Beans, Dry, Black (0%
    # moisture)" -- ordinary black beans, a different bean entirely, not
    # just a missing-data problem
    "black-eyed beans": "cowpeas common blackeyes crowder southern canned plain",
    "black eyed beans": "cowpeas common blackeyes crowder southern canned plain",
    # "white wine" was resolving to "Wheat, hard white" (!) purely on the
    # shared word "white" -- a serious mismatch, not just a missing-data
    # one: it was crediting the recipe with wheat's ~13g/100g protein
    # instead of wine's actual ~0.07g/100g
    "white wine": "alcoholic beverage wine table white",
    # bare "split peas" (no "soup"/"canned" wording at all in the raw text)
    # was resolving to "Split pea soup, canned, reduced sodium..." -- a
    # completely different prepared product, not the raw legume the recipe
    # actually means, and with no amino acid data at all
    "split peas": "peas split mature seeds cooked boiled without salt",
    # "bran flakes"/"bran flakes cereal" (generic, no brand named) were
    # resolving to a branded POST product with no amino acid data --
    # RALSTON's bran flakes (a different brand, same category) has a
    # complete profile already in the database
    "bran flakes": "cereals ready-to-eat ralston enriched wheat bran flakes",
    "bran flakes cereal": "cereals ready-to-eat ralston enriched wheat bran flakes",
    # no UK "crumpet" entry exists in this database at all -- English
    # muffins are the closest USDA analogue (same yeasted-batter griddle
    # bread class), complete amino acid + digestibility data
    "crumpet": "english muffins plain enriched without calcium propionate",
    "crumpets": "english muffins plain enriched without calcium propionate",
    # no "muesli" entry exists in this database at all -- homemade granola
    # is the closest analogue (same rolled-oats+dried-fruit+nuts class),
    # complete amino acid + digestibility data
    "muesli": "cereals granola homemade",
}

REVIEWED_FALLBACKS: dict[str, str] = {
    # populated over time from review-file corrections — see
    # docs/stock-recipes.md "troubleshooting food-match failures"
}
