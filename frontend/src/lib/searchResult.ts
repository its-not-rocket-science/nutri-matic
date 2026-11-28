import type { Food } from './types.ts';

/** What one food-search result shows, in order: the name (a reviewed
 * canonical's display name when there is one), where the logged row comes
 * from, and the alias or synonym note. The note is how a close analogue
 * ("UK double cream (~48% fat) is richer than US heavy cream (~36%)") is
 * disclosed before the user logs it, so it is never dropped here. */
export interface SearchResultText {
	title: string;
	source: string | null;
	note: string | null;
}

export function searchResultText(food: Food): SearchResultText {
	const note = food.search_note?.trim() || null;
	if (food.canonical_name) {
		return {
			title: food.canonical_name,
			source: `${food.canonical_source ?? 'USDA'}: ${food.name}`,
			note
		};
	}
	return { title: food.name, source: null, note };
}
