import { defineEnvVars } from '@sveltejs/kit/env';

// SvelteKit 3 replaces `$env/dynamic/public` with explicitly declared
// variables, imported from `$app/env/public`. All four are optional and read
// when the app starts (not inlined at build time), as before: an unset value
// must never fail the build, so every local/dev/CI/preview build without a
// Sentry DSN keeps working (see hooks.client.ts).
const optional = (value: string | undefined) => value || undefined;

export const variables = defineEnvVars({
	PUBLIC_SENTRY_DSN: {
		public: true,
		schema: optional,
		description: 'Sentry DSN for frontend error reporting; Sentry is off when unset.'
	},
	PUBLIC_SENTRY_ENVIRONMENT: {
		public: true,
		schema: optional,
		description: 'Sentry environment name (defaults to "development").'
	},
	PUBLIC_RELEASE_VERSION: {
		public: true,
		schema: optional,
		description: 'Release identifier sent to Sentry (the Vercel commit SHA).'
	},
	PUBLIC_SENTRY_TRACES_SAMPLE_RATE: {
		public: true,
		schema: optional,
		description: 'Sentry traces sample rate, a number between 0 and 1.'
	}
});
