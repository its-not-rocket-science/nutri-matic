import { describe, expect, it } from 'vitest';

import {
	CARBON_METHODOLOGY_NOTE,
	GLYCAEMIC_METHODOLOGY_NOTE,
	carbonTierLabel,
	classificationProvenanceNote,
	glycaemicBasisNote,
	glycaemicTierLabel,
	noSuggestionReasonMessage,
	safetyWarningMessage
} from './recommendationSafety';

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

describe('carbonTierLabel / glycaemicTierLabel', () => {
	it('labels every real tier', () => {
		expect(carbonTierLabel('very_high')).toBe('very high');
		expect(carbonTierLabel('low')).toBe('low');
		expect(glycaemicTierLabel('high')).toBe('high');
		expect(glycaemicTierLabel('low')).toBe('low');
	});
});

describe('classificationProvenanceNote', () => {
	it('distinguishes a direct name match from a recipe proxy', () => {
		const nameMatch = classificationProvenanceNote('name_match');
		const proxy = classificationProvenanceNote('dominant_ingredient_proxy');
		expect(nameMatch).not.toBe(proxy);
		expect(proxy).toContain('largest-by-weight ingredient');
	});

	it('returns an empty string, not a guess, when there is no provenance', () => {
		expect(classificationProvenanceNote(null)).toBe('');
	});
});

describe('glycaemicBasisNote', () => {
	it('never describes a negligible-carbohydrate food as a measured low GI', () => {
		const note = glycaemicBasisNote('negligible_carbohydrate').toLowerCase();
		expect(note).not.toContain('measured low');
		expect(note).not.toContain('tested low');
		expect(note).toContain('negligible carbohydrate');
	});

	it('distinguishes category_match from negligible_carbohydrate', () => {
		expect(glycaemicBasisNote('category_match')).not.toBe(glycaemicBasisNote('negligible_carbohydrate'));
	});

	it('returns an empty string, not a guess, when there is no basis', () => {
		expect(glycaemicBasisNote(null)).toBe('');
	});
});

describe('CARBON_METHODOLOGY_NOTE / GLYCAEMIC_METHODOLOGY_NOTE', () => {
	it('states this is an estimate, explicitly not a per-product lifecycle assessment', () => {
		const note = CARBON_METHODOLOGY_NOTE.toLowerCase();
		expect(note).toContain('estimate');
		expect(note).toContain('not a per-product lifecycle assessment');
	});

	it('states GI is not glycaemic load, and that this is not medical advice or a personal prediction', () => {
		const note = GLYCAEMIC_METHODOLOGY_NOTE.toLowerCase();
		expect(note).toContain('glycaemic load');
		expect(note).toContain('medical advice');
		expect(note).toContain('your own blood-sugar response');
	});
});
