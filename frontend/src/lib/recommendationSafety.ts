// Mirrors app/recommendation_safety.py's SafetyWarningCode messages —
// prompt 11's "structured warning codes rather than relying only on
// prose". Shown once per panel (not repeated on every card) so a
// standing caveat like "these are estimates" or "this profile has a
// medical dietary consideration this feature can't read" is visible but
// unobtrusive, never omitted.
const WARNING_MESSAGES: Record<string, string> = {
	data_is_estimate:
		'Nutrient values come from reference food-composition data — actual content varies by brand, growing conditions and preparation.',
	recipe_nutrients_vary:
		"A recipe's real nutrient content depends on the exact ingredients, brands and cooking method used, which can differ from what's shown here.",
	absorption_varies:
		'How much of a nutrient the body actually absorbs, and how much any individual needs, both vary — these are population reference values, not a personal measurement, and this is general nutritional information rather than medical advice.',
	pregnancy_conservative:
		'This profile is marked as pregnant — upper-limit comparisons are kept extra conservative here, but this remains general nutritional information, not antenatal medical advice.',
	lactation_conservative:
		'This profile is marked as lactating — upper-limit comparisons are kept extra conservative here, but this remains general nutritional information, not medical advice.',
	medical_constraint_present:
		"This profile has a stored medical dietary consideration. This feature does not read that note and does not know your prescribed diet's specific requirements — it must not be used to override it. Check with whoever prescribed it before changing what you eat."
};

export function safetyWarningMessage(code: string): string {
	return WARNING_MESSAGES[code] ?? code;
}

// Mirrors app/recommend_ingredients.py's NoSuggestionReason — public-
// launch hardening prompt 4 item 6: "No safe or useful addition found"
// is a real, valid result, but a bare version of that message with no
// explanation is exactly the confusing dead end the prompt calls out.
const NO_SUGGESTION_REASON_MESSAGES: Record<string, string> = {
	no_shortfall: "Nothing tracked is currently below target for this — there's no gap to close.",
	no_eligible_candidates:
		'No practical, dietarily-suitable food in the catalogue stood out for this — try a different priority.',
	energy_limit:
		'Every food that would help was above the calorie limit set for this — try raising or removing it.',
	no_meaningful_improvement:
		"A few options were considered, but none would meaningfully move the needle — you're likely close to target already."
};

export function noSuggestionReasonMessage(code: string): string {
	return NO_SUGGESTION_REASON_MESSAGES[code] ?? 'No safe or useful addition found for the current priorities.';
}

// Operational-hardening prompt 3: labels/caveats for the carbon/
// glycaemic classification metadata in ScoreBreakdown (see
// RecommendationCard.svelte's "Why this ranked here" panel) — approximate,
// category-based preferences, never shown as a bare adjustment number
// with no tier/confidence/basis attached. Kept out of the component
// itself so the actual wording lives in one place, same convention as
// the safety/no-suggestion messages above.

const CARBON_TIER_LABELS: Record<string, string> = {
	very_high: 'very high',
	high: 'high',
	medium: 'medium',
	low: 'low'
};

export function carbonTierLabel(tier: string): string {
	return CARBON_TIER_LABELS[tier] ?? tier;
}

const GLYCAEMIC_TIER_LABELS: Record<string, string> = {
	high: 'high',
	medium: 'medium',
	low: 'low'
};

export function glycaemicTierLabel(tier: string): string {
	return GLYCAEMIC_TIER_LABELS[tier] ?? tier;
}

// "provenance" — whose name the classification actually came from.
// Recipes/pairs/substitutions have no single name of their own to check,
// so this is the honest "what this is actually based on" disclosure the
// prompt's "dominant-ingredient recipe classification can miss important
// ingredients" requirement calls for.
export function classificationProvenanceNote(provenance: 'name_match' | 'dominant_ingredient_proxy' | null): string {
	if (provenance === 'dominant_ingredient_proxy') {
		return "based on this recipe's largest-by-weight ingredient only — other ingredients aren't reflected, and a different one could change the result";
	}
	if (provenance === 'name_match') {
		return "based on this food's own name";
	}
	return '';
}

// "basis" — glycaemic-only: why a "low" classification landed there.
// Never let a negligible-carbohydrate food (meat, fish, eggs, cheese,
// nuts) read as if it had been lab-measured and scored low — GI simply
// doesn't apply to a food with negligible carbohydrate at all.
export function glycaemicBasisNote(basis: 'category_match' | 'negligible_carbohydrate' | null): string {
	if (basis === 'negligible_carbohydrate') {
		return "negligible carbohydrate — glycaemic index isn't really measured for foods like this, not a tested \"low\" result";
	}
	if (basis === 'category_match') {
		return 'a published category average, not this specific food measured';
	}
	return '';
}

export const CARBON_METHODOLOGY_NOTE =
	'A coarse, name-keyword estimate anchored to published food-carbon-footprint research — not a per-product lifecycle assessment, and not available for every food.';

export const GLYCAEMIC_METHODOLOGY_NOTE =
	"A coarse, name-keyword estimate, not a measured glycaemic index — GI itself isn't the same as glycaemic load (which also depends on portion size and carbohydrate quantity), and real GI varies with ripeness, variety and preparation. Common staples (bread, rice, potato, banana) are deliberately left unclassified rather than guessed. This is general nutritional information, not a prediction of your own blood-sugar response or medical advice.";
