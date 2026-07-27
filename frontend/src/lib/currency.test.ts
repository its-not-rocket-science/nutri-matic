import { describe, expect, it } from 'vitest';

import { formatCurrency } from './currency';

describe('formatCurrency (public-launch hardening prompt 7)', () => {
	// The homepage's static "See it work" proof section (routes/+page.svelte)
	// now renders its illustrative cost-improvement example through this
	// function with an explicit 'GBP' currency, rather than the originally
	// hardcoded "10&cent;"/"+$0.09" — asserting the underlying behaviour it
	// now depends on: an explicit currency code always wins, regardless of
	// locale, and renders as pounds/pence, not dollars/cents.
	it('renders an explicit GBP amount with the pound sign, not dollars', () => {
		const result = formatCurrency(0.09, 'GBP');
		expect(result).toContain('£');
		expect(result).not.toContain('$');
	});

	it('does not fall back to a locale-implied currency when one is explicitly given', () => {
		const result = formatCurrency(0.1, 'GBP');
		expect(result).toContain('£');
	});
});
