"""Command-line entrypoint for the stock recipe pipeline.

    python -m app.stock_recipes discover
    python -m app.stock_recipes fetch
    python -m app.stock_recipes parse
    python -m app.stock_recipes match
    python -m app.stock_recipes analyse
    python -m app.stock_recipes review-export
    python -m app.stock_recipes import-approved
    python -m app.stock_recipes refresh
    python -m app.stock_recipes report
    python -m app.stock_recipes health-check
    python -m app.stock_recipes validate-aliases

Each stage reads/writes a local JSON candidate cache under --cache-dir
(default ./.stock_recipe_cache) — nothing touches the database until
import-approved (or refresh, for already-imported recipes) runs. See
docs/stock-recipes.md for the full walkthrough.

Default behaviour is safe: `import-approved` only ever writes candidates
whose review-file row has proposed_publication_status == "approved" — an
unedited review file (default status "needs_review") publishes nothing.
"""

import argparse
import logging
import sys
from pathlib import Path

from . import pipeline

DEFAULT_CACHE_DIR = Path(".stock_recipe_cache")
DEFAULT_REVIEW_FILE = DEFAULT_CACHE_DIR / "review.json"


def _add_common_args(p: argparse.ArgumentParser, *, review_file: bool = False) -> None:
    p.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR,
        help=f"Local candidate-state + fetched-page cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    p.add_argument("--source", help="Only operate on manifest entries with this source_name")
    p.add_argument("--collection", help="Only operate on manifest entries assigned to this collection key")
    p.add_argument("--limit", type=int, help="Process at most this many candidates")
    p.add_argument("--verbose", action="store_true", help="Debug-level logging")
    if review_file:
        p.add_argument(
            "--review-file", type=Path, default=DEFAULT_REVIEW_FILE,
            help=f"Review file path, .json (default: {DEFAULT_REVIEW_FILE}); "
                 "a sibling .csv is written/read alongside it",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.stock_recipes", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="Load the manifest; register new candidates in the cache")
    _add_common_args(p)

    p = sub.add_parser("fetch", help='Fetch source="fetch" candidates via their source adapter')
    _add_common_args(p)
    p.add_argument("--force-refresh", action="store_true", help="Bypass the page cache, re-fetch even if cached")
    p.add_argument("--dry-run", action="store_true", help="Fetch and parse structured data but don't cache it")

    p = sub.add_parser("parse", help="Parse ingredient lines for discovered/fetched candidates")
    _add_common_args(p)

    p = sub.add_parser("match", help="Match parsed ingredients to Food rows; compute coverage")
    _add_common_args(p)
    p.add_argument(
        "--minimum-match-coverage", type=float, default=pipeline.DEFAULT_MINIMUM_MATCH_COVERAGE,
        help=f"Line-coverage threshold below which a candidate is held for review "
             f"(default: {pipeline.DEFAULT_MINIMUM_MATCH_COVERAGE})",
    )

    p = sub.add_parser("analyse", help="Run nutrition + robustness analysis on matched candidates")
    _add_common_args(p)
    p.add_argument(
        "--simulation-count", type=int, default=pipeline.DEFAULT_SIMULATION_COUNT,
        help=f"Monte Carlo draws per robustness metric (default: {pipeline.DEFAULT_SIMULATION_COUNT})",
    )
    p.add_argument(
        "--random-seed", type=int, default=pipeline.DEFAULT_RANDOM_SEED,
        help=f"Seed for reproducible simulation (default: {pipeline.DEFAULT_RANDOM_SEED})",
    )

    p = sub.add_parser("review-export", help="Write a human-reviewable review file")
    _add_common_args(p, review_file=True)

    p = sub.add_parser(
        "import-approved",
        help="Import candidates marked approved in the review file (the only command that publishes)",
    )
    _add_common_args(p, review_file=True)
    p.add_argument("--dry-run", action="store_true", help="Validate and report what would import, write nothing")

    p = sub.add_parser("refresh", help="Re-fetch/re-analyse already-imported fetch-sourced recipes")
    _add_common_args(p)
    p.add_argument("--force-refresh", action="store_true", help="Bypass the page cache")
    p.add_argument(
        "--simulation-count", type=int, default=pipeline.DEFAULT_SIMULATION_COUNT,
        help=f"Monte Carlo draws per robustness metric (default: {pipeline.DEFAULT_SIMULATION_COUNT})",
    )
    p.add_argument(
        "--random-seed", type=int, default=pipeline.DEFAULT_RANDOM_SEED,
        help=f"Seed for reproducible simulation (default: {pipeline.DEFAULT_RANDOM_SEED})",
    )

    p = sub.add_parser("report", help="Print a run summary from the current cache state")
    _add_common_args(p)

    p = sub.add_parser(
        "health-check",
        help="Re-check imported fetch-sourced recipes for dead links, redirects, drift, and missing "
             "licences (read-only — writes a report only, never modifies a Recipe)",
    )
    p.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR,
        help=f"Local page cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    p.add_argument(
        "--report-file", type=Path, default=DEFAULT_CACHE_DIR / "health_report.json",
        help=f"Report path, .json (default: {DEFAULT_CACHE_DIR / 'health_report.json'}); "
             "a sibling .csv is written alongside it",
    )
    p.add_argument(
        "--use-cache", action="store_true",
        help="Allow cached source pages instead of always re-fetching live "
             "(faster reruns, but may miss a link that just broke)",
    )
    p.add_argument("--verbose", action="store_true", help="Debug-level logging")

    p = sub.add_parser(
        "validate-aliases",
        help="Validate the ingredient_aliases.py registry (read-only) — malformed entries, duplicate "
             "keys, dangling preferred target ids, name drift, incomplete nutrition coverage",
    )
    p.add_argument("--verbose", action="store_true", help="Debug-level logging")

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    handlers = {
        "discover": pipeline.cmd_discover,
        "fetch": pipeline.cmd_fetch,
        "parse": pipeline.cmd_parse,
        "match": pipeline.cmd_match,
        "analyse": pipeline.cmd_analyse,
        "review-export": pipeline.cmd_review_export,
        "import-approved": pipeline.cmd_import_approved,
        "refresh": pipeline.cmd_refresh,
        "report": pipeline.cmd_report,
        "health-check": pipeline.cmd_health_check,
        "validate-aliases": pipeline.cmd_validate_aliases,
    }
    exit_code = handlers[args.command](args)
    sys.exit(exit_code or 0)
