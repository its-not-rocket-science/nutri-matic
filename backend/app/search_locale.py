"""The one place food search decides which locale's vocabulary to use.

Today every request is en-GB: the users are UK-based and there is no
profile setting yet (docs/plans/canonical-foods-plan.md, Q1). Words like
"chips" and "biscuit" mean different foods in en-GB and en-US, so the
locale changes which synonyms win (see search_synonyms.py).

Call sites ask `search_locale()` rather than reading the constant, so a
per-user setting can later be added here (e.g. read from the profile
passed in) without touching any caller.
"""

from __future__ import annotations

from typing import Any

EN_GB = "en-GB"
EN_US = "en-US"
SUPPORTED_SEARCH_LOCALES = frozenset({EN_GB, EN_US})
DEFAULT_SEARCH_LOCALE = EN_GB


def search_locale(profile: Any = None) -> str:
    """The locale food search should use for this request. `profile` is
    accepted (and ignored) so that the future per-user setting slots in
    here; every caller already passes what it has."""
    return DEFAULT_SEARCH_LOCALE
