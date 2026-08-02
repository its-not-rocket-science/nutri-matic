// Onboarding's step-1 pick — shared here (rather than duplicated per-page)
// so onboarding, the profile page, and the dashboard can never drift out of
// sync with each other or with the backend's VALID_GOALS (goals.py). A
// profile can now hold several at once (prompt 2.1) — see profile/
// +page.svelte and onboarding/+page.svelte's multi-select.
//
// weight_loss/visceral_fat_reduction additionally drive a real calculation
// (a calorie-deficit daily energy target — see the backend's energy_goal.py
// and the methodology page's "Weight-loss calorie target" section).
// longevity/athletic_stamina/athletic_strength/athletic_power (prompt 2.2)
// each drive their own nutrient-priority emphasis in gap-suggestions/
// meal-optimize — see the backend's goal_nutrient_priorities.py for the
// evidence basis behind each one, and why the three athletic goals are
// deliberately distinct rather than one generic "athlete" bucket.
// reduce_carbon_footprint/blood_sugar_stability both give ingredient/
// recipe suggestions a deliberately modest nudge toward lower-tier
// candidates — see the backend's carbon_footprint.py/glycaemic_load.py
// for the coarse, low-confidence, name-keyword tiering behind each (an
// honestly-labelled nudge, not a precise per-food measurement).
export type Goal =
	| 'protein_quality'
	| 'nutrient_gaps'
	| 'budget'
	| 'exploring'
	| 'weight_loss'
	| 'visceral_fat_reduction'
	| 'longevity'
	| 'athletic_stamina'
	| 'athletic_strength'
	| 'athletic_power'
	| 'reduce_carbon_footprint'
	| 'blood_sugar_stability';

export const GOAL_OPTIONS: { value: Goal; label: string }[] = [
	{ value: 'protein_quality', label: 'Track protein quality' },
	{ value: 'nutrient_gaps', label: 'Close nutrient gaps' },
	{ value: 'budget', label: 'Plan meals on a budget' },
	{ value: 'exploring', label: 'Just exploring' },
	{ value: 'weight_loss', label: 'Lose weight' },
	{ value: 'visceral_fat_reduction', label: 'Reduce visceral fat' },
	{ value: 'longevity', label: 'Longevity / healthspan' },
	{ value: 'athletic_stamina', label: 'Athletic performance — stamina/endurance' },
	{ value: 'athletic_strength', label: 'Athletic performance — strength' },
	{ value: 'athletic_power', label: 'Athletic performance — power' },
	{ value: 'reduce_carbon_footprint', label: 'Reduce carbon footprint' },
	{ value: 'blood_sugar_stability', label: 'Blood-sugar stability' }
];

export const GOAL_MESSAGES: Record<Goal, string> = {
	protein_quality:
		"You're set up to track DIAAS/PDCAAS on everything you log — check the score on your first meal below.",
	nutrient_gaps: "Your dashboard will always lead with today's biggest nutrient gap and a real food to close it.",
	budget: 'Add prices under Food Prices any time — the meal-plan optimiser will factor real cost into every suggestion.',
	exploring: 'Have a look around — nothing here is locked behind a purchase, and every number traces back to its source.',
	weight_loss:
		"Recipe and diary calorie targets now reflect a calorie deficit for weight loss, not plain maintenance — see the note wherever you see it, or the methodology page for exactly how it's calculated.",
	visceral_fat_reduction:
		"Recipe and diary calorie targets now reflect a calorie deficit (the same one used for general weight loss — there's no separate way to target visceral fat specifically), not plain maintenance.",
	longevity:
		'Gap-suggestions and meal-optimize now give extra weight to protein, fibre, ALA (omega-3), magnesium, and potassium — nutrients aligned with healthy-aging research, not a promise about your own lifespan.',
	athletic_stamina:
		'Gap-suggestions and meal-optimize now give extra weight to iron and potassium — the nutrients endurance training depletes fastest.',
	athletic_strength:
		'Gap-suggestions and meal-optimize now give extra weight to protein, calcium, magnesium, and zinc — supporting muscle protein synthesis and bone loading.',
	athletic_power:
		'Gap-suggestions and meal-optimize now give extra weight to protein, phosphorus, and zinc — phosphorus specifically for the fast ATP/phosphocreatine energy system explosive training draws on.',
	reduce_carbon_footprint:
		'Ingredient and recipe suggestions now give a modest nudge toward lower-carbon-footprint candidates — a coarse, name-based estimate, not a precise per-food measurement; see the methodology page for the honest limits.',
	blood_sugar_stability:
		"Ingredient and recipe suggestions now give a modest nudge toward lower-glycaemic-impact candidates — a coarse, name-based estimate (common staples like bread, rice, potato, and banana are deliberately left untiered, since their real impact varies too much by preparation to estimate from the name alone). This is general nutritional information, not a prediction of your own blood-sugar response or medical advice; see the methodology page for the honest limits."
};

// weight_loss/visceral_fat_reduction only — the two goals that actually
// change a calculation (energy_goal.py's WEIGHT_LOSS_GOALS). Exported so
// any page needing to know "does this goal affect calorie math" doesn't
// have to hardcode the pair itself.
export const WEIGHT_LOSS_GOALS: Goal[] = ['weight_loss', 'visceral_fat_reduction'];
