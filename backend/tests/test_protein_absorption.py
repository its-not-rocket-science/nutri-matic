from app.aggregation import AminoAcidAggregate
from app.protein_absorption import compute_absorbed_protein
from app.reference_patterns import AMINO_ACIDS

# amino acid content (mg/g protein) chosen so lysine is clearly the
# limiting one regardless of which reference pattern is used — every other
# amino acid is generously abundant
_AMINO_ACIDS = {aa: 1000.0 for aa in AMINO_ACIDS}
_AMINO_ACIDS["lysine"] = 10.0


def _aggregate(digestibility_diaas=None, digestibility_pdcaas=None, total_protein_g=20.0, amino_acids=None):
    return AminoAcidAggregate(
        amino_acids=amino_acids if amino_acids is not None else dict(_AMINO_ACIDS),
        digestibility_diaas=digestibility_diaas,
        digestibility_pdcaas=digestibility_pdcaas,
        total_protein_g=total_protein_g,
    )


def test_none_when_no_protein():
    aggregate = _aggregate(total_protein_g=0.0)
    assert compute_absorbed_protein(aggregate) is None


def test_diaas_uses_the_limiting_amino_acids_own_coefficient():
    # lysine (the limiting AA) has a distinctly different coefficient (0.5)
    # from every other amino acid (0.9) — the result must use lysine's,
    # not an average across all nine
    digestibility = {aa: 0.9 for aa in AMINO_ACIDS}
    digestibility["lysine"] = 0.5
    aggregate = _aggregate(digestibility_diaas=digestibility, total_protein_g=20.0)

    result = compute_absorbed_protein(aggregate)
    assert result.diaas_absorbed_g is not None
    assert result.diaas_absorbed_g == 20.0 * 0.5


def test_pdcaas_uses_its_single_overall_coefficient():
    aggregate = _aggregate(digestibility_pdcaas=0.85, total_protein_g=20.0)
    result = compute_absorbed_protein(aggregate)
    assert result.pdcaas_absorbed_g == 20.0 * 0.85


def test_diaas_none_when_digestibility_missing_entirely():
    aggregate = _aggregate(digestibility_diaas=None, digestibility_pdcaas=0.85, total_protein_g=20.0)
    result = compute_absorbed_protein(aggregate)
    assert result.diaas_absorbed_g is None
    assert result.pdcaas_absorbed_g is not None  # unaffected by DIAAS being incomplete


def test_pdcaas_none_when_digestibility_missing_entirely():
    digestibility = {aa: 0.9 for aa in AMINO_ACIDS}
    aggregate = _aggregate(digestibility_diaas=digestibility, digestibility_pdcaas=None, total_protein_g=20.0)
    result = compute_absorbed_protein(aggregate)
    assert result.pdcaas_absorbed_g is None
    assert result.diaas_absorbed_g is not None  # unaffected by PDCAAS being incomplete


def test_diaas_none_when_one_amino_acid_missing_a_coefficient():
    digestibility = {aa: 0.9 for aa in AMINO_ACIDS}
    digestibility["lysine"] = None  # the limiting AA specifically missing its coefficient
    aggregate = _aggregate(digestibility_diaas=digestibility, total_protein_g=20.0)
    result = compute_absorbed_protein(aggregate)
    assert result.diaas_absorbed_g is None


def test_diaas_none_when_amino_acid_content_incomplete():
    amino_acids = dict(_AMINO_ACIDS)
    amino_acids["threonine"] = None
    digestibility = {aa: 0.9 for aa in AMINO_ACIDS}
    aggregate = _aggregate(digestibility_diaas=digestibility, amino_acids=amino_acids, total_protein_g=20.0)
    result = compute_absorbed_protein(aggregate)
    assert result.diaas_absorbed_g is None


def test_total_protein_g_passed_through():
    aggregate = _aggregate(total_protein_g=42.0)
    result = compute_absorbed_protein(aggregate)
    assert result.total_protein_g == 42.0
