"""python -m app.canonical_foods validate | load [--dry-run]"""

import argparse
import sys

from .csv_schema import CSV_PATH, CanonicalCsvError, file_sha256, load_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.canonical_foods", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Check the CSV file only (no database)")
    p = sub.add_parser("load", help="Load the CSV into the database DATABASE_URL points at")
    p.add_argument("--dry-run", action="store_true", help="Run every check and the load, then roll back")
    args = parser.parse_args(argv)

    try:
        canonicals = load_file()
    except CanonicalCsvError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"{CSV_PATH.name}: {len(canonicals)} canonical foods, "
          f"{sum(len(c.aliases) for c in canonicals.values())} aliases, sha256 {file_sha256()}")
    if args.command == "validate":
        return 0

    from ..database import SessionLocal
    from .loader import load

    db = SessionLocal()
    try:
        result = load(db, canonicals)
        print(result.summary())
        for label in ("created", "updated", "retired"):
            for key in getattr(result, label):
                print(f"  {label}: {key}")
        if args.dry_run:
            db.rollback()
            print("dry run: rolled back, nothing written")
        else:
            db.commit()
    except CanonicalCsvError as e:
        db.rollback()
        print(e, file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
