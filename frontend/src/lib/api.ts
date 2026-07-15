import { goto } from '$app/navigation';
import { auth } from './auth.svelte';
import type {
	ClinicianClientSummary,
	ClinicianLink,
	ClinicianNote,
	Collection,
	CollectionDetail,
	Complement,
	DiaryEntry,
	DiaryEntryCreate,
	DiaryMealTemplate,
	DiaryMealTemplateDetail,
	DiarySnapshot,
	DiarySummary,
	DiaryTrends,
	FilterKeysResponse,
	FilterScope,
	Food,
	FoodCreate,
	FoodList,
	FoodPrice,
	FoodPriceCreate,
	FoodProvenance,
	GapSuggestion,
	Meal,
	MealOptimization,
	MealPlanEntry,
	MealPlanEntryCreate,
	MealPlanTemplate,
	MealPlanTemplateDetail,
	NutrientAmount,
	PlanOptimization,
	ProfileUpdate,
	QuickAdd,
	Recipe,
	RecipeComment,
	RecipeCreate,
	RecipeRatingSummary,
	RecipeShare,
	SavedFilterPreset,
	SavedFilterPresetCreate,
	Score,
	SearchRequest,
	ShoppingList,
	TokenResponse,
	TrendGroupBy,
	User,
	WeightLog,
	WeightLogCreate
} from './types';

const API_URL = import.meta.env.VITE_API_URL;

