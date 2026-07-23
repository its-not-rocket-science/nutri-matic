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

/** Display-only — never "excluded" (those are dropped before display, not
 * badged). Only present on search/discovery results for a signed-in user
 * with dietary constraints; absent (null) elsewhere. See dietary_filter.py. */
export interface DietaryStatus {
	status: 'avoid' | 'unknown';
	confidence: 'high' | 'low';
	reasons: string[];
}

export interface Food {
	id: number;
	name: string;
	protein_g_per_100g: number;
	amino_acids: AminoAcidProfile;
	digestibility_diaas: AminoAcidProfile | null;
	digestibility_pdcaas: number | null;
	gtin_upc: string | null;
	dietary_status?: DietaryStatus | null;
}

export interface FoodList {
	items: Food[];
	total: number;
	limit: number;
	offset: number;
	has_more: boolean;
}

export interface FoodCreate {
	name: string;
	protein_g_per_100g: number;
	amino_acids: AminoAcidProfile;
	digestibility_diaas: AminoAcidProfile | null;
	digestibility_pdcaas: number | null;
}

export interface ExcludedIngredient {
	food_id: number;
	name: string;
	protein_g: number;
}

export interface Score {
	method: 'diaas' | 'pdcaas';
	pattern_used: string;
	score: number;
	limiting_amino_acid: string;
	per_aa_ratios: Record<string, number>;
	digestibility_source: 'measured' | 'estimated' | null;
	methodology_version: string;
	// coverage_fraction < 1.0 / is_partial true means this score was
	// computed from only the ingredients with complete amino acid +
	// digestibility data -- see backend aggregation.py's
	// compute_protein_quality_with_coverage.
	coverage_fraction: number;
	is_partial: boolean;
	excluded_ingredients: ExcludedIngredient[];
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
	/** set when this raw value is thousands of times its own DRV — almost
	 *  certainly a source data error, not a real property of the food */
	implausible_reason: string | null;
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
	/** set when `amount` is thousands of times its own DRV — almost certainly
	 *  a source data error; excluded from totals/suggestions upstream, shown
	 *  here purely for transparency */
	implausible_reason: string | null;
	/** true only for the "energy" row when adult_drv reflects a weight-loss
	 *  goal's calorie deficit rather than plain maintenance EER */
	goal_adjusted?: boolean;
}

/** Account-level fields only — bio/dietary/goal fields live on Profile
 * (an account can have more than one, see the household-profiles feature). */
export interface User {
	id: number;
	email: string;
	/** ISO 4217 code, or null to use the browser locale's implied currency */
	currency: string | null;
	plan: string;
}

export interface AccountUpdate {
	currency?: string | null;
}

export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'active' | 'very_active';

export interface Profile {
	id: number;
	name: string;
	is_account_owner: boolean;
	sex: 'male' | 'female' | null;
	birth_year: number | null;
	activity_level: ActivityLevel | null;
	is_pregnant: boolean;
	is_lactating: boolean;
	weight_kg: number | null;
	height_cm: number | null;
	dietary_pattern: string | null;
	/** onboarding's step-1 pick — null if never set */
	goal: string | null;
}

export interface ProfileCreate {
	name: string;
	sex: 'male' | 'female' | null;
	birth_year: number | null;
	activity_level: ActivityLevel | null;
	is_pregnant: boolean;
	is_lactating: boolean;
	weight_kg: number | null;
	height_cm: number | null;
	dietary_pattern: string | null;
	goal?: string | null;
}

export interface ProfileUpdate {
	name: string;
	sex: 'male' | 'female' | null;
	birth_year: number | null;
	activity_level: ActivityLevel | null;
	is_pregnant: boolean;
	is_lactating: boolean;
	weight_kg: number | null;
	height_cm: number | null;
	dietary_pattern: string | null;
	goal?: string | null;
}

export type DietaryConstraintCategory = 'allergy' | 'intolerance' | 'religious' | 'medical' | 'preference';
export type DietarySeverity = 'hard_exclude' | 'avoid';

export interface DietaryConstraint {
	id: number;
	category: DietaryConstraintCategory;
	tag: string | null;
	severity: DietarySeverity | null;
	note: string | null;
}

export interface DietaryConstraintCreate {
	category: DietaryConstraintCategory;
	tag: string | null;
	severity: DietarySeverity | null;
	note: string | null;
}

export interface DietaryTag {
	key: string;
	label: string;
}

export interface DietaryPattern {
	key: string;
	label: string;
	excludes: string[];
}

