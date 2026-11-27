import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { HttpError, NetworkError } from './api';
import { BARCODE_MISS_HINT, isBarcodeMiss } from './barcodeMiss';

describe('isBarcodeMiss', () => {
	it('treats a 404 as a miss', () => {
		expect(isBarcodeMiss(new HttpError('No food found for that barcode', 404))).toBe(true);
	});

	it('keeps other failures as errors', () => {
		expect(isBarcodeMiss(new HttpError('Server error', 500))).toBe(false);
		expect(isBarcodeMiss(new HttpError('Unauthorized', 401))).toBe(false);
		expect(isBarcodeMiss(new NetworkError('offline'))).toBe(false);
		expect(isBarcodeMiss(new Error('x'))).toBe(false);
	});

	it('uses the plan wording', () => {
		expect(BARCODE_MISS_HINT).toBe('Not in our database. Most products are US-listed. Search by name instead.');
	});
});
