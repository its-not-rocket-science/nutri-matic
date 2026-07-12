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
