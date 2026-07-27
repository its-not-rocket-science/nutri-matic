import * as Sentry from '@sentry/sveltekit';
import { env } from '$env/dynamic/public';
import { scrubSentryEvent } from '$lib/sentryScrub';

// Public-launch hardening prompt 6 — the frontend half of "integrate
// Sentry... backend and frontend errors". No-op unless PUBLIC_SENTRY_DSN
// is set (`$env/dynamic/public`, not `$env/static/public`, specifically
// so an unset value doesn't fail the build — mirrors app/monitoring.py's
// "missing monitoring credentials must never break local development"
// on the backend). Every local/dev/CI/preview build with no DSN
// configured behaves exactly as it did before this prompt.
if (env.PUBLIC_SENTRY_DSN) {
	Sentry.init({
		dsn: env.PUBLIC_SENTRY_DSN,
		environment: env.PUBLIC_SENTRY_ENVIRONMENT || 'development',
		release: env.PUBLIC_RELEASE_VERSION || undefined,
		tracesSampleRate: env.PUBLIC_SENTRY_TRACES_SAMPLE_RATE
			? Number(env.PUBLIC_SENTRY_TRACES_SAMPLE_RATE)
			: 0.1,
		beforeSend: scrubSentryEvent
	});
}

export const handleError = Sentry.handleErrorWithSentry();
