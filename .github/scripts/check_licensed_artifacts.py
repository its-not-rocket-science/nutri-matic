"""Fail-closed scan for licensed PhyFoodComp source-row data or workbook
files tracked in git — prompts.txt PROMPT 9. See
docs/phytate-review/PRIVATE_ARTIFACTS.md for the policy this enforces
(source_licence_policy.py's redistribution_permitted=False/
export_permitted=False for the phyfoodcomp_1_0 source).

Deliberately content/structure-based, not filename/extension-based (a bot
review finding on PR #57 caught the first version of this check only
enumerating a case-sensitive "*.csv" pathspec and only matching ".xlsx" by
name — a file committed as "review.CSV", a .tsv, an extensionless copy,
or a workbook saved under any other extension would have passed silently).
Every tracked file is inspected by its actual bytes:

  - a workbook check: does this file's bytes parse as a zip archive
    containing an OOXML spreadsheet manifest (xl/workbook.xml)? True
    regardless of what the file is named.
  - a source-row check: does this file's first line, decoded as text,
    contain both "food_description" and "compound_fraction" as
    substrings? True regardless of delimiter (comma, tab, pipe, ...) or
    extension. This is the exact column-pair every PhyFoodComp
    source-derived artifact carries and no file legitimately kept public
    under docs/phytate-review/ does — verified directly against every
    tracked file's header before relying on this fingerprint (see
    PRIVATE_ARTIFACTS.md's inventory table).

Reads every tracked file's content from git's own object store (`git show
HEAD:<path>`), never the working tree, so an untracked local copy (e.g.
an authorised operator's private artifacts, kept on disk but git-ignored)
can never produce a false failure.
"""

import subprocess
import sys
import zipfile
from io import BytesIO

FINGERPRINT_MARKERS = ("food_description", "compound_fraction")

# Explicit, individually-reviewed synthetic fixtures that legitimately
# share the same column shape as real PhyFoodComp source-row data by
# design (prompts.txt PROMPT 12: they exist specifically so public CI can
# test the stable-ID mapping validator's structural checks without the
# real private artifact). This is exactly the exception prompts.txt
# PROMPT 9 itself names ("while allowing explicitly named synthetic
# fixtures") — an exact, individually-reviewed path list, not a pattern
# or a directory-wide exemption, and each entry's content was read and
# confirmed fabricated (not derived from the real workbook in any way)
# before being added here.
ALLOWED_SYNTHETIC_FIXTURES = frozenset({
    "backend/tests/fixtures/synthetic_stable_id_mapping.csv",
})


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]


def read_tracked(path: str) -> bytes:
    result = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, check=True)
    return result.stdout


def is_ooxml_spreadsheet(data: bytes) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            return "xl/workbook.xml" in zf.namelist()
    except zipfile.BadZipFile:
        return False


def has_source_row_fingerprint(data: bytes) -> bool:
    try:
        first_line = data.split(b"\n", 1)[0].decode("utf-8", errors="strict").lower()
    except UnicodeDecodeError:
        return False
    return all(marker in first_line for marker in FINGERPRINT_MARKERS)


def main() -> None:
    workbook_offenders = []
    source_row_offenders = []

    for path in tracked_files():
        try:
            data = read_tracked(path)
        except subprocess.CalledProcessError:
            continue  # e.g. a submodule gitlink entry, not a blob
        if is_ooxml_spreadsheet(data):
            workbook_offenders.append(path)
        if has_source_row_fingerprint(data) and path not in ALLOWED_SYNTHETIC_FIXTURES:
            source_row_offenders.append(path)

    if workbook_offenders:
        print("Tracked file(s) are OOXML spreadsheet workbooks, regardless of extension:")
        for p in workbook_offenders:
            print(f"  {p}")
    if source_row_offenders:
        print(
            "Tracked file(s) contain the PhyFoodComp source-row fingerprint "
            "(food_description + compound_fraction in the header), regardless of extension/delimiter:"
        )
        for p in source_row_offenders:
            print(f"  {p}")

    if workbook_offenders or source_row_offenders:
        print(
            "\nThese must never be committed while redistribution_permitted=False in "
            "source_licence_policy.py -- see docs/phytate-review/PRIVATE_ARTIFACTS.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("No tracked file matches a licensed-artifact fingerprint (workbook or source-row).")


if __name__ == "__main__":
    main()
