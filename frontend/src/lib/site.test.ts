import { describe, expect, it } from 'vitest';

import { CANONICAL_ORIGIN, canonicalUrl, PUBLIC_ROUTES, REDIRECT_FROM_HOSTS } from './site';

describe('site config', () => {
	it('canonicalUrl builds an absolute URL under the canonical origin', () => {
		expect(canonicalUrl('/diary')).toBe('https://nutri-matic.uk/diary');
		expect(canonicalUrl('/')).toBe('https://nutri-matic.uk/');
	});

	it('never lists the canonical host itself as something to redirect from', () => {
		expect(REDIRECT_FROM_HOSTS).not.toContain(new URL(CANONICAL_ORIGIN).hostname);
	});

	it('public routes are a small, explicit allowlist, not every route in the app', () => {
		expect(PUBLIC_ROUTES).not.toContain('/diary');
		expect(PUBLIC_ROUTES).not.toContain('/profile');
		expect(PUBLIC_ROUTES).toContain('/');
	});
});
