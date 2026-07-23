import { describe, expect, it } from 'vitest';

import { nutrientLabel } from './nutrientLabels';

describe('nutrientLabel', () => {
	it('uses UK spelling for fibre rather than the internal "fiber" key', () => {
		expect(nutrientLabel('fiber_total')).toBe('Fibre');
	});

	it('returns known overrides verbatim', () => {
		expect(nutrientLabel('vitamin_b12')).toBe('Vitamin B12');
		expect(nutrientLabel('iron_heme')).toBe('Haem iron');
	});

	it('humanises an unmapped key by capitalising the first word only', () => {
		expect(nutrientLabel('folate')).toBe('Folate');
		expect(nutrientLabel('some_new_nutrient')).toBe('Some new nutrient');
	});
});
