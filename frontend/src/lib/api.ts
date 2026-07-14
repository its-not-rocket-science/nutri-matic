import { auth } from './auth.svelte';
import type {
	Collection,
	CollectionDetail,
	DiaryEntry,
	DiaryEntryCreate,
	DiarySummary,
	DiaryTrends,
	FilterKeysResponse,
	FilterScope,
	Food,
	FoodCreate,
	FoodPrice,
	FoodPriceCreate,
	MealPlanEntry,
	MealPlanEntryCreate,
	MealPlanTemplate,
	MealPlanTemplateDetail,
	NutrientAmount,
	ProfileUpdate,
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
	getFoodByBarcode: (gtinUpc: string) => request<Food>(`/api/foods/barcode/${encodeURIComponent(gtinUpc)}`),
	getNutrients: (id: number) => request<NutrientAmount[]>(`/api/foods/${id}/nutrients`),

	register: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
	login: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
	me: () => request<User>('/api/auth/me'),

	getProfile: () => request<User>('/api/profile'),
	updateProfile: (profile: ProfileUpdate) =>
		request<User>('/api/profile', { method: 'PUT', body: JSON.stringify(profile) }),

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
	getDiaryTrends: (startDate: string, endDate: string, groupBy: TrendGroupBy) =>
		request<DiaryTrends>(`/api/diary/trends?start_date=${startDate}&end_date=${endDate}&group_by=${groupBy}`),

	listMealPlanEntries: (startDate: string, endDate: string) =>
		request<MealPlanEntry[]>(`/api/meal-plan?start_date=${startDate}&end_date=${endDate}`),
	addMealPlanEntry: (entry: MealPlanEntryCreate) =>
		request<MealPlanEntry>('/api/meal-plan', { method: 'POST', body: JSON.stringify(entry) }),
	deleteMealPlanEntry: (id: number) => request<void>(`/api/meal-plan/${id}`, { method: 'DELETE' }),
	markMealPlanEntryEaten: (id: number) =>
		request<DiaryEntry>(`/api/meal-plan/${id}/mark-eaten`, { method: 'POST' }),
	getShoppingList: (startDate: string, endDate: string) =>
		request<ShoppingList>(`/api/meal-plan/shopping-list?start_date=${startDate}&end_date=${endDate}`),

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
		request<CollectionDetail>(`/api/collections/${collectionId}/recipes/${recipeId}`, { method: 'DELETE' })
};
