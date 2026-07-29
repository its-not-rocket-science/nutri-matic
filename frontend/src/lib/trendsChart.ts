import type { TrendNutrient } from './types';

// Prompt 4.1: the diet-trends chart bar previously replaced its label with
// a bare "insufficient data" string whenever avg_percent_drv was withheld,
// hiding the raw measured amount that was still available. Mirrors the
// same "always show the raw amount, only the %DRV is ever withheld"
// pattern NutrientBars.svelte already establishes for the vitamin/mineral
// list.
export function trendBarValueLabel(nutrient: TrendNutrient): string {
	if (nutrient.avg_percent_drv !== null) return `${Math.round(nutrient.avg_percent_drv)}%`;
	return `${nutrient.avg_amount.toFixed(1)}${nutrient.unit}`;
}

export function trendBarCaveat(nutrient: TrendNutrient): string | null {
	if (nutrient.avg_percent_drv === null && nutrient.insufficient_data_reason) {
		return 'insufficient data for %';
	}
	return null;
}
