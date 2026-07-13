"""Combines a weighted list of (Food, quantity_g) into a single nutrient
profile — shared by the recipe builder (ingredients -> per-serving) and the
diary (a day's logged entries -> daily total).

Amino acid / digestibility combination follows FAO's approach for mixed
protein sources: each ingredient's contribution is weighted by the *protein*
it contributes (not its mass), since DIAAS/PDCAAS are inherently
per-gram-protein measures. If any protein-contributing ingredient is
missing an amino acid or digestibility value, the mixture's value for that
amino acid is left null rather than silently understating it — the
existing compute_diaas/compute_pdcaas machinery already refuses to score
an incomplete profile, and that's the right behavior here too: a wrong
DIAAS number is worse than an honest "can't be scored."

Vitamin/mineral/fibre/fat totals are handled differently and more
permissively: a missing FoodNutrient row for an ingredient just
contributes zero for that nutrient, rather than making the whole mixture
"unscorable." Diet-level totals are inherently an approximation (matches
how any food diary app works) — unlike DIAAS, there's no single "wrong
number" risk from a partial sum, so failing loud here would just make the
feature unusable for the very common case of one ingredient lacking full
micronutrient data.
"""

from dataclasses import dataclass

from .models import Food, FoodNutrient
from .reference_patterns import AMINO_ACIDS


@dataclass
class WeightedFood:
    food: Food
    quantity_g: float


@dataclass
class AminoAcidAggregate:
    amino_acids: dict[str, float | None]
    digestibility_diaas: dict[str, float | None] | None
    digestibility_pdcaas: float | None
    total_protein_g: float


def aggregate_amino_acids(items: list[WeightedFood]) -> AminoAcidAggregate:
    total_protein = 0.0
    aa_numerators = dict.fromkeys(AMINO_ACIDS, 0.0)
    diaas_numerators = dict.fromkeys(AMINO_ACIDS, 0.0)
    aa_complete = dict.fromkeys(AMINO_ACIDS, True)
    diaas_complete = dict.fromkeys(AMINO_ACIDS, True)
    pdcaas_numerator = 0.0
    pdcaas_complete = True

    for item in items:
        protein_g = item.food.protein_g_per_100g * item.quantity_g / 100
        if protein_g <= 0:
            continue
        total_protein += protein_g

        for aa in AMINO_ACIDS:
            aa_value = item.food.amino_acids.get(aa)
            if aa_value is None:
                aa_complete[aa] = False
                diaas_complete[aa] = False
                continue
            aa_mg = aa_value * protein_g
            aa_numerators[aa] += aa_mg

            if item.food.digestibility_diaas is None:
                diaas_complete[aa] = False
                continue
            diaas_coefficient = item.food.digestibility_diaas.get(aa)
            if diaas_coefficient is None:
                diaas_complete[aa] = False
                continue
            diaas_numerators[aa] += aa_mg * diaas_coefficient

        if item.food.digestibility_pdcaas is None:
            pdcaas_complete = False
        else:
            pdcaas_numerator += protein_g * item.food.digestibility_pdcaas

    if total_protein <= 0:
        return AminoAcidAggregate(
            amino_acids=dict.fromkeys(AMINO_ACIDS),
            digestibility_diaas=None,
            digestibility_pdcaas=None,
            total_protein_g=0.0,
        )

    amino_acids = {
        aa: (aa_numerators[aa] / total_protein) if aa_complete[aa] else None for aa in AMINO_ACIDS
    }
    digestibility_diaas = {
        aa: (diaas_numerators[aa] / aa_numerators[aa]) if diaas_complete[aa] and aa_numerators[aa] > 0 else None
        for aa in AMINO_ACIDS
    }
    digestibility_pdcaas = (pdcaas_numerator / total_protein) if pdcaas_complete else None

    return AminoAcidAggregate(
        amino_acids=amino_acids,
        digestibility_diaas=digestibility_diaas,
        digestibility_pdcaas=digestibility_pdcaas,
        total_protein_g=total_protein,
    )


def aggregate_nutrients(
    items: list[WeightedFood], food_nutrients_by_food_id: dict[int, list[FoodNutrient]], divide_by: float = 1.0
) -> dict[str, float]:
    """Sums amount_per_100g * quantity_g / 100 across items for each
    nutrient key, then divides by `divide_by` (servings, for a recipe;
    1 for a diary day's raw total)."""
    totals: dict[str, float] = {}
    for item in items:
        for fn in food_nutrients_by_food_id.get(item.food.id, []):
            contribution = fn.amount_per_100g * item.quantity_g / 100
            totals[fn.nutrient_key] = totals.get(fn.nutrient_key, 0.0) + contribution
    if divide_by and divide_by != 1.0:
        totals = {k: v / divide_by for k, v in totals.items()}
    return totals
