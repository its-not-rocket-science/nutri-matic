// The nutrient-gap recommendation endpoints (recommend_ingredients.py,
// recommend_recipes.py, recommend_pairs.py) return bare nutrient keys —
// "iron", "fiber_total" — not display names, so the frontend needs its
// own key -> UK-English label mapping for recommendation cards. This is
// intentionally separate from NutrientAmount.name (which the API does
// supply for full nutrient-list endpoints) rather than a second source of
// truth: those endpoints aggregate arbitrary candidate foods that were
// never loaded as full NutrientAmount rows, so no name is available to
// reuse from the response itself.
const OVERRIDES: Record<string, string> = {
	energy: 'Energy',
	protein: 'Protein',
	fiber_total: 'Fibre',
	fiber_soluble: 'Soluble fibre',
	fiber_insoluble: 'Insoluble fibre',
	resistant_starch: 'Resistant starch',
	saturated_fat: 'Saturated fat',
	monounsaturated_fat: 'Monounsaturated fat',
	polyunsaturated_fat: 'Polyunsaturated fat',
	vitamin_a: 'Vitamin A',
	vitamin_c: 'Vitamin C',
	vitamin_d: 'Vitamin D',
	vitamin_e: 'Vitamin E',
	vitamin_k1: 'Vitamin K1',
	vitamin_k2: 'Vitamin K2',
	vitamin_b6: 'Vitamin B6',
	vitamin_b12: 'Vitamin B12',
	ala: 'ALA (omega-3)',
	epa: 'EPA (omega-3)',
	dha: 'DHA (omega-3)',
	la: 'LA (omega-6)',
	iron_heme: 'Haem iron',
	iron_non_heme: 'Non-haem iron'
};

/** UK-English display label for a nutrient key, e.g. "fiber_total" ->
 * "Fibre". Falls back to a straightforward humanisation (underscores to
 * spaces, first letter capitalised) for anything not in OVERRIDES. */
export function nutrientLabel(key: string): string {
	const override = OVERRIDES[key];
	if (override) return override;
	const words = key.split('_');
	const first = words[0];
	return [first.charAt(0).toUpperCase() + first.slice(1), ...words.slice(1)].join(' ');
}
