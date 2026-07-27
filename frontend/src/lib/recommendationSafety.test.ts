import { describe, expect, it } from 'vitest';

import { noSuggestionReasonMessage, safetyWarningMessage } from './recommendationSafety';

describe('safetyWarningMessage', () => {
	it('maps known codes to a human-readable message', () => {
		expect(safetyWarningMessage('data_is_estimate')).toContain('reference food-composition data');
		expect(safetyWarningMessage('medical_constraint_present')).toContain('must not be used to override it');
	});

	it('falls back to the raw code for anything unmapped, rather than showing nothing', () => {
		expect(safetyWarningMessage('some_future_code')).toBe('some_future_code');
	});
});

describe('noSuggestionReasonMessage', () => {
	it('maps every known reason code to a distinct, human-readable message', () => {
		const codes = ['no_shortfall', 'no_eligible_candidates', 'energy_limit', 'no_meaningful_improvement'];
		const messages = codes.map(noSuggestionReasonMessage);
		expect(new Set(messages).size).toBe(codes.length);
		for (const message of messages) {
			expect(message.length).toBeGreaterThan(0);
		}
	});

	it('falls back to the generic message for anything unmapped, rather than showing nothing', () => {
		expect(noSuggestionReasonMessage('some_future_code')).toContain('No safe or useful addition found');
	});
});
