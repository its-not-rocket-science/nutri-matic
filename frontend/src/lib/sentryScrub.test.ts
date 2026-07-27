import { describe, expect, it } from 'vitest';

import { scrubMapping, scrubSentryEvent } from './sentryScrub';

describe('scrubMapping', () => {
	it('redacts sensitive-key values entirely', () => {
		const result = scrubMapping({ password: 'hunter2', access_token: 'real-jwt', accept: 'application/json' });
		expect(result.password).toBe('[Scrubbed]');
		expect(result.access_token).toBe('[Scrubbed]');
		expect(result.accept).toBe('application/json');
	});

	it('redacts emails by pattern regardless of key name', () => {
		const result = scrubMapping({ email: 'a@example.com', message: 'contact b@example.com please' });
		expect(result.email).toBe('[redacted-email]');
		expect(result.message).toBe('contact [redacted-email] please');
	});

	it('recurses into nested objects and arrays', () => {
		const result = scrubMapping({
			user: { email: 'nested@example.com', id: 7 },
			emails: ['a@example.com', 'b@example.com']
		});
		expect((result.user as Record<string, unknown>).email).toBe('[redacted-email]');
		expect((result.user as Record<string, unknown>).id).toBe(7);
		expect(result.emails).toEqual(['[redacted-email]', '[redacted-email]']);
	});
});

describe('scrubSentryEvent', () => {
	it('scrubs request headers, cookies, and data', () => {
		const event = {
			request: {
				headers: { Authorization: 'Bearer real-token', Accept: 'application/json' },
				cookies: { session: 'real-session-id' },
				data: { password: 'hunter2', email: 'a@example.com' }
			}
		};
		const scrubbed = scrubSentryEvent(event);
		expect((scrubbed.request as any).headers.Authorization).toBe('[Scrubbed]');
		expect((scrubbed.request as any).headers.Accept).toBe('application/json');
		expect((scrubbed.request as any).cookies).toEqual({ redacted: '[Scrubbed]' });
		expect((scrubbed.request as any).data.password).toBe('[Scrubbed]');
		expect((scrubbed.request as any).data.email).toBe('[redacted-email]');
	});

	it('scrubs extra context', () => {
		const event = { extra: { note: 'renal diet', profile_id: 7 } };
		const scrubbed = scrubSentryEvent(event);
		expect((scrubbed.extra as any).note).toBe('[Scrubbed]');
		expect((scrubbed.extra as any).profile_id).toBe(7);
	});

	it('does not throw on an event with none of these fields', () => {
		expect(() => scrubSentryEvent({ message: 'plain event' })).not.toThrow();
	});
});