// Without this, a request that never gets a response (dead backend, stalled
// proxy, huge unpaginated payload) leaves every "Loading…" screen spinning
// forever instead of surfacing an error — see the pagination fix on
// GET /api/foods for the case that originally exposed this.
const REQUEST_TIMEOUT_MS = 20_000;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`;

	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

	let res: Response;
	try {
		res = await fetch(`${API_URL}${path}`, {
			headers,
			signal: controller.signal,
			...options
		});
	} catch (e) {
		if (e instanceof DOMException && e.name === 'AbortError') {
			throw new Error('Request timed out. Please check your connection and try again.');
		}
		throw new Error('Network error. Please check your connection and try again.');
	} finally {
		clearTimeout(timeout);
	}

	if (res.status === 401 && auth.token) {
		// Token expired or invalid (tokens are now 24h-lived, not 7 days — see
		// docs/auth-model-review.md) — clear it and send the user back to log
		// in rather than surfacing a raw "Invalid or expired token" error.
		auth.logout();
		await goto('/login');
		throw new Error('Session expired — please log in again.');
	}
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(body.detail ?? `Request failed: ${res.status}`);
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

export const api = {
	listFoods: (limit = 10, offset = 0) =>
		request<FoodList>(`/api/foods?limit=${limit}&offset=${offset}`),
	getFood: (id: number) => request<Food>(`/api/foods/${id}`),
	createFood: (food: FoodCreate) =>
		request<Food>('/api/foods', { method: 'POST', body: JSON.stringify(food) }),
	scoreFood: (id: number, method: 'diaas' | 'pdcaas') =>
		request<Score>(`/api/foods/${id}/score?method=${method}`),
	complementFood: (id: number, method: 'diaas' | 'pdcaas') =>
		request<Complement>(`/api/foods/${id}/complement?method=${method}`),
	getFoodByBarcode: (gtinUpc: string) => request<Food>(`/api/foods/barcode/${encodeURIComponent(gtinUpc)}`),
	searchFoodsByName: (q: string, limit = 15) =>
		request<Food[]>(`/api/foods/search-by-name?q=${encodeURIComponent(q)}&limit=${limit}`),
	getNutrients: (id: number) => request<NutrientAmount[]>(`/api/foods/${id}/nutrients`),
	getFoodProvenance: (id: number) => request<FoodProvenance>(`/api/foods/${id}/provenance`),

	register: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
	login: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
	me: () => request<User>('/api/auth/me'),

	getProfile: () => request<User>('/api/profile'),
	updateProfile: (profile: ProfileUpdate) =>
		request<User>('/api/profile', { method: 'PUT', body: JSON.stringify(profile) }),

	logWeight: (entry: WeightLogCreate) =>
		request<WeightLog>('/api/weight-logs', { method: 'POST', body: JSON.stringify(entry) }),
	listWeightLogs: (startDate: string, endDate: string) =>
		request<WeightLog[]>(`/api/weight-logs?start_date=${startDate}&end_date=${endDate}`),
	deleteWeightLog: (id: number) => request<void>(`/api/weight-logs/${id}`, { method: 'DELETE' }),

	listRecipes: (tag?: string) => request<Recipe[]>(`/api/recipes${tag ? `?tag=${encodeURIComponent(tag)}` : ''}`),
	listSharedWithMe: () => request<Recipe[]>('/api/recipes/shared-with-me'),
	listMyTags: () => request<string[]>('/api/recipes/tags'),
	addTag: (recipeId: number, tag: string) =>
		request<Recipe>(`/api/recipes/${recipeId}/tags`, { method: 'POST', body: JSON.stringify({ tag }) }),
	removeTag: (recipeId: number, tag: string) =>
		request<Recipe>(`/api/recipes/${recipeId}/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' }),
	getRecipe: (id: number) => request<Recipe>(`/api/recipes/${id}`),
	createRecipe: (recipe: RecipeCreate) =>
		request<Recipe>('/api/recipes', { method: 'POST', body: JSON.stringify(recipe) }),
	deleteRecipe: (id: number) => request<void>(`/api/recipes/${id}`, { method: 'DELETE' }),
	copyRecipe: (id: number) => request<Recipe>(`/api/recipes/${id}/copy`, { method: 'POST' }),
	scoreRecipe: (id: number, method: 'diaas' | 'pdcaas') =>
		request<Score>(`/api/recipes/${id}/score?method=${method}`),
	getRecipeNutrients: (id: number) => request<NutrientAmount[]>(`/api/recipes/${id}/nutrients`),

	listShares: (recipeId: number) => request<RecipeShare[]>(`/api/recipes/${recipeId}/shares`),
	createShare: (recipeId: number, email: string) =>
		request<RecipeShare>(`/api/recipes/${recipeId}/shares`, { method: 'POST', body: JSON.stringify({ email }) }),
	deleteShare: (recipeId: number, shareId: number) =>
		request<void>(`/api/recipes/${recipeId}/shares/${shareId}`, { method: 'DELETE' }),

	getRatings: (recipeId: number) => request<RecipeRatingSummary>(`/api/recipes/${recipeId}/ratings`),
	rateRecipe: (recipeId: number, rating: number) =>
		request<RecipeRatingSummary>(`/api/recipes/${recipeId}/ratings`, {
			method: 'POST',
			body: JSON.stringify({ rating })
		}),
	deleteRating: (recipeId: number) =>
		request<RecipeRatingSummary>(`/api/recipes/${recipeId}/ratings`, { method: 'DELETE' }),

	listComments: (recipeId: number) => request<RecipeComment[]>(`/api/recipes/${recipeId}/comments`),
	createComment: (recipeId: number, body: string) =>
		request<RecipeComment>(`/api/recipes/${recipeId}/comments`, { method: 'POST', body: JSON.stringify({ body }) }),
	deleteComment: (recipeId: number, commentId: number) =>
		request<void>(`/api/recipes/${recipeId}/comments/${commentId}`, { method: 'DELETE' }),

	getDiaryDay: (entryDate: string) => request<DiarySummary>(`/api/diary?entry_date=${entryDate}`),
	addDiaryEntry: (entry: DiaryEntryCreate) =>
		request<DiaryEntry>('/api/diary', { method: 'POST', body: JSON.stringify(entry) }),
	deleteDiaryEntry: (id: number) => request<void>(`/api/diary/${id}`, { method: 'DELETE' }),
	copyDiaryDay: (sourceDate: string, targetDate: string) =>
		request<DiaryEntry[]>(`/api/diary/copy-day?source_date=${sourceDate}&target_date=${targetDate}`, {
			method: 'POST'
		}),
	getDiaryTrends: (startDate: string, endDate: string, groupBy: TrendGroupBy) =>
		request<DiaryTrends>(`/api/diary/trends?start_date=${startDate}&end_date=${endDate}&group_by=${groupBy}`),
	getQuickAdd: () => request<QuickAdd>('/api/diary/quick-add'),
	getGapSuggestions: (entryDate: string) =>
		request<GapSuggestion | null>(`/api/diary/gap-suggestions?entry_date=${entryDate}`),
	getDiarySnapshot: (entryDate: string) =>
		request<DiarySnapshot | null>(`/api/diary/snapshot?entry_date=${entryDate}`),
	createDiarySnapshot: (entryDate: string) =>
		request<DiarySnapshot>(`/api/diary/snapshot?entry_date=${entryDate}`, { method: 'POST' }),
	getMealOptimization: (entryDate: string, meal: Meal, maxAdditionalCost?: number | null) =>
		request<MealOptimization | null>(
			`/api/diary/meal-optimize?entry_date=${entryDate}&meal=${meal}` +
				(maxAdditionalCost != null ? `&max_additional_cost=${maxAdditionalCost}` : '')
		),

	listDiaryMealTemplates: () => request<DiaryMealTemplate[]>('/api/diary-meal-templates'),
	createDiaryMealTemplate: (name: string, entryDate: string, meal: Meal) =>
		request<DiaryMealTemplate>('/api/diary-meal-templates', {
			method: 'POST',
			body: JSON.stringify({ name, entry_date: entryDate, meal })
		}),
	getDiaryMealTemplate: (id: number) => request<DiaryMealTemplateDetail>(`/api/diary-meal-templates/${id}`),
	deleteDiaryMealTemplate: (id: number) => request<void>(`/api/diary-meal-templates/${id}`, { method: 'DELETE' }),
	applyDiaryMealTemplate: (id: number, entryDate: string, meal: Meal) =>
		request<DiaryEntry[]>(`/api/diary-meal-templates/${id}/apply?entry_date=${entryDate}&meal=${meal}`, {
			method: 'POST'
		}),

	listMealPlanEntries: (startDate: string, endDate: string) =>
		request<MealPlanEntry[]>(`/api/meal-plan?start_date=${startDate}&end_date=${endDate}`),
	addMealPlanEntry: (entry: MealPlanEntryCreate) =>
		request<MealPlanEntry>('/api/meal-plan', { method: 'POST', body: JSON.stringify(entry) }),
	deleteMealPlanEntry: (id: number) => request<void>(`/api/meal-plan/${id}`, { method: 'DELETE' }),
	markMealPlanEntryEaten: (id: number) =>
		request<DiaryEntry>(`/api/meal-plan/${id}/mark-eaten`, { method: 'POST' }),
	getShoppingList: (startDate: string, endDate: string) =>
		request<ShoppingList>(`/api/meal-plan/shopping-list?start_date=${startDate}&end_date=${endDate}`),
	getPlanOptimization: (startDate: string, endDate: string, maxAdditionalCost?: number | null) =>
		request<PlanOptimization | null>(
			`/api/meal-plan/optimize?start_date=${startDate}&end_date=${endDate}` +
				(maxAdditionalCost != null ? `&max_additional_cost=${maxAdditionalCost}` : '')
		),

	listMealPlanTemplates: () => request<MealPlanTemplate[]>('/api/meal-plan-templates'),
	createMealPlanTemplate: (name: string, startDate: string, endDate: string) =>
		request<MealPlanTemplate>('/api/meal-plan-templates', {
			method: 'POST',
			body: JSON.stringify({ name, start_date: startDate, end_date: endDate })
		}),
	getMealPlanTemplate: (id: number) => request<MealPlanTemplateDetail>(`/api/meal-plan-templates/${id}`),
	deleteMealPlanTemplate: (id: number) => request<void>(`/api/meal-plan-templates/${id}`, { method: 'DELETE' }),
	applyMealPlanTemplate: (id: number, startDate: string) =>
		request<MealPlanEntry[]>(`/api/meal-plan-templates/${id}/apply?start_date=${startDate}`, { method: 'POST' }),

	listFoodPrices: () => request<FoodPrice[]>('/api/food-prices'),
	setFoodPrice: (foodId: number, price: FoodPriceCreate) =>
		request<FoodPrice>(`/api/food-prices/${foodId}`, { method: 'PUT', body: JSON.stringify(price) }),
	deleteFoodPrice: (foodId: number) => request<void>(`/api/food-prices/${foodId}`, { method: 'DELETE' }),

	getFilterKeys: () => request<FilterKeysResponse>('/api/search/keys'),
	searchFoods: (req: SearchRequest) =>
		request<Food[]>('/api/foods/search', { method: 'POST', body: JSON.stringify(req) }),
	searchRecipes: (req: SearchRequest) =>
		request<Recipe[]>('/api/recipes/search', { method: 'POST', body: JSON.stringify(req) }),

	listPresets: (scope: FilterScope) => request<SavedFilterPreset[]>(`/api/presets?scope=${scope}`),
	createPreset: (preset: SavedFilterPresetCreate) =>
		request<SavedFilterPreset>('/api/presets', { method: 'POST', body: JSON.stringify(preset) }),
	deletePreset: (id: number) => request<void>(`/api/presets/${id}`, { method: 'DELETE' }),

	listCollections: () => request<Collection[]>('/api/collections'),
	createCollection: (name: string) =>
		request<Collection>('/api/collections', { method: 'POST', body: JSON.stringify({ name }) }),
	getCollection: (id: number) => request<CollectionDetail>(`/api/collections/${id}`),
	deleteCollection: (id: number) => request<void>(`/api/collections/${id}`, { method: 'DELETE' }),
	addRecipeToCollection: (collectionId: number, recipeId: number) =>
		request<CollectionDetail>(`/api/collections/${collectionId}/recipes`, {
			method: 'POST',
			body: JSON.stringify({ recipe_id: recipeId })
		}),
	removeRecipeFromCollection: (collectionId: number, recipeId: number) =>
		request<CollectionDetail>(`/api/collections/${collectionId}/recipes/${recipeId}`, { method: 'DELETE' }),

	inviteClinicianClient: (clientEmail: string) =>
		request<ClinicianLink>('/api/clinician/invites', {
			method: 'POST',
			body: JSON.stringify({ client_email: clientEmail })
		}),
	listPendingClinicianInvites: () => request<ClinicianLink[]>('/api/clinician/invites/pending'),
	acceptClinicianInvite: (linkId: number) =>
		request<ClinicianLink>(`/api/clinician/invites/${linkId}/accept`, { method: 'POST' }),
	declineClinicianInvite: (linkId: number) =>
		request<ClinicianLink>(`/api/clinician/invites/${linkId}/decline`, { method: 'POST' }),
	listClinicianClients: () => request<ClinicianLink[]>('/api/clinician/clients'),
	revokeClinicianClient: (clientUserId: number) =>
		request<void>(`/api/clinician/clients/${clientUserId}`, { method: 'DELETE' }),
	getClinicianClientSummary: (clientUserId: number, entryDate: string) =>
		request<ClinicianClientSummary>(`/api/clinician/clients/${clientUserId}/summary?entry_date=${entryDate}`),
	listClinicianNotes: (clientUserId: number) =>
		request<ClinicianNote[]>(`/api/clinician/clients/${clientUserId}/notes`),
	createClinicianNote: (clientUserId: number, noteText: string) =>
		request<ClinicianNote>(`/api/clinician/clients/${clientUserId}/notes`, {
			method: 'POST',
			body: JSON.stringify({ note_text: noteText })
		})
};
