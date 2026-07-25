/// <reference types="vitest/config" />
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// Operational-hardening prompt 6: adapter-auto only auto-detects a
			// handful of specific platforms (Vercel/Netlify/Cloudflare) at
			// build time and falls back to a broken build everywhere else —
			// this repo's only actual deployment story is the backend's own
			// Dockerfile (docker-compose.yml), so adapter-node (a plain
			// Node.js server, the standard choice for a Docker/VM deploy) is
			// the adapter that actually matches how this app is deployed,
			// not a guess about a platform nothing else in this repo uses.
			// See docs/frontend-deployment.md for the resulting build/run
			// commands and required environment variables (PORT, ORIGIN).
			adapter: adapter()
		})
	],
	test: {
		environment: 'node'
	}
});
