import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { api } from './api';

describe('api.listFoods', () => {
	beforeEach(() => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => ({
				ok: true,
				status: 200,
				json: async () => ({ items: [], total: 0, limit: 10, offset: 0, has_more: false })
			}))
		);
	});

	it('defaults to a small bounded page instead of the full catalog', async () => {
		await api.listFoods();
		const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
		expect(url).toContain('limit=10');
		expect(url).toContain('offset=0');
	});

	it('passes through explicit limit/offset', async () => {
		await api.listFoods(50, 100);
		const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
		expect(url).toContain('limit=50');
		expect(url).toContain('offset=100');
	});
});

describe('api.getIngredientSuggestions', () => {
	beforeEach(() => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ suggestions: [] }) }))
		);
	});

	function calledUrl() {
		return (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
	}

	it('builds a day scope with entry_date, meal and source', async () => {
		await api.getIngredientSuggestions({ kind: 'day', entryDate: '2026-01-01', meal: 'lunch', source: 'meal_plan' });
		const url = calledUrl();
		expect(url).toContain('entry_date=2026-01-01');
		expect(url).toContain('meal=lunch');
		expect(url).toContain('source=meal_plan');
		expect(url).not.toContain('start_date');
		expect(url).not.toContain('recipe_id');
	});

	it('builds a multi-day range scope forced to source=meal_plan', async () => {
		await api.getIngredientSuggestions({ kind: 'range', startDate: '2026-01-01', endDate: '2026-01-07' });
		const url = calledUrl();
		expect(url).toContain('start_date=2026-01-01');
		expect(url).toContain('end_date=2026-01-07');
		expect(url).toContain('source=meal_plan');
		expect(url).not.toContain('entry_date');
	});

	it('builds a recipe scope with recipe_id and servings', async () => {
		await api.getIngredientSuggestions({ kind: 'recipe', recipeId: 42, servings: 2 });
		const url = calledUrl();
		expect(url).toContain('recipe_id=42');
		expect(url).toContain('servings=2');
		expect(url).not.toContain('entry_date');
	});

	it('joins priority nutrients with commas and passes through energy/count caps', async () => {
		await api.getIngredientSuggestions(
			{ kind: 'day', entryDate: '2026-01-01' },
			{ maxAdditionalEnergy: 200, maxSuggestions: 3, priorityNutrients: ['iron', 'folate'] }
		);
		const url = calledUrl();
		expect(url).toContain('max_additional_energy=200');
		expect(url).toContain('max_suggestions=3');
		expect(url).toContain('priority_nutrients=iron%2Cfolate');
	});
});

describe('api.getRecipeSuggestions', () => {
	beforeEach(() => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ suggestions: [] }) }))
		);
	});

	it('passes a goal through to the query string', async () => {
		await api.getRecipeSuggestions({ kind: 'day', entryDate: '2026-01-01' }, { goal: 'fibre' });
		const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
		expect(url).toContain('goal=fibre');
	});
});

describe('api.getSubstitutionSuggestions', () => {
	beforeEach(() => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => ({
				ok: true,
				status: 200,
				json: async () => ({ current_recipe_id: 1, current_recipe_name: 'x', suggestions: [] })
			}))
		);
	});

	it('defaults to source=diary and passes entry_id', async () => {
		await api.getSubstitutionSuggestions(7);
		const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
		expect(url).toContain('entry_id=7');
		expect(url).toContain('source=diary');
	});
});
