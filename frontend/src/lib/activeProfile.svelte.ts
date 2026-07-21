import type { Profile } from './types';

const STORAGE_KEY = 'nutrimatic_active_profile_id';

function loadStoredId(): number | null {
	if (typeof localStorage === 'undefined') return null;
	const raw = localStorage.getItem(STORAGE_KEY);
	return raw ? Number(raw) : null;
}

let profiles = $state<Profile[]>([]);
let activeId = $state<number | null>(loadStoredId());

function persist(id: number | null) {
	if (typeof localStorage === 'undefined') return;
	if (id === null) localStorage.removeItem(STORAGE_KEY);
	else localStorage.setItem(STORAGE_KEY, String(id));
}

/** Which household profile every profile-scoped API call (diary, weight
 * log, meal plan, dietary constraints) applies to — a simple global
 * switcher rather than a per-page selector, so changing it once (in the
 * nav) redirects every page consistently. Falls back to the account's
 * owner profile whenever the stored id is missing or no longer valid
 * (e.g. a dependent profile got deleted from another tab). */
export const activeProfile = {
	get list(): Profile[] {
		return profiles;
	},
	get active(): Profile | null {
		return profiles.find((p) => p.id === activeId) ?? null;
	},
	get id(): number | null {
		return activeId;
	},
	/** Called once after login/app-mount with the account's full profile
	 * list — resets the active selection to the owner profile if the
	 * previously-active one (from localStorage) no longer exists. */
	setProfiles(list: Profile[]) {
		profiles = list;
		if (activeId === null || !list.some((p) => p.id === activeId)) {
			const owner = list.find((p) => p.is_account_owner);
			activeId = owner ? owner.id : (list[0]?.id ?? null);
			persist(activeId);
		}
	},
	setActive(id: number) {
		activeId = id;
		persist(id);
	},
	clear() {
		profiles = [];
		activeId = null;
		persist(null);
	}
};
