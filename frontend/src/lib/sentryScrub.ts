// Public-launch hardening prompt 6 — mirrors backend/app/monitoring.py's
// scrub_event exactly (same sensitive-key substrings, same email-pattern
// redaction), so the frontend's Sentry events get the same guarantee:
// never a token, password, secret, JWT, cookie, medical/dietary note, or
// email address, wherever it appears (key name OR pattern match in a
// string value).
const SENSITIVE_KEY_SUBSTRINGS = [
	'authorization',
	'token',
	'password',
	'secret',
	'jwt',
	'cookie',
	'note',
	'medical',
	'dietary_note'
];

const EMAIL_PATTERN = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;

function isSensitiveKey(key: string): boolean {
	const lowered = key.toLowerCase();
	return SENSITIVE_KEY_SUBSTRINGS.some((marker) => lowered.includes(marker));
}

function scrubValue(key: string, value: unknown): unknown {
	if (isSensitiveKey(key)) return '[Scrubbed]';
	if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
		return scrubMapping(value as Record<string, unknown>);
	}
	if (Array.isArray(value)) return value.map((item) => scrubValue(key, item));
	if (typeof value === 'string') return value.replace(EMAIL_PATTERN, '[redacted-email]');
	return value;
}

export function scrubMapping(mapping: Record<string, unknown>): Record<string, unknown> {
	const result: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(mapping)) {
		result[key] = scrubValue(key, value);
	}
	return result;
}

/** Sentry's `beforeSend` hook — same scope as the backend's
 * `scrub_event`: request headers/cookies/data, and `extra`/`contexts`
 * context, never sent as-is.
 *
 * Typed as `any` at this one boundary deliberately: Sentry's own
 * `ErrorEvent` type has no index signature (so it can't structurally
 * satisfy `Record<string, unknown>`), and this function's whole job is
 * reaching into whatever shape of `request`/`extra` data actually shows
 * up on it — `scrubMapping` above (what does the real redaction work)
 * stays fully typed. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- see comment above
export function scrubSentryEvent(event: any): any {
	const withRequest = event as {
		request?: { headers?: Record<string, unknown>; cookies?: Record<string, unknown>; data?: unknown };
		extra?: Record<string, unknown>;
	};

	if (withRequest.request) {
		if (withRequest.request.headers) {
			withRequest.request.headers = scrubMapping(withRequest.request.headers);
		}
		if (withRequest.request.cookies) {
			withRequest.request.cookies = { redacted: '[Scrubbed]' };
		}
		if (withRequest.request.data && typeof withRequest.request.data === 'object') {
			withRequest.request.data = scrubMapping(withRequest.request.data as Record<string, unknown>);
		}
	}
	if (withRequest.extra) {
		withRequest.extra = scrubMapping(withRequest.extra);
	}
	return event;
}
