# Optimizer constraints — what's built vs. what's scoped out

`optimizer.py`'s `suggest_meal_optimizations()` (used by the diary's
`/meal-optimize` and the meal-plan's `/optimize`) supports **budget** as a
real, computed constraint — `prices_by_food_id` (from the user's own
`FoodPrice` rows) and `max_additional_cost` filter suggestions by actual
entered prices. The other constraints named in
`nutri-matic-claude-prompts.txt` Prompt 2.2 — family size, cooking time,
dietary restrictions, allergies, preferred store — are **not**
implemented. This documents why, and what each would need.

## Family size

Not a real constraint to model — quantities in this app are already
per-person. "Scale for a family of 4" is multiplication the caller (or a
thin frontend helper) can do to any suggestion's `quantity_g` and
`estimated_cost`; the optimizer doesn't need to know about it. No schema
change needed if this is wanted — it's a display-layer concern.

## Cooking time / prep time

**Blocked on missing data.** Neither `Food` nor `Recipe` has any
time-to-prepare field, and USDA FoodData Central doesn't supply one for
raw ingredients (prep time is a property of a recipe/method, not a food).
To support this honestly:

- Add a `prep_minutes: int | None` column to `Recipe` (user-entered, like
  `FoodPrice` — optional, never inferred).
- For raw-food "add" suggestions, prep time is usually ~0 (many are
  ready-to-eat or near enough) — could default add-suggestions to 0 and
  only show real prep time for recipe-based swaps, once recipes carry it.
- Filtering the optimizer by a time budget only becomes meaningful once
  a reasonable fraction of recipes actually have this set — until then a
  "max 15 minutes" filter would silently exclude untimed recipes rather
  than neutrally include them (the same "don't penalize missing data"
  principle the cost filter already follows for price).

## Dietary restrictions / allergies

**Blocked on missing data**, and the most consequential gap to get wrong.
Foods have no allergen or diet-category tags anywhere in the schema, and
FDC doesn't supply structured allergen data either (Branded Foods has
free-text ingredient statements, not a queryable allergen taxonomy). A
naive keyword-match implementation (e.g. exclude foods whose name contains
"peanut") would produce **false negatives that matter** — a peanut allergy
sufferer relying on a keyword filter that misses "may contain" wording or
an unlisted cross-contamination risk is a real-world safety issue, not a
minor UX gap. This app has stayed strict about never presenting an
estimate with more confidence than the data supports; a half-built allergy
filter is the one place that discipline matters most, because the
consequence of getting it wrong isn't a wrong number, it's someone eating
something that could hurt them.

If this is ever built: it needs a real tagged-ingredient data source (not
name-substring matching), an explicit "this is not a safety-checked medical
filter, verify labels yourself" disclaimer surfaced every time it's used,
and ideally a second data source cross-check before shipping. Not attempted
here.

## Preferred store

**Blocked on missing data.** `FoodPrice` is one price per food per user —
there's no store dimension at all (see `models.py::FoodPrice`). Supporting
this would mean turning `FoodPrice` into a per-store price list
(`FoodPrice(user_id, food_id, store, package_price, package_quantity_g)`,
dropping today's `uq_food_price_user_food` unique constraint in favor of
`uq_food_price_user_food_store`), migrating existing rows to some default
store, and adding store selection UI to the food-prices page. A real
schema/migration change, not a query-time filter — deferred until there's
a specific request for it, per this phase's own ground rule about not
scaffolding for unconfirmed demand.
