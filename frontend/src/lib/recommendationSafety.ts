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
