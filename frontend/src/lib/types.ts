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
}

export interface NutrientAmount {
	key: string;
	name: string;
	unit: string;
	/** per 100g for a food, per serving for a recipe, per day for a diary summary */
	amount: number;
	adult_drv: number | null;
	percent_drv: number | null;
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
}

export interface RecipeCreate {
	name: string;
	servings: number;
	ingredients: { food_id: number; quantity_g: number }[];
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

export interface DiarySummary {
	entries: DiaryEntry[];
	nutrients: NutrientAmount[];
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
