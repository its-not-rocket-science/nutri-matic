"""Repository-level policy test (prompts.txt PROMPT 4 of the phytate
extension): "prefer a testable dependency/service boundary over grep
alone, but add a repository policy test if that is the most reliable
defence against accidental new uses."

app.source_licence_policy.load_compound_observations is the mandatory
read boundary for anything that serves CompoundObservation rows to a
caller. There is no way to enforce "always call this, never query
CompoundObservation directly" at the type-checker level in this
codebase, so this test does it structurally: every .py file under
backend/app that references CompoundObservation must be on the
allowlist below, and adding a new one requires a deliberate edit to this
test (and, implicitly, a reviewer noticing it) rather than silently
compiling."""

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# Every file under backend/app allowed to reference CompoundObservation
# directly, and why:
ALLOWED_FILES = {
    "models.py",  # the table definition itself
    "source_licence_policy.py",  # the boundary module itself
    "ingest_phytate.py",  # write path — automated ingestion, never serves a response
    "import_reviewed_phytate_mappings.py",  # write path — reviewed ingestion, never serves a response
}


def test_no_new_direct_compound_observation_references_outside_the_allowlist():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.name in ALLOWED_FILES:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "CompoundObservation" in text:
            offenders.append(str(path.relative_to(APP_DIR)))

    assert offenders == [], (
        f"{offenders} reference CompoundObservation directly but aren't in this test's ALLOWED_FILES. "
        "A service reading CompoundObservation rows to serve a response must go through "
        "app.source_licence_policy.load_compound_observations instead of querying it directly — "
        "either fix the reference or, if it's a legitimate new write-only/definition file, add it "
        "to ALLOWED_FILES deliberately."
    )


def test_allowed_files_still_exist_and_still_reference_it():
    """A stale allowlist entry (a file renamed/removed, or one that no
    longer actually touches CompoundObservation) would let this test's
    protection quietly rot -- catch that too."""
    for fname in ALLOWED_FILES:
        path = APP_DIR / fname
        assert path.is_file(), f"{fname} is in ALLOWED_FILES but no longer exists"
        assert "CompoundObservation" in path.read_text(encoding="utf-8"), (
            f"{fname} is in ALLOWED_FILES but no longer references CompoundObservation -- remove it"
        )
