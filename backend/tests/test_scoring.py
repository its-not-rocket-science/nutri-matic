import pytest

from app.reference_patterns import REFERENCE_PATTERNS
from app.scoring import (
    IncompleteAminoAcidProfile,
    UnknownReferencePattern,
    compute_diaas,
    compute_pdcaas,
)

PATTERN = REFERENCE_PATTERNS["child_3y_adult"]


def test_diaas_matches_pattern_scores_100():
    result = compute_diaas(PATTERN, digestibility=1.0)
    assert result.score == pytest.approx(100.0)
    assert all(pytest.approx(v) == 100.0 for v in result.per_aa_ratios.values())


def test_diaas_identifies_limiting_amino_acid():
    aa = dict(PATTERN)
    aa["lysine"] = PATTERN["lysine"] * 0.5
    result = compute_diaas(aa, digestibility=1.0)
    assert result.limiting_amino_acid == "lysine"
    assert result.score == pytest.approx(50.0)


def test_diaas_can_exceed_100():
    aa = {k: v * 2 for k, v in PATTERN.items()}
    result = compute_diaas(aa, digestibility=1.0)
    assert result.score == pytest.approx(200.0)


def test_diaas_per_amino_acid_digestibility():
    aa = dict(PATTERN)
    digestibility = {k: 0.9 for k in PATTERN}
    digestibility["tryptophan"] = 0.5
    result = compute_diaas(aa, digestibility=digestibility)
    assert result.limiting_amino_acid == "tryptophan"
    assert result.score == pytest.approx(50.0)


def test_pdcaas_applies_overall_digestibility():
    aa = dict(PATTERN)
    aa["lysine"] = PATTERN["lysine"] * 0.8
    result = compute_pdcaas(aa, overall_digestibility=0.9)
    assert result.limiting_amino_acid == "lysine"
    assert result.score == pytest.approx(80.0 * 0.9)


def test_pdcaas_capped_at_100():
    aa = {k: v * 2 for k, v in PATTERN.items()}
    result = compute_pdcaas(aa, overall_digestibility=1.0)
    assert result.score == pytest.approx(100.0)


def test_unknown_pattern_raises():
    with pytest.raises(UnknownReferencePattern):
        compute_diaas(PATTERN, digestibility=1.0, pattern_name="nonexistent")


def test_diaas_raises_on_missing_amino_acid():
    aa = dict(PATTERN)
    aa["tryptophan"] = None
    with pytest.raises(IncompleteAminoAcidProfile):
        compute_diaas(aa, digestibility=1.0)


def test_diaas_raises_on_missing_digestibility_coefficient():
    digestibility = {k: 0.9 for k in PATTERN}
    digestibility["lysine"] = None
    with pytest.raises(IncompleteAminoAcidProfile):
        compute_diaas(PATTERN, digestibility=digestibility)


def test_pdcaas_raises_on_missing_amino_acid():
    aa = dict(PATTERN)
    aa["valine"] = None
    with pytest.raises(IncompleteAminoAcidProfile):
        compute_pdcaas(aa, overall_digestibility=0.9)
