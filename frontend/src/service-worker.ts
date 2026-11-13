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

	async function respond(): Promise<Response> {
		const cache = await caches.open(CACHE);

		if (ASSETS.has(url.pathname)) {
			const cached = await cache.match(url.pathname);
			if (cached) return cached;
		}

		try {
			const response = await fetch(event.request);
			if (response.status === 200) {
				cache.put(event.request, response.clone());
			}
			return response;
		} catch (err) {
			const cached = await cache.match(event.request);
			if (cached) return cached;
			throw err;
		}
	}

	event.respondWith(respond());
});
