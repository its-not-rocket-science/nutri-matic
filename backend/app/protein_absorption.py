"""Total absorbed protein — protein weighted by DIAAS/PDCAAS
digestibility, i.e. how much actually gets absorbed rather than the raw
"protein on the label" figure.

Two figures side by side, same convention as every other DIAAS/PDCAAS
pairing in this app: DIAAS uses the limiting amino acid's own
digestibility coefficient (that's the amino acid governing protein
synthesis capacity for this mix, so its coefficient — not an average
across all nine — is the one that actually matters); PDCAAS already
reduces to one overall coefficient by definition. Either can be None if
that method's digestibility data is incomplete for this mix — see
scoring.IncompleteAminoAcidProfile for why a missing coefficient refuses
rather than guesses.
"""

from dataclasses import dataclass

from .aggregation import AminoAcidAggregate, WeightedFood, compute_protein_quality_with_coverage
from .reference_patterns import DEFAULT_PATTERN
from .scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas


@dataclass
class AbsorbedProtein:
    total_protein_g: float
    diaas_absorbed_g: float | None
    pdcaas_absorbed_g: float | None
    # coverage_fraction < 1.0 means the corresponding *_absorbed_g was
    # computed from only the ingredients with complete amino acid +
    # digestibility data for that method (see
    # aggregation.compute_protein_quality_with_coverage) — the absorbed
    # grams are scaled to that covered protein, not the full total, since
    # the excluded ingredients' own digestibility is unknown.
    diaas_coverage_fraction: float | None = None
    pdcaas_coverage_fraction: float | None = None


def compute_absorbed_protein(
    aggregate: AminoAcidAggregate, pattern: str = DEFAULT_PATTERN
) -> AbsorbedProtein | None:
    """None if nothing in the mix contributed protein — nothing meaningful
    to report, same convention as bioavailability.py/food_chemistry.py."""
    if aggregate.total_protein_g <= 0:
        return None

    diaas_absorbed_g = None
    if aggregate.digestibility_diaas is not None:
        try:
            diaas_result = compute_diaas(aggregate.amino_acids, aggregate.digestibility_diaas, pattern)
            coefficient = aggregate.digestibility_diaas.get(diaas_result.limiting_amino_acid)
            if coefficient is not None:
                diaas_absorbed_g = aggregate.total_protein_g * coefficient
        except (IncompleteAminoAcidProfile, UnknownReferencePattern):
            pass

    pdcaas_absorbed_g = (
        aggregate.total_protein_g * aggregate.digestibility_pdcaas
        if aggregate.digestibility_pdcaas is not None
        else None
    )

    return AbsorbedProtein(
        total_protein_g=aggregate.total_protein_g,
        diaas_absorbed_g=diaas_absorbed_g,
        pdcaas_absorbed_g=pdcaas_absorbed_g,
    )


def compute_absorbed_protein_with_coverage(
    items: list[WeightedFood], pattern: str = DEFAULT_PATTERN
) -> AbsorbedProtein | None:
    """Coverage-aware counterpart to compute_absorbed_protein: each method's
    absorbed grams are computed from just the ingredients with complete data
    for it (compute_protein_quality_with_coverage), scaled to that *covered*
    protein rather than the full mix's total — applying a digestibility
    coefficient derived from a subset of ingredients to protein from
    ingredients outside that subset would overstate confidence in a number
    that subset never actually measured. total_protein_g still reports the
    true, full total (informational), independent of either method's
    coverage. None only if the mix has no protein-contributing ingredients
    at all."""
    total_protein_g = sum(
        max(item.food.protein_g_per_100g * item.quantity_g / 100, 0.0) for item in items
    )
    if total_protein_g <= 0:
        return None

    diaas_quality = compute_protein_quality_with_coverage(items, "diaas", pattern)
    pdcaas_quality = compute_protein_quality_with_coverage(items, "pdcaas", pattern)

    diaas_absorbed_g = None
    if diaas_quality.score is not None and diaas_quality.aggregate is not None:
        coefficient = diaas_quality.aggregate.digestibility_diaas.get(diaas_quality.score.limiting_amino_acid)
        if coefficient is not None:
            diaas_absorbed_g = diaas_quality.covered_protein_g * coefficient

    pdcaas_absorbed_g = None
    if pdcaas_quality.score is not None and pdcaas_quality.aggregate is not None:
        if pdcaas_quality.aggregate.digestibility_pdcaas is not None:
            pdcaas_absorbed_g = pdcaas_quality.covered_protein_g * pdcaas_quality.aggregate.digestibility_pdcaas

    return AbsorbedProtein(
        total_protein_g=total_protein_g,
        diaas_absorbed_g=diaas_absorbed_g,
        pdcaas_absorbed_g=pdcaas_absorbed_g,
        diaas_coverage_fraction=diaas_quality.coverage_fraction if diaas_absorbed_g is not None else None,
        pdcaas_coverage_fraction=pdcaas_quality.coverage_fraction if pdcaas_absorbed_g is not None else None,
    )
