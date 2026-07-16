export type ThemeChoice = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'nutrimatic_theme';

let choice = $state<ThemeChoice>('system');

function apply(value: ThemeChoice) {
	if (typeof document === 'undefined') return;
	if (value === 'system') {
		document.documentElement.removeAttribute('data-theme');
	} else {
		document.documentElement.setAttribute('data-theme', value);
	}
}

export const theme = {
	get choice() {
		return choice;
	},
	set(value: ThemeChoice) {
		choice = value;
		apply(value);
		if (typeof window !== 'undefined') {
			localStorage.setItem(STORAGE_KEY, value);
		}
	},
	cycle() {
		const order: ThemeChoice[] = ['system', 'light', 'dark'];
		const next = order[(order.indexOf(choice) + 1) % order.length];
		theme.set(next);
	},
	/** Call once on app mount to restore the persisted choice. */
	init() {
		if (typeof window === 'undefined') return;
		const stored = localStorage.getItem(STORAGE_KEY) as ThemeChoice | null;
		if (stored === 'light' || stored === 'dark' || stored === 'system') {
			choice = stored;
			apply(stored);
		}
	}
};
