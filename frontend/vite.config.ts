/// <reference types="vitest/config" />
import adapter from '@sveltejs/adapter-vercel';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

// Public-launch hardening prompt 5: the backend origin varies per
// environment (VITE_API_URL, baked in at build time — see docs/
// frontend-deployment.md) and the CSP's connect-src must explicitly
// allow it, or every API call the app makes would be silently blocked
// in production. loadEnv reads the same .env files/environment Vite
// itself would use for the actual build, so this always matches
// VITE_API_URL's real baked-in value rather than guessing at it
// separately.
function backendOrigin(viteApiUrl: string | undefined): string {
	if (!viteApiUrl) return 'http://localhost:8000';
	try {
		return new URL(viteApiUrl).origin;
	} catch {
		return 'http://localhost:8000';
	}
}

// Public-launch hardening prompt 6, caught by review: the Sentry
// browser SDK POSTs error/trace envelopes directly to the DSN's own
// ingest origin (not the backend origin above) — connect-src not
// allowing it means the browser silently blocks every envelope, so
// client-side Sentry would be wired up but never actually deliver
// anything in production. Derived from the same PUBLIC_SENTRY_DSN
// hooks.client.ts/hooks.server.ts read, so it can never drift from the
// DSN actually in use. Returns null (added to connect-src only when
// present) rather than a placeholder — no DSN means nothing to allow.
function sentryIngestOrigin(publicSentryDsn: string | undefined): string | null {
	if (!publicSentryDsn) return null;
	try {
		return new URL(publicSentryDsn).origin;
	} catch {
		return null;
	}
}

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), '');

	return {
		plugins: [
			sveltekit({
				compilerOptions: {
					// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
					runes: ({ filename }) =>
						filename.split(/[/\\]/).includes('node_modules') ? undefined : true
				},

				// Operational-hardening prompt 6, corrected: this repo already has
				// a live Vercel project (visible as a status check on every PR/
				// push — see docs/frontend-deployment.md) auto-deploying this
				// frontend. adapter-node (the first choice here) was wrong —
				// picked from repo-local config alone (Dockerfile/docker-
				// compose.yml, the backend's deployment story) without checking
				// actual current hosting, which the prompt explicitly asked for
				// and this missed the first time. adapter-vercel is the correct,
				// supported adapter for the platform this app is actually
				// running on.
				adapter: adapter(),

				// Public-launch hardening prompt 5 — see docs/security-headers.md
				// for the full inventory this was derived from (every script/
				// style/image/font/connect source the app actually uses, not a
				// copy-pasted template). mode: 'auto' lets SvelteKit use nonces
				// for the dynamically-rendered pages this app actually has (no
				// route currently prerenders) and hashes for any that later do —
				// both handled automatically for SvelteKit's own generated
				// inline scripts/styles; app.html's one hand-written inline
				// script uses the %sveltekit.nonce% placeholder for the same
				// reason.
				csp: {
					mode: 'auto',
					directives: {
						'default-src': ['self'],
						'script-src': ['self'],
						// style-src stays strict (no unsafe-inline) — this app uses
						// no Svelte transitions (which compile to inline <style>
						// elements) anywhere, checked directly rather than assumed.
						'style-src': ['self'],
						// Several components set a dynamically-computed inline
						// style="width: N%" for progress/score bar fills (real
						// per-render values, not hashable ahead of time) — scoped
						// to attribute-level only (style-src-elem/style-src above
						// stay strict), and the app renders no user-controlled
						// HTML anywhere (`{@html}` is never used), so this can't be
						// leveraged to inject an arbitrary <style> block.
						'style-src-attr': ['unsafe-inline'],
						'img-src': ['self'],
						'font-src': ['self'],
						// eslint-disable-next-line @typescript-eslint/no-explicit-any -- SvelteKit's CspDirectives
						// types each source as a template-literal pattern (Csp.HostSource) that a dynamically
						// computed origin string can't be statically narrowed to, even though any real
						// http(s)://host[:port] value satisfies it at runtime.
						'connect-src': [
							'self',
							backendOrigin(env.VITE_API_URL) as any,
							...(sentryIngestOrigin(env.PUBLIC_SENTRY_DSN)
								? [sentryIngestOrigin(env.PUBLIC_SENTRY_DSN) as any]
								: [])
						],
						'manifest-src': ['self'],
						'worker-src': ['self'],
						'object-src': ['none'],
						'base-uri': ['self'],
						'form-action': ['self'],
						// Clickjacking protection — this app is never meant to be
						// framed by another site. Also set as X-Frame-Options isn't
						// needed once this is present (modern browsers prefer CSP).
						'frame-ancestors': ['none']
					}
				}
			})
		],
		test: {
			environment: 'node'
		}
	};
});
