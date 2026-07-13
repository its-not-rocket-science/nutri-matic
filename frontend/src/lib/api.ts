import { auth } from './auth.svelte';
import type {
	DiaryEntry,
	DiaryEntryCreate,
	DiarySummary,
	FilterKeysResponse,
	FilterScope,
	Food,
	FoodCreate,
	NutrientAmount,
	ProfileUpdate,
	Recipe,
	RecipeCreate,
	SavedFilterPreset,
	SavedFilterPresetCreate,
	Score,
	SearchRequest,
	TokenResponse,
	User
} from './types';

const API_URL = import.meta.env.VITE_API_URL;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`;

	const res = await fetch(`${API_URL}${path}`, {
		headers,
		...options
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(body.detail ?? `Request failed: ${res.status}`);
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

export const api = {
	listFoods: () => request<Food[]>('/api/foods'),
	getFood: (id: number) => request<Food>(`/api/foods/${id}`),
	createFood: (food: FoodCreate) =>
		request<Food>('/api/foods', { method: 'POST', body: JSON.stringify(food) }),
	scoreFood: (id: number, method: 'diaas' | 'pdcaas') =>
		request<Score>(`/api/foods/${id}/score?method=${method}`),
	getNutrients: (id: number) => request<NutrientAmount[]>(`/api/foods/${id}/nutrients`),

	register: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
	login: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
	me: () => request<User>('/api/auth/me'),

	getProfile: () => request<User>('/api/profile'),
	updateProfile: (profile: ProfileUpdate) =>
		request<User>('/api/profile', { method: 'PUT', body: JSON.stringify(profile) }),

	listRecipes: () => request<Recipe[]>('/api/recipes'),
	getRecipe: (id: number) => request<Recipe>(`/api/recipes/${id}`),
	createRecipe: (recipe: RecipeCreate) =>
		request<Recipe>('/api/recipes', { method: 'POST', body: JSON.stringify(recipe) }),
	deleteRecipe: (id: number) => request<void>(`/api/recipes/${id}`, { method: 'DELETE' }),
	scoreRecipe: (id: number, method: 'diaas' | 'pdcaas') =>
		request<Score>(`/api/recipes/${id}/score?method=${method}`),
	getRecipeNutrients: (id: number) => request<NutrientAmount[]>(`/api/recipes/${id}/nutrients`),

	getDiaryDay: (entryDate: string) => request<DiarySummary>(`/api/diary?entry_date=${entryDate}`),
	addDiaryEntry: (entry: DiaryEntryCreate) =>
		request<DiaryEntry>('/api/diary', { method: 'POST', body: JSON.stringify(entry) }),
	deleteDiaryEntry: (id: number) => request<void>(`/api/diary/${id}`, { method: 'DELETE' }),

	getFilterKeys: () => request<FilterKeysResponse>('/api/search/keys'),
	searchFoods: (req: SearchRequest) =>
		request<Food[]>('/api/foods/search', { method: 'POST', body: JSON.stringify(req) }),
	searchRecipes: (req: SearchRequest) =>
		request<Recipe[]>('/api/recipes/search', { method: 'POST', body: JSON.stringify(req) }),

	listPresets: (scope: FilterScope) => request<SavedFilterPreset[]>(`/api/presets?scope=${scope}`),
	createPreset: (preset: SavedFilterPresetCreate) =>
		request<SavedFilterPreset>('/api/presets', { method: 'POST', body: JSON.stringify(preset) }),
	deletePreset: (id: number) => request<void>(`/api/presets/${id}`, { method: 'DELETE' })
};
