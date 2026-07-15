import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { api } from './api';

describe('api.listFoods', () => {
	beforeEach(() => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => ({
				ok: true,
				status: 200,
				json: async () => ({ items: [], total: 0, limit: 10, offset: 0, has_more: false })
			}))
		);
	});

	it('defaults to a small bounded page instead of the full catalog', async () => {
		await api.listFoods();
		const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
		expect(url).toContain('limit=10');
		expect(url).toContain('offset=0');
	});

	it('passes through explicit limit/offset', async () => {
		await api.listFoods(50, 100);
		const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
		expect(url).toContain('limit=50');
		expect(url).toContain('offset=100');
	});
});
