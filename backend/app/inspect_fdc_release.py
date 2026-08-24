"""Read-only inspection of locally-supplied FDC "Download Datasets"
directories for any genuine release/version evidence — prompts.txt
PROMPT 11.

Never downloads anything (works only against directories the operator
already has locally — see ingest_fdc.py's own --dir convention), never
infers a release from file timestamps (mtime/ctime reflect when a file
was extracted on this machine, not what USDA published), and never sets
`upstream_release_version` on its own. It only prints whatever evidence
was actually found, each entry explicitly labelled with its own
confidence/provenance, for a human to review before anyone hand-edits a
manifest file — see catalogue_manifest.py's module docstring for why
`upstream_release_version` stays `unrecorded_at_ingestion` absent real
evidence, and app.resolve_phytate_stable_ids for the actual
drift-detection mechanism this never replaces (a directory matching
whatever this command reports is not the same claim as "the live Food
catalogue was actually built from this exact directory" — only
re-ingesting and comparing catalogue_snapshot_checksum, as
resolve_phytate_stable_ids already does, establishes that).

Usage:
    python -m app.inspect_fdc_release \
        --dir path/to/FoodData_Central_foundation_food_csv_2026-04-30 \
        --dir path/to/FoodData_Central_branded_food_csv_2026-04-30
"""

import argparse
import re
from pathlib import Path

# USDA's own documented naming convention for FDC "Download Datasets"
# exports, e.g. "FoodData_Central_foundation_food_csv_2026-04-30" -- a
# directory matching this is NOT proof of anything (an operator can
# rename a directory to whatever they like; it is metadata *about* the
# files, not content *of* the files, exactly the same class of weak
# evidence as a file's mtime), so it is recorded as an explicitly
# low-confidence hint only, never promoted to upstream_release_version
# automatically.
_USDA_DIR_NAME_PATTERN = re.compile(r"FoodData_Central_(?P<dataset>[a-zA-Z_]+)_csv_(?P<date>\d{4}-\d{2}-\d{2})")

# Filenames that might legitimately carry embedded release/version text,
# matched case-insensitively against the file stem -- their *content* is
# never parsed by this tool (that would risk this tool itself becoming
# the thing that guesses a release from unreliable text), only surfaced
# for a human to read directly.
_CANDIDATE_METADATA_NAMES = ("readme", "metadata", "changelog", "version")


def inspect_directory(directory: Path) -> dict:
    """Read-only: never writes anything, never downloads anything.
    Returns whatever evidence was actually found in `directory`, each
    entry explicitly labelled with its own confidence/provenance --
    never a single resolved "the release is X" value."""
    findings: dict = {"directory": str(directory), "directory_name_hint": None, "metadata_files_found": []}

    name_match = _USDA_DIR_NAME_PATTERN.search(directory.name)
    if name_match:
        findings["directory_name_hint"] = {
            "dataset": name_match.group("dataset"),
            "date": name_match.group("date"),
            "confidence": (
                "low -- matches USDA's documented directory-naming convention, but a directory name is "
                "operator-supplied and not cryptographically tied to the file contents; never promoted to "
                "upstream_release_version automatically"
            ),
        }

    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        # startswith, not a raw substring check -- "version" is itself a
        # substring of "conversion", and every real FDC export directory
        # ships several *_conversion_factor.csv data files that would
        # otherwise be false-flagged as metadata (caught by testing this
        # against the real downloaded directories before relying on it).
        stem_lower = entry.stem.lower()
        if any(stem_lower.startswith(candidate) for candidate in _CANDIDATE_METADATA_NAMES):
            findings["metadata_files_found"].append(str(entry))

    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dir", dest="dirs", action="append", required=True,
        help="A local FDC 'Download Datasets' directory to inspect (repeatable).",
    )
    args = parser.parse_args()

    print("Read-only inspection -- nothing here is written to any manifest automatically.\n")
    for raw_dir in args.dirs:
        directory = Path(raw_dir)
        if not directory.is_dir():
            print(f"error: not a directory: {directory}")
            continue
        findings = inspect_directory(directory)
        print(f"{findings['directory']}:")
        if findings["directory_name_hint"]:
            hint = findings["directory_name_hint"]
            print(f"  directory name suggests dataset={hint['dataset']!r} date={hint['date']!r}")
            print(f"    confidence: {hint['confidence']}")
        else:
            print("  directory name does not match USDA's documented FDC export naming convention")
        if findings["metadata_files_found"]:
            print("  possible metadata files found (inspect manually -- content not parsed by this tool):")
            for f in findings["metadata_files_found"]:
                print(f"    {f}")
        else:
            print("  no README/metadata/changelog/version-named file found in this directory")
        print()

    print(
        "None of the above is sufficient evidence to set upstream_release_version on its own (see "
        "catalogue_manifest.py's module docstring for what counts as evidence). If you have independent "
        "confirmation of the actual USDA release identity (e.g. from FDC's own download page at the time "
        "these files were obtained), record it in docs/phytate-evidence-review.md first, then edit the "
        "manifest file by hand -- never edit it to match a guess, and never let this tool's output alone "
        "stand in for that evidence."
    )


if __name__ == "__main__":
    main()
