"""Stock recipe library — sources, curates, matches, analyses, and imports a
curated set of recipes visible to every Nutri-Matic user (public, read-only,
system-account-owned — see models.User.is_system).

Run as `python -m app.stock_recipes <command>` — see cli.py for the full
command list, or docs/stock-recipes.md for the end-to-end walkthrough
(what each pipeline stage does, how to add a source, how to review, what
robustness ratings do/don't mean).

Module map:
    manifest.py           the version-controlled target recipe list
                           (seed_data/manifest.json)
    sources/               pluggable source adapters (manual seed file,
                           schema.org/Recipe JSON-LD scraper)
    ingredient_parser.py   raw ingredient line -> structured fields
    unit_conversion.py     household units -> grams, with confidence
    ingredient_aliases.py  maintainable alias -> canonical food name map
    food_matching.py       parsed ingredient -> Food, with confidence
    robustness.py          Monte Carlo nutritional-robustness analysis
    dedup.py               stable ids / near-duplicate detection
    pipeline.py            orchestrates discover/fetch/.../report against
                           a local candidate cache; only import-approved
                           and refresh touch the database
    cli.py / __main__.py   the command-line entrypoint
"""
