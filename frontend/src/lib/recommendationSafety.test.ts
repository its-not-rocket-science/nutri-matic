import { describe, expect, it } from 'vitest';

import { safetyWarningMessage } from './recommendationSafety';

describe('safetyWarningMessage', () => {
	it('maps known codes to a human-readable message', () => {
		expect(safetyWarningMessage('data_is_estimate')).toContain('reference food-composition data');
		expect(safetyWarningMessage('medical_constraint_present')).toContain('must not be used to override it');
	});

	it('falls back to the raw code for anything unmapped, rather than showing nothing', () => {
		expect(safetyWarningMessage('some_future_code')).toBe('some_future_code');
	});
});
