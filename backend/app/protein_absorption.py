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

from .aggregation import AminoAcidAggregate
from .reference_patterns import DEFAULT_PATTERN
from .scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas


@dataclass
class AbsorbedProtein:
    total_protein_g: float
    diaas_absorbed_g: float | None
    pdcaas_absorbed_g: float | None


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
