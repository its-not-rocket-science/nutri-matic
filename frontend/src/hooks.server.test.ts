import { describe, expect, it } from 'vitest';

// Tested in isolation from Sentry's own wrapper (see hooks.server.ts's
// exported `handle`, which composes this with Sentry.sentryHandle()) —
// this file's job is the redirect/security-header logic specifically.
import { canonicalAndSecurityHandle as handle } from './hooks.server';

function makeEvent(url: string) {
	return { url: new URL(url) } as Parameters<typeof handle>[0]['event'];
}

const resolveOk = async () => new Response('ok');

describe('hooks.server handle — alias redirect', () => {
	it('redirects the known Vercel alias to the canonical .uk origin, preserving path and query', async () => {
		const res = await handle({
			event: makeEvent('https://nutri-matic.vercel.app/diary?entry_date=2026-01-01'),
			resolve: resolveOk
		});
		expect(res.status).toBe(308);
		expect(res.headers.get('Location')).toBe('https://nutri-matic.uk/diary?entry_date=2026-01-01');
	});

	it('does not redirect the canonical host itself (no loop)', async () => {
		const res = await handle({ event: makeEvent('https://nutri-matic.uk/diary'), resolve: resolveOk });
		expect(res.status).not.toBe(308);
	});

	it('does not redirect a per-deployment preview hostname', async () => {
		const res = await handle({
			event: makeEvent('https://nutri-matic-abc123-pauls-projects-24d18deb.vercel.app/diary'),
			resolve: resolveOk
		});
		expect(res.status).not.toBe(308);
	});

	it('does not redirect localhost', async () => {
		const res = await handle({ event: makeEvent('http://localhost:5173/diary'), resolve: resolveOk });
		expect(res.status).not.toBe(308);
	});

	it('preserves the path exactly for the root path', async () => {
		const res = await handle({ event: makeEvent('https://nutri-matic.vercel.app/'), resolve: resolveOk });
		expect(res.headers.get('Location')).toBe('https://nutri-matic.uk/');
	});
});

describe('hooks.server handle — security headers', () => {
	it('sets X-Content-Type-Options, Referrer-Policy, Permissions-Policy, and HSTS on a normal response', async () => {
		const res = await handle({ event: makeEvent('https://nutri-matic.uk/'), resolve: resolveOk });
		expect(res.headers.get('X-Content-Type-Options')).toBe('nosniff');
		expect(res.headers.get('Referrer-Policy')).toBe('strict-origin-when-cross-origin');
		expect(res.headers.get('Permissions-Policy')).toContain('geolocation=()');
		expect(res.headers.get('Strict-Transport-Security')).toContain('max-age=63072000');
	});

	it('allows same-origin camera access — BarcodeScanner.svelte genuinely uses it', async () => {
		const res = await handle({ event: makeEvent('https://nutri-matic.uk/'), resolve: resolveOk });
		expect(res.headers.get('Permissions-Policy')).toContain('camera=(self)');
	});
});
