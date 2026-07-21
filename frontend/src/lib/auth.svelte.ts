import { activeProfile } from './activeProfile.svelte';
import type { User } from './types';

const TOKEN_KEY = 'nutrimatic_token';

let token = $state<string | null>(null);
let user = $state<User | null>(null);
let initialized = false;

function setToken(value: string | null) {
	token = value;
	if (typeof window !== 'undefined') {
		if (value) localStorage.setItem(TOKEN_KEY, value);
		else localStorage.removeItem(TOKEN_KEY);
	}
}

export const auth = {
	get token() {
		return token;
	},
	get user() {
		return user;
	},
	get isLoggedIn() {
		return token !== null;
	},
	setToken,
	setUser(value: User | null) {
		user = value;
	},
	logout() {
		setToken(null);
		user = null;
		activeProfile.clear();
	},
	/** Call once on app mount to pick up a token persisted from a previous session. */
	init(): string | null {
		if (initialized) return token;
		initialized = true;
		if (typeof window !== 'undefined') {
			token = localStorage.getItem(TOKEN_KEY);
		}
		return token;
	}
};
