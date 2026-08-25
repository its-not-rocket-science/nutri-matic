"""Repository-level policy test — bot review on PR #62 (PROMPT 14 audit)
correctly caught that test_source_licence_policy_boundary.py only rejects
a new file that references `CompoundObservation` *directly*; a future
router could import `select_phytate_observations` from
app.phytate_selection (already allowlisted there, since that module is
itself the Prompt 6 read boundary's consumer) and pass a permitted
surface string like SURFACE_PERSONAL_FREE_INTERNAL_API from a route that
isn't actually the free personal internal API — the existing boundary
test would stay green throughout, because nothing in it inspects *which*
file calls `select_phytate_observations`, only which files mention
CompoundObservation by name.

This test closes that gap the same structural way: only
app/routers/phytate.py may call `select_phytate_observations` at all.
Today that's already true (grepped repo-wide); this test is what keeps
it true, the same "a testable dependency/service boundary, backed by a
repository policy test where that's the most reliable defence" approach
test_source_licence_policy_boundary.py's own docstring describes."""

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

ALLOWED_CALLERS = {
    "phytate_selection.py",  # the function's own definition
    "routers/phytate.py",  # the one real consumer -- Prompt 6/7
}


def test_only_the_phytate_router_calls_select_phytate_observations():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(APP_DIR)).replace("\\", "/")
        if rel in ALLOWED_CALLERS:
            continue
        if "select_phytate_observations(" in path.read_text(encoding="utf-8"):
            offenders.append(rel)

    assert offenders == [], (
        f"{offenders} call select_phytate_observations() but aren't on this test's ALLOWED_CALLERS. "
        "Passing a permitted surface string (e.g. SURFACE_PERSONAL_FREE_INTERNAL_API) from a route that "
        "isn't actually the free personal internal API would leak phytate data through a surface check that "
        "still technically passes -- either wire the new route through app/routers/phytate.py instead, or "
        "add it to ALLOWED_CALLERS deliberately (and update docs/phytate-production-readiness.md's control 4 "
        "if the isolation guarantee's scope changes)."
    )


def test_allowed_callers_still_exist_and_still_call_it():
    """Same staleness guard test_source_licence_policy_boundary.py uses
    for its own allowlist -- a renamed/removed file here would let this
    protection quietly rot."""
    for rel in ALLOWED_CALLERS:
        path = APP_DIR / rel
        assert path.is_file(), f"{rel} is in ALLOWED_CALLERS but no longer exists"
        assert "select_phytate_observations" in path.read_text(encoding="utf-8"), (
            f"{rel} is in ALLOWED_CALLERS but no longer references select_phytate_observations -- remove it"
        )
