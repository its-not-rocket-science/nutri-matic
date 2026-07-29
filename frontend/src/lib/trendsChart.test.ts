import { describe, expect, it } from 'vitest';

import { trendBarCaveat, trendBarValueLabel } from './trendsChart';
import type { TrendNutrient } from './types';

function makeNutrient(overrides: Partial<TrendNutrient> = {}): TrendNutrient {
	return {
		key: 'vitamin_a',
		name: 'Vitamin A',
		unit: 'mcg',
		avg_amount: 8.21,
		adult_drv: 900,
		avg_percent_drv: null,
		drv_source: null,
		drv_confidence: null,
		drv_methodology_version: '1',
		coverage: 0.1,
		insufficient_data_reason: 'Not enough reported data to estimate a percentage.',
		...overrides
	};
}

describe('trendBarValueLabel (prompt 4.1 — always show the raw amount)', () => {
	it('shows a rounded percentage when avg_percent_drv is available', () => {
		const nutrient = makeNutrient({ avg_percent_drv: 42.6 });
		expect(trendBarValueLabel(nutrient)).toBe('43%');
	});

	it('falls back to the raw amount, not a placeholder string, when the percentage is withheld', () => {
		const nutrient = makeNutrient({ avg_percent_drv: null });
		expect(trendBarValueLabel(nutrient)).toBe('8.21mcg');
	});

	it('uses whole numbers for amounts >= 10, matching NutrientBars', () => {
		const nutrient = makeNutrient({ avg_percent_drv: null, avg_amount: 234.7 });
		expect(trendBarValueLabel(nutrient)).toBe('235mcg');
	});

	it('never rounds a small-but-real amount down to an indistinguishable-from-zero "0.0"', () => {
		const nutrient = makeNutrient({ avg_percent_drv: null, avg_amount: 0.04, unit: 'mg' });
		expect(trendBarValueLabel(nutrient)).toBe('0.04mg');
	});
});

describe('trendBarCaveat', () => {
	it('flags insufficient data only when the percentage was actually withheld for that reason', () => {
		const nutrient = makeNutrient({ avg_percent_drv: null, insufficient_data_reason: 'low coverage' });
		expect(trendBarCaveat(nutrient)).toBe('insufficient data for %');
	});

	it('is null when a percentage is available', () => {
		const nutrient = makeNutrient({ avg_percent_drv: 50, insufficient_data_reason: null });
		expect(trendBarCaveat(nutrient)).toBeNull();
	});

	it('is null when the percentage is simply absent for another reason (no insufficient_data_reason)', () => {
		const nutrient = makeNutrient({ avg_percent_drv: null, insufficient_data_reason: null });
		expect(trendBarCaveat(nutrient)).toBeNull();
	});
});
