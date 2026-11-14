/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true" />
/// <reference lib="esnext" />
/// <reference lib="webworker" />

// Caches the built app shell (JS/CSS bundle + static assets) so the app
// still opens offline. API responses are deliberately never cached here —
// nutrition/diary/meal-plan data must always be current, and a stale
// cached response would be actively misleading rather than just slow.

import { version } from '$app/env';
import { assets, immutable } from '$app/manifest';

const sw = self as unknown as ServiceWorkerGlobalScope;

const CACHE = `cache-${version}`;
// SvelteKit 3's manifest paths are relative to the base path, which is the
// service worker's scope; resolve them to absolute pathnames so they match
// `url.pathname` in the fetch handler.
const toPathname = (path: string) => new URL(path, sw.registration.scope).pathname;
const ASSETS = new Set([...immutable, ...assets].map(({ path }) => toPathname(path)));

sw.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll([...ASSETS]))
			.then(() => sw.skipWaiting())
	);
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then(async (keys) => {
				for (const key of keys) {
					if (key !== CACHE) await caches.delete(key);
				}
			})
			.then(() => sw.clients.claim())
	);
});

sw.addEventListener('fetch', (event) => {
	if (event.request.method !== 'GET') return;

	const url = new URL(event.request.url);
	if (url.pathname.startsWith('/api/')) return; // always live, never cached

	// Every step that can reject (Cache Storage, network) is caught here so
	// respondWith never receives a rejected promise — that surfaces as
	// "Uncaught (in promise) TypeError: Failed to fetch" in the worker and a
	// network-error response in the page, even while online (an aborted
	// navigation or a transient fetch failure is enough).
	async function respond(): Promise<Response> {
		const cache = await caches.open(CACHE).catch(() => undefined);

		if (cache && ASSETS.has(url.pathname)) {
			const cached = await cache.match(url.pathname).catch(() => undefined);
			if (cached) return cached;
		}

		try {
			const response = await fetch(event.request);
			if (cache && response.status === 200) {
				// Not awaited (don't delay the response), but never left unhandled.
				cache.put(event.request, response.clone()).catch(() => {});
			}
			return response;
		} catch {
			const cached = await cache?.match(event.request).catch(() => undefined);
			if (cached) return cached;
			return offlineResponse(event.request);
		}
	}

	event.respondWith(respond());
});

function offlineResponse(request: Request): Response {
	if (request.mode === 'navigate') {
		return new Response(
			'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
				'<title>Offline — Nutri-Matic</title>' +
				'<h1>You appear to be offline</h1><p>Check your connection and reload the page.</p>',
			{ status: 503, statusText: 'Offline', headers: { 'Content-Type': 'text/html; charset=utf-8' } }
		);
	}
	return new Response(null, { status: 503, statusText: 'Offline' });
}
