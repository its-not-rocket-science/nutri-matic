<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { Food } from '$lib/types';

	interface IngredientRow {
		food: Food;
		quantity_g: number;
	}

	let name = $state('');
	let servings = $state<number | null>(1);
	let rows: IngredientRow[] = $state([]);
	let allFoods: Food[] = $state([]);
	let search = $state('');
	let error: string | null = $state(null);
	let submitting = $state(false);
	let loadingFoods = $state(true);

	const searchResults = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (q.length < 2) return [];
		return allFoods.filter((f) => f.name.toLowerCase().includes(q)).slice(0, 15);
	});

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			allFoods = await api.listFoods();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingFoods = false;
		}
	});

	function addIngredient(food: Food) {
		if (!rows.some((r) => r.food.id === food.id)) {
			rows = [...rows, { food, quantity_g: 100 }];
		}
		search = '';
	}

	function removeIngredient(foodId: number) {
		rows = rows.filter((r) => r.food.id !== foodId);
	}

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = null;

		if (!name || servings === null || servings <= 0) {
			error = 'Name and a positive number of servings are required.';
			return;
		}
		if (rows.length === 0) {
			error = 'Add at least one ingredient.';
			return;
		}

		submitting = true;
		try {
			const recipe = await api.createRecipe({
				name,
				servings,
				ingredients: rows.map((r) => ({ food_id: r.food.id, quantity_g: r.quantity_g }))
			});
			await goto(`/recipes/${recipe.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			submitting = false;
		}
	}
</script>

<h1>New recipe</h1>
<p><a href="/recipes">&larr; Back</a></p>

<form onsubmit={handleSubmit}>
	<label>
		Name
		<input type="text" bind:value={name} required />
	</label>
	<label>
		Servings
		<input type="number" step="any" min="0" bind:value={servings} required />
	</label>

	<fieldset>
		<legend>Ingredients</legend>

		{#if rows.length > 0}
			<ul class="ingredients">
				{#each rows as row (row.food.id)}
					<li>
						<span class="food-name">{row.food.name}</span>
						<input type="number" step="any" min="0" bind:value={row.quantity_g} />
						<span class="muted">g</span>
						<button type="button" onclick={() => removeIngredient(row.food.id)}>Remove</button>
					</li>
				{/each}
			</ul>
		{/if}

		<label>
			Add ingredient
			<input type="text" bind:value={search} placeholder="Search foods…" disabled={loadingFoods} />
		</label>
		{#if searchResults.length > 0}
			<ul class="search-results">
				{#each searchResults as food (food.id)}
					<li>
						<button type="button" onclick={() => addIngredient(food)}>{food.name}</button>
					</li>
				{/each}
			</ul>
		{/if}
	</fieldset>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<button type="submit" disabled={submitting}>{submitting ? 'Saving…' : 'Save recipe'}</button>
</form>

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 32rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	fieldset {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.ingredients,
	.search-results {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.ingredients li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.food-name {
		flex: 1;
	}
	.ingredients input[type='number'] {
		width: 5rem;
	}
	.search-results button {
		width: 100%;
		text-align: left;
	}
	.muted {
		color: #666;
	}
	.error {
		color: #b00020;
	}
</style>
