import { describe, expect, it } from 'vitest';

import { PUBLIC_ROUTES } from '$lib/site';
import { GET } from './+server';

describe('GET /sitemap.xml', () => {
	it('lists every public route as an absolute canonical-origin URL', async () => {
		const res = GET();
		expect(res.headers.get('Content-Type')).toBe('application/xml');
		const body = await res.text();
		for (const route of PUBLIC_ROUTES) {
			expect(body).toContain(`<loc>https://nutri-matic.uk${route}</loc>`);
		}
	});

	it('never lists a private/authenticated or demo-specific route', async () => {
		const res = GET();
		const body = await res.text();
		for (const privatePath of ['/diary', '/profile', '/meal-plan', '/search', '/recipes']) {
			expect(body).not.toContain(`<loc>https://nutri-matic.uk${privatePath}</loc>`);
		}
	});
});
