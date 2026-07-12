"""DIAAS / PDCAAS protein quality scoring.

DIAAS uses amino-acid-specific true ileal digestibility (SID). It is not
capped at 100% — values above 100 are valid and reported as-is.

PDCAAS uses a single overall (typically faecal) crude protein digestibility
coefficient applied after the limiting amino acid ratio is found, and is
conventionally capped at 100%.
"""

from dataclasses import dataclass

from .reference_patterns import AMINO_ACIDS, DEFAULT_PATTERN, REFERENCE_PATTERNS, AminoAcidPattern


@dataclass
class ScoreResult:
    score: float
    limiting_amino_acid: str
    per_aa_ratios: dict[str, float]
    pattern_used: str


class UnknownReferencePattern(ValueError):
    pass


def _get_pattern(pattern_name: str) -> AminoAcidPattern:
    try:
        return REFERENCE_PATTERNS[pattern_name]
    except KeyError:
        raise UnknownReferencePattern(
            f"Unknown reference pattern '{pattern_name}'. "
            f"Available: {sorted(REFERENCE_PATTERNS)}"
        ) from None


def _limiting(ratios: dict[str, float]) -> str:
    return min(ratios, key=ratios.get)


def compute_diaas(
    amino_acids_mg_per_g_protein: AminoAcidPattern,
    digestibility: dict[str, float] | float,
    pattern_name: str = DEFAULT_PATTERN,
) -> ScoreResult:
    """digestibility: per-amino-acid SID coefficients (0-1), or a single
    coefficient applied uniformly to all amino acids."""
    pattern = _get_pattern(pattern_name)

    ratios: dict[str, float] = {}
    for aa in AMINO_ACIDS:
        coeff = digestibility[aa] if isinstance(digestibility, dict) else digestibility
        digestible_aa = amino_acids_mg_per_g_protein[aa] * coeff
        ratios[aa] = (digestible_aa / pattern[aa]) * 100

    limiting = _limiting(ratios)
    return ScoreResult(
        score=ratios[limiting],
        limiting_amino_acid=limiting,
        per_aa_ratios=ratios,
        pattern_used=pattern_name,
    )


def compute_pdcaas(
    amino_acids_mg_per_g_protein: AminoAcidPattern,
    overall_digestibility: float,
    pattern_name: str = DEFAULT_PATTERN,
) -> ScoreResult:
    """overall_digestibility: single crude protein digestibility coefficient
    (0-1), typically faecal. Score is capped at 100%."""
    pattern = _get_pattern(pattern_name)

    raw_ratios = {aa: (amino_acids_mg_per_g_protein[aa] / pattern[aa]) * 100 for aa in AMINO_ACIDS}
    limiting = _limiting(raw_ratios)

    score = min(raw_ratios[limiting] * overall_digestibility, 100.0)
    return ScoreResult(
        score=score,
        limiting_amino_acid=limiting,
        per_aa_ratios=raw_ratios,
        pattern_used=pattern_name,
    )
