// Onboarding's step-1 pick — shared here (rather than duplicated per-page)
// so onboarding, the profile page, and the dashboard can never drift out of
// sync with each other or with the backend's VALID_GOALS (routers/profile.py).
export type Goal = 'protein_quality' | 'nutrient_gaps' | 'budget' | 'exploring';

export const GOAL_OPTIONS: { value: Goal; label: string }[] = [
	{ value: 'protein_quality', label: 'Track protein quality' },
	{ value: 'nutrient_gaps', label: 'Close nutrient gaps' },
	{ value: 'budget', label: 'Plan meals on a budget' },
	{ value: 'exploring', label: 'Just exploring' }
];

export const GOAL_MESSAGES: Record<Goal, string> = {
	protein_quality:
		"You're set up to track DIAAS/PDCAAS on everything you log — check the score on your first meal below.",
	nutrient_gaps: "Your dashboard will always lead with today's biggest nutrient gap and a real food to close it.",
	budget: 'Add prices under Food Prices any time — the meal-plan optimiser will factor real cost into every suggestion.',
	exploring: 'Have a look around — nothing here is locked behind a purchase, and every number traces back to its source.'
};
