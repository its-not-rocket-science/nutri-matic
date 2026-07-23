import { goto } from '$app/navigation';
import { activeProfile } from './activeProfile.svelte';
import { auth } from './auth.svelte';
import type {
	AbsorbedProtein,
	AccountUpdate,
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
	DietaryConstraint,
	DietaryConstraintCreate,
	DietaryVocabulary,
	FilterKeysResponse,
	FilterScope,
	Food,
	FoodCreate,
	FoodList,
	FoodPrice,
	FoodPriceCreate,
	FoodProvenance,
	GapSuggestion,
	IngredientSuggestions,
	Meal,
	MealOptimization,
	MealPlanEntry,
	MealPlanEntryCreate,
	MealPlanTemplate,
	MealPlanTemplateDetail,
	NutrientAmount,
	PlanOptimization,
	Profile,
	ProfileCreate,
	ProfileUpdate,
	QuickAdd,
	Recipe,
	RecipeComment,
	RecipeCreate,
	RecipeRatingSummary,
	RecipeShare,
	RecipeSuggestions,
	RecipeUpdate,
	Robustness,
	SavedFilterPreset,
	SavedFilterPresetCreate,
	Score,
	SearchRequest,
	ShoppingList,
	SubstitutionSuggestions,
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

/** Appends the currently active household profile's id as a query param —
 * every profile-scoped endpoint (diary, weight log, meal plan, templates,
 * presets, dietary constraints) defaults to the account's owner profile
 * server-side when this is omitted, so omitting it before a profile list
 * has ever loaded is still safe, just not switchable yet. */
function withProfile(path: string): string {
	if (activeProfile.id == null) return path;
	const sep = path.includes('?') ? '&' : '?';
	return `${path}${sep}profile_id=${activeProfile.id}`;
}

/** One of three mutually exclusive scopes GET /api/recommendations/* takes
 * — a single day (optionally one meal within it), a multi-day meal-plan
 * range, or a standalone recipe (recipe-detail page's "Improve this
 * recipe") — matching the backend's "give exactly one" validation in
 * routers/recommendations.py. */
export type RecommendationScope =
	| { kind: 'day'; entryDate: string; meal?: Meal; source?: 'diary' | 'meal_plan' }
	| { kind: 'range'; startDate: string; endDate: string }
	| { kind: 'recipe'; recipeId: number; servings?: number };

function scopeParams(scope: RecommendationScope): URLSearchParams {
	const params = new URLSearchParams();
	if (scope.kind === 'day') {
		params.set('entry_date', scope.entryDate);
		if (scope.meal) params.set('meal', scope.meal);
		if (scope.source) params.set('source', scope.source);
	} else if (scope.kind === 'range') {
		params.set('start_date', scope.startDate);
		params.set('end_date', scope.endDate);
		params.set('source', 'meal_plan');
	} else {
		params.set('recipe_id', String(scope.recipeId));
		if (scope.servings != null) params.set('servings', String(scope.servings));
	}
	return params;
}

export interface IngredientSuggestionOptions {
	maxAdditionalEnergy?: number;
	maxSuggestions?: number;
	priorityNutrients?: string[];
}

export interface RecipeSuggestionOptions {
	maxAdditionalEnergy?: number;
	maxSuggestions?: number;
	priorityNutrients?: string[];
	goal?: string;
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
	startDemo: () => request<TokenResponse>('/api/auth/demo', { method: 'POST' }),
	login: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
	me: () => request<User>('/api/auth/me'),

	getAccount: () => request<User>('/api/account'),
	updateAccount: (body: AccountUpdate) =>
		request<User>('/api/account', { method: 'PUT', body: JSON.stringify(body) }),

	listProfiles: () => request<Profile[]>('/api/profiles'),
	createProfile: (profile: ProfileCreate) =>
		request<Profile>('/api/profiles', { method: 'POST', body: JSON.stringify(profile) }),
	getProfile: (id: number) => request<Profile>(`/api/profiles/${id}`),
	updateProfile: (id: number, profile: ProfileUpdate) =>
		request<Profile>(`/api/profiles/${id}`, { method: 'PUT', body: JSON.stringify(profile) }),
	deleteProfile: (id: number) => request<void>(`/api/profiles/${id}`, { method: 'DELETE' }),

	getDietaryVocabulary: () => request<DietaryVocabulary>('/api/profiles/dietary-vocabulary'),
	listDietaryConstraints: (profileId: number) =>
		request<DietaryConstraint[]>(`/api/profiles/${profileId}/dietary-constraints`),
	createDietaryConstraint: (profileId: number, constraint: DietaryConstraintCreate) =>
		request<DietaryConstraint>(`/api/profiles/${profileId}/dietary-constraints`, {
			method: 'POST',
			body: JSON.stringify(constraint)
		}),
	deleteDietaryConstraint: (profileId: number, id: number) =>
		request<void>(`/api/profiles/${profileId}/dietary-constraints/${id}`, { method: 'DELETE' }),

	logWeight: (entry: WeightLogCreate) =>
		request<WeightLog>(withProfile('/api/weight-logs'), { method: 'POST', body: JSON.stringify(entry) }),
	listWeightLogs: (startDate: string, endDate: string) =>
		request<WeightLog[]>(withProfile(`/api/weight-logs?start_date=${startDate}&end_date=${endDate}`)),
	deleteWeightLog: (id: number) => request<void>(withProfile(`/api/weight-logs/${id}`), { method: 'DELETE' }),

	listRecipes: (tag?: string) => request<Recipe[]>(`/api/recipes${tag ? `?tag=${encodeURIComponent(tag)}` : ''}`),
	listSharedWithMe: () => request<Recipe[]>('/api/recipes/shared-with-me'),
	listPublicRecipes: () => request<Recipe[]>('/api/recipes/public'),
	listMyTags: () => request<string[]>('/api/recipes/tags'),
	addTag: (recipeId: number, tag: string) =>
		request<Recipe>(`/api/recipes/${recipeId}/tags`, { method: 'POST', body: JSON.stringify({ tag }) }),
	removeTag: (recipeId: number, tag: string) =>
		request<Recipe>(`/api/recipes/${recipeId}/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' }),
	getRecipe: (id: number) => request<Recipe>(`/api/recipes/${id}`),
	createRecipe: (recipe: RecipeCreate) =>
		request<Recipe>('/api/recipes', { method: 'POST', body: JSON.stringify(recipe) }),
	deleteRecipe: (id: number) => request<void>(`/api/recipes/${id}`, { method: 'DELETE' }),
	updateRecipe: (id: number, body: RecipeUpdate) =>
		request<Recipe>(`/api/recipes/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	addIngredient: (recipeId: number, foodId: number, quantityG: number) =>
		request<Recipe>(`/api/recipes/${recipeId}/ingredients`, {
			method: 'POST',
			body: JSON.stringify({ food_id: foodId, quantity_g: quantityG })
		}),
	updateIngredient: (recipeId: number, ingredientId: number, quantityG: number) =>
		request<Recipe>(`/api/recipes/${recipeId}/ingredients/${ingredientId}`, {
			method: 'PATCH',
			body: JSON.stringify({ quantity_g: quantityG })
		}),
	removeIngredient: (recipeId: number, ingredientId: number) =>
		request<Recipe>(`/api/recipes/${recipeId}/ingredients/${ingredientId}`, { method: 'DELETE' }),
	copyRecipe: (id: number) => request<Recipe>(`/api/recipes/${id}/copy`, { method: 'POST' }),
	scoreRecipe: (id: number, method: 'diaas' | 'pdcaas') =>
		request<Score>(`/api/recipes/${id}/score?method=${method}`),
	getRecipeNutrients: (id: number) => request<NutrientAmount[]>(withProfile(`/api/recipes/${id}/nutrients`)),
	getRecipeAbsorbedProtein: (id: number) =>
		request<AbsorbedProtein | null>(withProfile(`/api/recipes/${id}/absorbed-protein`)),
	getRecipeRobustness: (id: number) => request<Robustness | null>(`/api/recipes/${id}/robustness`),

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

	getDiaryDay: (entryDate: string) => request<DiarySummary>(withProfile(`/api/diary?entry_date=${entryDate}`)),
	addDiaryEntry: (entry: DiaryEntryCreate) =>
		request<DiaryEntry>(withProfile('/api/diary'), { method: 'POST', body: JSON.stringify(entry) }),
	deleteDiaryEntry: (id: number) => request<void>(withProfile(`/api/diary/${id}`), { method: 'DELETE' }),
	copyDiaryDay: (sourceDate: string, targetDate: string) =>
		request<DiaryEntry[]>(withProfile(`/api/diary/copy-day?source_date=${sourceDate}&target_date=${targetDate}`), {
			method: 'POST'
		}),
	getDiaryTrends: (startDate: string, endDate: string, groupBy: TrendGroupBy) =>
		request<DiaryTrends>(
			withProfile(`/api/diary/trends?start_date=${startDate}&end_date=${endDate}&group_by=${groupBy}`)
		),
	getQuickAdd: () => request<QuickAdd>(withProfile('/api/diary/quick-add')),
	getGapSuggestions: (entryDate: string) =>
		request<GapSuggestion | null>(withProfile(`/api/diary/gap-suggestions?entry_date=${entryDate}`)),
	getDiarySnapshot: (entryDate: string) =>
		request<DiarySnapshot | null>(withProfile(`/api/diary/snapshot?entry_date=${entryDate}`)),
	createDiarySnapshot: (entryDate: string) =>
		request<DiarySnapshot>(withProfile(`/api/diary/snapshot?entry_date=${entryDate}`), { method: 'POST' }),
	getMealOptimization: (entryDate: string, meal: Meal, maxAdditionalCost?: number | null) =>
		request<MealOptimization | null>(
			withProfile(
				`/api/diary/meal-optimize?entry_date=${entryDate}&meal=${meal}` +
					(maxAdditionalCost != null ? `&max_additional_cost=${maxAdditionalCost}` : '')
			)
		),

	// "Improve this…" nutrient-gap recommendations (prompts 6-10). See
	// docs/nutrient-gap-recommendations.md — these never diagnose a
	// deficiency, only describe nutrients as below/near/within/above the
	// app's own target.
	getIngredientSuggestions: (scope: RecommendationScope, options: IngredientSuggestionOptions = {}) => {
		const params = scopeParams(scope);
		if (options.maxAdditionalEnergy != null) params.set('max_additional_energy', String(options.maxAdditionalEnergy));
		if (options.maxSuggestions != null) params.set('max_suggestions', String(options.maxSuggestions));
		if (options.priorityNutrients?.length) params.set('priority_nutrients', options.priorityNutrients.join(','));
		return request<IngredientSuggestions>(withProfile(`/api/recommendations/ingredients?${params}`));
	},
	getRecipeSuggestions: (scope: RecommendationScope, options: RecipeSuggestionOptions = {}) => {
		const params = scopeParams(scope);
		if (options.maxAdditionalEnergy != null) params.set('max_additional_energy', String(options.maxAdditionalEnergy));
		if (options.maxSuggestions != null) params.set('max_suggestions', String(options.maxSuggestions));
		if (options.priorityNutrients?.length) params.set('priority_nutrients', options.priorityNutrients.join(','));
		if (options.goal) params.set('goal', options.goal);
		return request<RecipeSuggestions>(withProfile(`/api/recommendations/recipes?${params}`));
	},
	getSubstitutionSuggestions: (
		entryId: number,
		source: 'diary' | 'meal_plan' = 'diary',
		options: { maxSuggestions?: number; priorityNutrients?: string[]; energyToleranceKcal?: number } = {}
	) => {
		const params = new URLSearchParams({ entry_id: String(entryId), source });
		if (options.maxSuggestions != null) params.set('max_suggestions', String(options.maxSuggestions));
		if (options.priorityNutrients?.length) params.set('priority_nutrients', options.priorityNutrients.join(','));
		if (options.energyToleranceKcal != null) params.set('energy_tolerance_kcal', String(options.energyToleranceKcal));
		return request<SubstitutionSuggestions>(withProfile(`/api/recommendations/substitutions?${params}`));
	},

	listDiaryMealTemplates: () => request<DiaryMealTemplate[]>(withProfile('/api/diary-meal-templates')),
	createDiaryMealTemplate: (name: string, entryDate: string, meal: Meal) =>
		request<DiaryMealTemplate>(withProfile('/api/diary-meal-templates'), {
			method: 'POST',
			body: JSON.stringify({ name, entry_date: entryDate, meal })
		}),
	getDiaryMealTemplate: (id: number) =>
		request<DiaryMealTemplateDetail>(withProfile(`/api/diary-meal-templates/${id}`)),
	deleteDiaryMealTemplate: (id: number) =>
		request<void>(withProfile(`/api/diary-meal-templates/${id}`), { method: 'DELETE' }),
	applyDiaryMealTemplate: (id: number, entryDate: string, meal: Meal) =>
		request<DiaryEntry[]>(
			withProfile(`/api/diary-meal-templates/${id}/apply?entry_date=${entryDate}&meal=${meal}`),
			{ method: 'POST' }
		),

	listMealPlanEntries: (startDate: string, endDate: string) =>
		request<MealPlanEntry[]>(withProfile(`/api/meal-plan?start_date=${startDate}&end_date=${endDate}`)),
	addMealPlanEntry: (entry: MealPlanEntryCreate) =>
		request<MealPlanEntry>(withProfile('/api/meal-plan'), { method: 'POST', body: JSON.stringify(entry) }),
	deleteMealPlanEntry: (id: number) => request<void>(withProfile(`/api/meal-plan/${id}`), { method: 'DELETE' }),
	markMealPlanEntryEaten: (id: number) =>
		request<DiaryEntry>(withProfile(`/api/meal-plan/${id}/mark-eaten`), { method: 'POST' }),
	getShoppingList: (startDate: string, endDate: string, profileIds?: number[]) =>
		request<ShoppingList>(
			withProfile(
				`/api/meal-plan/shopping-list?start_date=${startDate}&end_date=${endDate}` +
					(profileIds && profileIds.length > 0 ? `&profile_ids=${profileIds.join(',')}` : '')
			)
		),
	getPlanOptimization: (startDate: string, endDate: string, maxAdditionalCost?: number | null) =>
		request<PlanOptimization | null>(
			withProfile(
				`/api/meal-plan/optimize?start_date=${startDate}&end_date=${endDate}` +
					(maxAdditionalCost != null ? `&max_additional_cost=${maxAdditionalCost}` : '')
			)
		),

	listMealPlanTemplates: () => request<MealPlanTemplate[]>(withProfile('/api/meal-plan-templates')),
	createMealPlanTemplate: (name: string, startDate: string, endDate: string) =>
		request<MealPlanTemplate>(withProfile('/api/meal-plan-templates'), {
			method: 'POST',
			body: JSON.stringify({ name, start_date: startDate, end_date: endDate })
		}),
	getMealPlanTemplate: (id: number) =>
		request<MealPlanTemplateDetail>(withProfile(`/api/meal-plan-templates/${id}`)),
	deleteMealPlanTemplate: (id: number) =>
		request<void>(withProfile(`/api/meal-plan-templates/${id}`), { method: 'DELETE' }),
	applyMealPlanTemplate: (id: number, startDate: string) =>
		request<MealPlanEntry[]>(withProfile(`/api/meal-plan-templates/${id}/apply?start_date=${startDate}`), {
			method: 'POST'
		}),

	listFoodPrices: () => request<FoodPrice[]>('/api/food-prices'),
	setFoodPrice: (foodId: number, price: FoodPriceCreate) =>
		request<FoodPrice>(`/api/food-prices/${foodId}`, { method: 'PUT', body: JSON.stringify(price) }),
	deleteFoodPrice: (foodId: number) => request<void>(`/api/food-prices/${foodId}`, { method: 'DELETE' }),

	getFilterKeys: () => request<FilterKeysResponse>('/api/search/keys'),
	searchFoods: (req: SearchRequest) =>
		request<Food[]>('/api/foods/search', { method: 'POST', body: JSON.stringify(req) }),
	searchRecipes: (req: SearchRequest) =>
		request<Recipe[]>(withProfile('/api/recipes/search'), { method: 'POST', body: JSON.stringify(req) }),

	listPresets: (scope: FilterScope) => request<SavedFilterPreset[]>(withProfile(`/api/presets?scope=${scope}`)),
	createPreset: (preset: SavedFilterPresetCreate) =>
		request<SavedFilterPreset>(withProfile('/api/presets'), { method: 'POST', body: JSON.stringify(preset) }),
	deletePreset: (id: number) => request<void>(withProfile(`/api/presets/${id}`), { method: 'DELETE' }),

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
