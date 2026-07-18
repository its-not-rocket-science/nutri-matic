// Onboarding's step-1 pick — shared here (rather than duplicated per-page)
// so onboarding, the profile page, and the dashboard can never drift out of
// sync with each other or with the backend's VALID_GOALS (routers/profile.py).
//
// weight_loss/visceral_fat_reduction additionally drive a real calculation
// (a calorie-deficit daily energy target — see the backend's energy_goal.py
// and the methodology page's "Weight-loss calorie target" section) — the
// other four are purely UI framing, no calculation depends on them.
export type Goal =
	| 'protein_quality'
	| 'nutrient_gaps'
	| 'budget'
	| 'exploring'
	| 'weight_loss'
	| 'visceral_fat_reduction';

export const GOAL_OPTIONS: { value: Goal; label: string }[] = [
	{ value: 'protein_quality', label: 'Track protein quality' },
	{ value: 'nutrient_gaps', label: 'Close nutrient gaps' },
	{ value: 'budget', label: 'Plan meals on a budget' },
	{ value: 'exploring', label: 'Just exploring' },
	{ value: 'weight_loss', label: 'Lose weight' },
	{ value: 'visceral_fat_reduction', label: 'Reduce visceral fat' }
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
		"Recipe and diary calorie targets now reflect a calorie deficit (the same one used for general weight loss — there's no separate way to target visceral fat specifically), not plain maintenance."
};

// weight_loss/visceral_fat_reduction only — the two goals that actually
// change a calculation (energy_goal.py's WEIGHT_LOSS_GOALS). Exported so
// any page needing to know "does this goal affect calorie math" doesn't
// have to hardcode the pair itself.
export const WEIGHT_LOSS_GOALS: Goal[] = ['weight_loss', 'visceral_fat_reduction'];