export interface DietaryVocabulary {
	allergen_tags: DietaryTag[];
	religious_requirements: DietaryPattern[];
	dietary_patterns: DietaryPattern[];
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
	id: number;
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
	is_public: boolean;
	average_rating: number | null;
	rating_count: number;
	tags: string[];
	dietary_status?: DietaryStatus | null;
	source_url: string | null;
	method: string | null;
	is_stock: boolean;
	source_name: string | null;
	match_coverage_lines: number | null;
	match_coverage_mass: number | null;
	unresolved_ingredients: string[];
	// set only for a stock recipe whose ingredient list was deliberately
	// adapted/composited for nutritional-analysis purposes rather than
	// transcribed as a specific real-world dish — see the provenance
	// note built in recipes/[id]/+page.svelte.
	educational_note: string | null;
}

export interface RecipeCreate {
	name: string;
	servings: number;
	ingredients: { food_id: number; quantity_g: number }[];
	source_url?: string | null;
	method?: string | null;
}

export interface RecipeUpdate {
	name?: string;
	servings?: number;
	source_url?: string | null;
	method?: string | null;
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
	owner_email: string;
	is_owner: boolean;
	is_public: boolean;
	is_stock: boolean;
}

export interface CollectionDetail {
	id: number;
	name: string;
	owner_email: string;
	is_owner: boolean;
	is_public: boolean;
	is_stock: boolean;
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

export interface AbsorbedProtein {
	total_protein_g: number;
	/** null if that method's digestibility data is incomplete for the day's mix */
	diaas_absorbed_g: number | null;
	pdcaas_absorbed_g: number | null;
	/** null if the profile is incomplete (weight, birth year, activity level) */
	target_g: number | null;
	diaas_percent_drv: number | null;
	pdcaas_percent_drv: number | null;
	/** < 1.0 means diaas/pdcaas_absorbed_g came from only the ingredients with
	 * complete data for that method; null whenever the corresponding
	 * *_absorbed_g is itself null */
	diaas_coverage_fraction: number | null;
	pdcaas_coverage_fraction: number | null;
}

export interface RobustnessMetric {
	baseline: number | null;
	median: number | null;
	p10: number | null;
	p90: number | null;
	cv: number | null;
	threshold: number | null;
	prob_above_threshold: number | null;
	top_influential: { ingredient: string; impact: number }[];
	optional_sensitivity: number | null;
	unmatched_uncertainty_note: string | null;
	display_rating: number | null;
	explanation: string;
	not_calculated_reason: string | null;
	/** only meaningful for protein_quality_diaas/pdcaas and
	 * absorbed_protein_diaas/pdcaas -- null/empty for every other metric */
	coverage_fraction: number | null;
	excluded_foods: { food_id: number; name: string; protein_g: number }[];
}

/** A stock recipe's nutritional-robustness analysis — how stable its
 * calculated nutrition is under plausible ingredient-quantity variation.
 * NOT a health score or a suitability judgement — see docs/stock-recipes.md. */
export interface Robustness {
	model_version: string;
	computed_at: string;
	simulation_count: number;
	random_seed: number;
	metrics: Record<string, RobustnessMetric>;
	overall_rating: number | null;
	overall_explanation: string;
}

export interface DiarySummary {
	entries: DiaryEntry[];
	nutrients: NutrientAmount[];
	iron_bioavailability: MealIronBioavailability[];
	calcium_phosphorus: CalciumPhosphorus | null;
	sodium_potassium: SodiumPotassium | null;
	protein_distribution: MealProteinDistribution[];
	absorbed_protein: AbsorbedProtein | null;
}

export interface DiarySnapshot {
	entry_date: string;
	drv_methodology_version: string;
	scoring_methodology_version: string;
	created_at: string;
	summary: DiarySummary;
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
	goal_adjusted?: boolean;
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
	action: 'add' | 'swap' | 'add_recipe';
	/** null for "add_recipe" — recipe_id/quantity_servings are set instead */
	food_id: number | null;
	food_name: string;
	quantity_g: number | null;
	replaces_food_id: number | null;
	replaces_food_name: string | null;
	before_percent_drv: number;
	after_percent_drv: number;
	improvement: number;
	calories_added: number;
	improvement_per_100kcal: number | null;
	/** null when no price is on file for the food(s) involved — never fabricated */
	estimated_cost: number | null;
	rationale: string;
	recipe_id: number | null;
	quantity_servings: number | null;
}

export interface MealOptimization {
	meal: Meal;
	target_nutrient_key: string;
	target_nutrient_name: string;
	suggestions: OptimizationSuggestion[];
}

export interface PlanOptimization {
	start_date: string;
	end_date: string;
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

export type ClinicianLinkStatus = 'pending' | 'active' | 'revoked';

export interface ClinicianLink {
	id: number;
	clinician_email: string;
	client_email: string;
	client_user_id: number;
	status: ClinicianLinkStatus;
	created_at: string;
	responded_at: string | null;
}

export interface ClinicianNote {
	id: number;
	note_text: string;
	created_at: string;
}

export interface ClinicianClientSummary {
	client_email: string;
	day: DiarySummary;
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
