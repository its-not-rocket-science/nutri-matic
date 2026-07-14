export interface AminoAcidProfile {
	histidine: number;
	isoleucine: number;
	leucine: number;
	lysine: number;
	met_cys: number;
	phe_tyr: number;
	threonine: number;
	tryptophan: number;
	valine: number;
}

export interface Food {
	id: number;
	name: string;
	protein_g_per_100g: number;
	amino_acids: AminoAcidProfile;
	digestibility_diaas: AminoAcidProfile | null;
	digestibility_pdcaas: number | null;
	gtin_upc: string | null;
}

export interface FoodCreate {
	name: string;
	protein_g_per_100g: number;
	amino_acids: AminoAcidProfile;
	digestibility_diaas: AminoAcidProfile | null;
	digestibility_pdcaas: number | null;
}

export interface Score {
	method: 'diaas' | 'pdcaas';
	pattern_used: string;
	score: number;
	limiting_amino_acid: string;
	per_aa_ratios: Record<string, number>;
	digestibility_source: 'measured' | 'estimated' | null;
	methodology_version: string;
}

export interface ComplementSuggestion {
	food_id: number;
	food_name: string;
	combined_score: number;
	score_improvement: number;
}

export interface Complement {
	original_score: number;
	limiting_amino_acid: string;
	suggestions: ComplementSuggestion[];
	methodology_version: string;
}

export interface NutrientProvenance {
	key: string;
	name: string;
	fdc_nutrient_nbr: string;
	amount_per_100g: number;
	drv_source: string | null;
	drv_confidence: string | null;
}

export interface FoodProvenance {
	food_id: number;
	food_name: string;
	fdc_id: number | null;
	data_type: string | null;
	dataset_label: string | null;
	gtin_upc: string | null;
	digestibility_diaas_source: string | null;
	digestibility_pdcaas_source: string | null;
	nutrients: NutrientProvenance[];
}

export interface NutrientAmount {
	key: string;
	name: string;
	unit: string;
	/** per 100g for a food, per serving for a recipe, per day for a diary summary */
	amount: number;
	adult_drv: number | null;
	percent_drv: number | null;
	/** provenance of adult_drv, e.g. "UK RNI; pregnancy increment confirmed live" */
	drv_source: string | null;
	/** "live_confirmed" | "secondary_source" | "personalized_calculation" | null */
	drv_confidence: string | null;
	drv_methodology_version: string;
}

export interface User {
	id: number;
	email: string;
	sex: 'male' | 'female' | null;
	birth_year: number | null;
	activity_level: 'sedentary' | 'light' | 'moderate' | 'active' | 'very_active' | null;
	is_pregnant: boolean;
	is_lactating: boolean;
	weight_kg: number | null;
	height_cm: number | null;
}

export interface ProfileUpdate {
	sex: 'male' | 'female' | null;
	birth_year: number | null;
	activity_level: User['activity_level'];
	is_pregnant: boolean;
	is_lactating: boolean;
	weight_kg: number | null;
	height_cm: number | null;
}

export interface WeightLog {
	id: number;
	log_date: string;
	weight_kg: number;
}

export interface WeightLogCreate {
	log_date: string;
	weight_kg: number;
}

export interface TokenResponse {
	access_token: string;
	token_type: string;
}

export interface RecipeIngredient {
	food_id: number;
	food_name: string;
	quantity_g: number;
}

export interface Recipe {
	id: number;
	name: string;
	servings: number;
	ingredients: RecipeIngredient[];
	owner_email: string;
	is_owner: boolean;
	average_rating: number | null;
	rating_count: number;
	tags: string[];
}

export interface RecipeCreate {
	name: string;
	servings: number;
	ingredients: { food_id: number; quantity_g: number }[];
}

export interface RecipeShare {
	id: number;
	email: string;
	created_at: string;
}

export interface RecipeRatingSummary {
	average: number | null;
	count: number;
	my_rating: number | null;
}

export interface RecipeComment {
	id: number;
	user_email: string;
	body: string;
	created_at: string;
	is_own: boolean;
}

export interface Collection {
	id: number;
	name: string;
	recipe_count: number;
}

export interface CollectionDetail {
	id: number;
	name: string;
	recipes: Recipe[];
}

export type Meal = 'breakfast' | 'lunch' | 'dinner' | 'snack';

export interface DiaryEntry {
	id: number;
	entry_date: string;
	meal: Meal;
	food_id: number | null;
	food_name: string | null;
	quantity_g: number | null;
	recipe_id: number | null;
	recipe_name: string | null;
	quantity_servings: number | null;
}

export interface DiaryEntryCreate {
	entry_date: string;
	meal: Meal;
	food_id?: number | null;
	quantity_g?: number | null;
	recipe_id?: number | null;
	quantity_servings?: number | null;
}

export interface MealIronBioavailability {
	meal: Meal;
	heme_iron_mg: number;
	non_heme_iron_mg: number;
	vitamin_c_mg: number;
	absorbed_heme_mg: number;
	absorbed_non_heme_mg: number;
	absorbed_total_mg: number;
	non_heme_absorption_tier: 'baseline' | 'enhanced';
	iron_split_source: 'measured' | 'estimated';
}

export interface CalciumPhosphorus {
	calcium_mg: number;
	phosphorus_mg: number;
	ratio: number;
	guidance: string;
}

