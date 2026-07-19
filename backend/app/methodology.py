"""Global methodology/algorithm version stamps.

Nutri-Matic recomputes every score and %DRV comparison live, from current
code and current data. Diary entries are NOT frozen at the methodology that
was in effect when they were originally logged — a diary day always
reflects today's calculation methodology, not the methodology of the day
it was logged. This is a deliberate architectural choice (the app is a
live nutrient-tracking tool, not an audit log), not an oversight.

These version strings exist so API consumers can still detect *when* the
underlying methodology changed, even though Nutri-Matic itself never
stores or replays an old methodology against new data. If you are building
something that needs point-in-time reproducibility (e.g. a research
export), record these versions alongside the values you capture.

Bump policy — increment the relevant version whenever a change would alter
previously-computed output for the same input data:
  - SCORING_METHODOLOGY_VERSION: changes to scoring.py's DIAAS/PDCAAS
    formulas, or to reference_patterns.py's amino acid reference patterns.
  - DRV_METHODOLOGY_VERSION: changes to nutrients.py's DRV matrix values,
    resolve_drv()'s profile-selection logic, or the source those values
    are drawn from.

Use semver-ish MAJOR.MINOR.PATCH informally: MAJOR for a change that would
meaningfully move most users' numbers, MINOR for a scoped correction
(e.g. one nutrient's DRV), PATCH for a non-substantive fix (e.g. rounding).
"""

SCORING_METHODOLOGY_VERSION = "1.1.0"
DRV_METHODOLOGY_VERSION = "1.0.0"
