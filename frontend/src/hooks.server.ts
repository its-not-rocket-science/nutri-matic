import type { Handle } from '@sveltejs/kit';
import { CANONICAL_ORIGIN, REDIRECT_FROM_HOSTS } from '$lib/site';

// Public-launch hardening prompt 5.
//
// 1. Redirects a known public alias (see site.ts's REDIRECT_FROM_HOSTS
//    — currently just the stable nutri-matic.vercel.app alias) to the
//    canonical https://nutri-matic.uk origin, preserving path and query
//    string exactly (a plain hostname/protocol swap on the same URL
//    object, never a manual string rebuild that could drop something).
//    A 308 (permanent, method-preserving) redirect — matches the
//    prompt's "appropriate permanent redirect" and doesn't silently
//    turn a POST into a GET the way a 301/302 can in some clients.
//
//    Deliberately an explicit, exact hostname allowlist rather than a
//    pattern — a per-deployment preview hostname
//    (nutri-matic-<hash>-pauls-projects-24d18deb.vercel.app) never
//    matches it, so preview deployments are never redirected, and
//    neither is localhost/CI. No loop risk: CANONICAL_ORIGIN's own
//    hostname is never in REDIRECT_FROM_HOSTS.
//
// 2. Sets response headers this app doesn't get for free from
//    SvelteKit's own config: X-Content-Type-Options, Referrer-Policy,
//    Permissions-Policy, and HSTS (Vercel's platform already adds a
//    baseline HSTS header for custom domains with valid TLS — verified
//    directly, not assumed — but this sets an explicit, equally strong
//    value too, so the guarantee doesn't depend on that alone). CSP is
//    handled separately, by SvelteKit's own kit.csp config (see
//    vite.config.ts) — not duplicated here.
export const handle: Handle = async ({ event, resolve }) => {
	if (REDIRECT_FROM_HOSTS.includes(event.url.hostname)) {
		const target = new URL(event.url);
		target.protocol = 'https:';
		target.hostname = new URL(CANONICAL_ORIGIN).hostname;
		target.port = '';
		return new Response(null, { status: 308, headers: { Location: target.toString() } });
	}

	const response = await resolve(event);
	response.headers.set('X-Content-Type-Options', 'nosniff');
	response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
	// camera=(self): BarcodeScanner.svelte (diary/meal-plan "Scan barcode")
	// genuinely uses the camera via @zxing/browser's decodeFromVideoDevice
	// — camera=() (deny everywhere, including same-origin) would silently
	// break that real feature, caught by PR review rather than checked
	// up front. Every other capability here has no real usage anywhere in
	// this app (checked directly) — denied by default rather than left at
	// the browser's own permissive default.
	response.headers.set(
		'Permissions-Policy',
		'camera=(self), microphone=(), geolocation=(), payment=(), usb=()'
	);
	response.headers.set('Strict-Transport-Security', 'max-age=63072000; includeSubDomains; preload');
	return response;
};
