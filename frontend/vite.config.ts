/// <reference types="vitest/config" />
import adapter from '@sveltejs/adapter-vercel';
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
			adapter: adapter()
		})
	],
	test: {
		environment: 'node'
	}
});