export interface QuickAddItem {
	food_id: number | null;
	food_name: string | null;
	recipe_id: number | null;
	recipe_name: string | null;
	quantity_g: number | null;
	quantity_servings: number | null;
	last_logged: string;
	log_count: number;
}

export interface QuickAdd {
	recent: QuickAddItem[];
	frequent: QuickAddItem[];
}

export interface SodiumPotassium {
	sodium_mg: number;
	potassium_mg: number;
	ratio: number | null;
	guidance: string;
}

export interface MealProteinDistribution {
	meal: Meal;
	protein_g: number;
	leucine_g: number;
	leucine_threshold_g: number;
	meets_leucine_threshold: boolean;
}

export interface DiarySummary {
	entries: DiaryEntry[];
	nutrients: NutrientAmount[];
	iron_bioavailability: MealIronBioavailability[];
	calcium_phosphorus: CalciumPhosphorus | null;
	sodium_potassium: SodiumPotassium | null;
	protein_distribution: MealProteinDistribution[];
}

export interface DiaryMealTemplateItem {
	food_id: number | null;
	food_name: string | null;
	quantity_g: number | null;
	recipe_id: number | null;
	recipe_name: string | null;
	quantity_servings: number | null;
}

export interface DiaryMealTemplate {
	id: number;
	name: string;
	item_count: number;
}

export interface DiaryMealTemplateDetail {
	id: number;
	name: string;
	items: DiaryMealTemplateItem[];
}

export interface MealPlanEntry {
	id: number;
	plan_date: string;
	meal: Meal;
	food_id: number | null;
	food_name: string | null;
	quantity_g: number | null;
	recipe_id: number | null;
	recipe_name: string | null;
	quantity_servings: number | null;
}

export interface MealPlanEntryCreate {
	plan_date: string;
	meal: Meal;
	food_id?: number | null;
	quantity_g?: number | null;
	recipe_id?: number | null;
	quantity_servings?: number | null;
}

export interface MealPlanTemplateEntry {
	day_offset: number;
	meal: Meal;
	food_id: number | null;
	food_name: string | null;
	quantity_g: number | null;
	recipe_id: number | null;
	recipe_name: string | null;
	quantity_servings: number | null;
}

export interface MealPlanTemplate {
	id: number;
	name: string;
	entry_count: number;
}

export interface MealPlanTemplateDetail {
	id: number;
	name: string;
	entries: MealPlanTemplateEntry[];
}

export interface ShoppingListItem {
	food_id: number;
	food_name: string;
	quantity_g: number;
	price_per_100g: number | null;
	estimated_cost: number | null;
}

export interface ShoppingList {
	items: ShoppingListItem[];
	total_cost: number;
	items_missing_price: number;
}

export interface FoodPrice {
	id: number;
	food_id: number;
	food_name: string;
	package_price: number;
	package_quantity_g: number;
	price_per_100g: number;
}

export interface FoodPriceCreate {
	package_price: number;
	package_quantity_g: number;
}

export type TrendGroupBy = 'week' | 'month';

export interface TrendNutrient {
	key: string;
	name: string;
	unit: string;
	avg_amount: number;
	adult_drv: number | null;
	avg_percent_drv: number | null;
	drv_source: string | null;
	drv_confidence: string | null;
	drv_methodology_version: string;
}

export interface TrendBucket {
	bucket_start: string;
	bucket_end: string;
	logged_days: number;
	nutrients: TrendNutrient[];
}

export interface DiaryTrends {
	group_by: TrendGroupBy;
	buckets: TrendBucket[];
}

export interface FoodNutrientRank {
	food_id: number;
	food_name: string;
	amount_per_100g: number;
}

export interface GapSuggestion {
	nutrient_key: string;
	nutrient_name: string;
	unit: string;
	percent_drv: number;
	foods: FoodNutrientRank[];
}

export interface OptimizationSuggestion {
	action: 'add' | 'swap';
	food_id: number;
	food_name: string;
	quantity_g: number;
	replaces_food_id: number | null;
	replaces_food_name: string | null;
	before_percent_drv: number;
	after_percent_drv: number;
	improvement: number;
	calories_added: number;
	improvement_per_100kcal: number | null;
}

export interface MealOptimization {
	meal: Meal;
	target_nutrient_key: string;
	target_nutrient_name: string;
	suggestions: OptimizationSuggestion[];
}

export type FilterOp = 'gte' | 'lte' | 'eq';

export interface FilterKey {
	key: string;
	label: string;
	unit: string | null;
}

export interface NutrientFilterInput {
	key: string;
	op: FilterOp;
	value: number;
}

export interface SearchRequest {
	filters: NutrientFilterInput[];
	limit?: number;
}

export interface FilterKeysResponse {
	food: FilterKey[];
	recipe: FilterKey[];
}

export type FilterScope = 'food' | 'recipe';

export interface SavedFilterPreset {
	id: number;
	name: string;
	scope: FilterScope;
	filters: NutrientFilterInput[];
}

export interface SavedFilterPresetCreate {
	name: string;
	scope: FilterScope;
	filters: NutrientFilterInput[];
}

export const AMINO_ACID_LABELS: Record<keyof AminoAcidProfile, string> = {
	histidine: 'Histidine',
	isoleucine: 'Isoleucine',
	leucine: 'Leucine',
	lysine: 'Lysine',
	met_cys: 'Methionine + Cysteine',
	phe_tyr: 'Phenylalanine + Tyrosine',
	threonine: 'Threonine',
	tryptophan: 'Tryptophan',
	valine: 'Valine'
};
