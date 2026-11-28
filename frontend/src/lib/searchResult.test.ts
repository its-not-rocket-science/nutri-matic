import { describe, expect, it } from 'vitest';

import { searchResultText } from './searchResult';
import type { Food } from './types';

const base = { id: 1, name: 'Cream, fluid, heavy whipping' } as Food;

describe('searchResultText', () => {
	it('shows a canonical with its source and its approximation note', () => {
		const text = searchResultText({
			...base,
			canonical_key: 'cream_heavy.unspecified',
			canonical_name: 'Cream, heavy (US)',
			canonical_source: 'USDA SR Legacy',
			search_note: 'UK double cream (~48% fat) is richer than US heavy cream (~36%)'
		});
		expect(text).toEqual({
			title: 'Cream, heavy (US)',
			source: 'USDA SR Legacy: Cream, fluid, heavy whipping',
			note: 'UK double cream (~48% fat) is richer than US heavy cream (~36%)'
		});
	});

	it('keeps the note on a plain synonym result', () => {
		const text = searchResultText({ ...base, search_note: 'approx. UK semi-skimmed' });
		expect(text).toEqual({ title: base.name, source: null, note: 'approx. UK semi-skimmed' });
	});

	it('shows the FDC name alone when there is nothing else', () => {
		expect(searchResultText(base)).toEqual({ title: base.name, source: null, note: null });
	});
});
