"""FAO/WHO (2013) amino acid scoring patterns, mg indispensable amino acid
per g protein. Source: FAO. 2013. Dietary protein quality evaluation in
human nutrition. Report of an FAO Expert Consultation, Table 4.1.

Methionine+cysteine and phenylalanine+tyrosine are summed pairs, as used
in DIAAS/PDCAAS scoring.
"""

AminoAcidPattern = dict[str, float]

REFERENCE_PATTERNS: dict[str, AminoAcidPattern] = {
    "infant_0.5_3y": {
        "histidine": 20.0,
        "isoleucine": 32.0,
        "leucine": 66.0,
        "lysine": 57.0,
        "met_cys": 27.0,
        "phe_tyr": 52.0,
        "threonine": 31.0,
        "tryptophan": 8.5,
        "valine": 43.0,
    },
    "child_3y_adult": {
        "histidine": 16.0,
        "isoleucine": 30.0,
        "leucine": 61.0,
        "lysine": 48.0,
        "met_cys": 23.0,
        "phe_tyr": 41.0,
        "threonine": 25.0,
        "tryptophan": 6.6,
        "valine": 40.0,
    },
}

AMINO_ACIDS = (
    "histidine",
    "isoleucine",
    "leucine",
    "lysine",
    "met_cys",
    "phe_tyr",
    "threonine",
    "tryptophan",
    "valine",
)

DEFAULT_PATTERN = "child_3y_adult"
