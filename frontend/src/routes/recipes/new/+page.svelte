<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import type { Food } from '$lib/types';

	interface IngredientRow {
		food: Food;
		quantity_g: number;
	}

	let name = $state('');
	let servings = $state<number | null>(1);
	let sourceUrl = $state('');
	let method = $state('');
	let rows: IngredientRow[] = $state([]);
	let error: string | null = $state(null);
	let submitting = $state(false);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
		}
	});

	function addIngredient(food: Food) {
		if (!rows.some((r) => r.food.id === food.id)) {
			rows = [...rows, { food, quantity_g: 100 }];
		}
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
		const trimmedUrl = sourceUrl.trim();
		if (trimmedUrl && !trimmedUrl.startsWith('http://') && !trimmedUrl.startsWith('https://')) {
			error = 'Source URL must start with http:// or https://';
			return;
		}

		submitting = true;
		try {
			const recipe = await api.createRecipe({
				name,
				servings,
				ingredients: rows.map((r) => ({ food_id: r.food.id, quantity_g: r.quantity_g })),
				source_url: trimmedUrl || null,
				method: method.trim() || null
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

<form class="card recipe-form" onsubmit={handleSubmit}>
	<div class="field">
		<label for="recipe-name">Name</label>
		<input id="recipe-name" type="text" bind:value={name} required />
	</div>
	<div class="field">
		<label for="recipe-servings">Servings</label>
		<input id="recipe-servings" type="number" step="any" min="0" bind:value={servings} required />
	</div>
	<div class="field">
		<label for="recipe-source-url">Source URL (optional)</label>
		<input
			id="recipe-source-url"
			type="url"
			bind:value={sourceUrl}
			placeholder="https://…"
		/>
	</div>

	<details class="method-details">
		<summary>Method (optional)</summary>
		<div class="field">
			<label for="recipe-method">Cooking instructions</label>
			<textarea id="recipe-method" bind:value={method} rows="6" placeholder="Optional step-by-step method…"
			></textarea>
		</div>
	</details>

	<fieldset>
		<legend>Ingredients</legend>

		{#if rows.length > 0}
			<ul class="ingredients">
				{#each rows as row (row.food.id)}
					<li>
						<span class="food-name">{row.food.name}</span>
						<input
							type="number"
							step="any"
							min="0"
							bind:value={row.quantity_g}
							aria-label="Quantity in grams for {row.food.name}"
						/>
						<span class="muted">g</span>
						<button type="button" class="btn btn-danger" onclick={() => removeIngredient(row.food.id)}>
							Remove
						</button>
					</li>
				{/each}
			</ul>
		{/if}

		<FoodSearchInput
			onSelect={addIngredient}
			label="Add ingredient"
			exclude={(food) => rows.some((r) => r.food.id === food.id)}
		/>
	</fieldset>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<button type="submit" class="btn btn-primary" disabled={submitting}>
		{submitting ? 'Saving…' : 'Save recipe'}
	</button>
</form>

<style>
	.recipe-form {
		max-width: 32rem;
	}
	fieldset {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-4);
		margin: 0 0 var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.method-details {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-3) var(--space-4);
		margin: 0 0 var(--space-4);
	}
	.method-details summary {
		cursor: pointer;
		font-weight: var(--font-weight-medium);
	}
	.method-details .field {
		margin-top: var(--space-3);
	}
	.method-details textarea {
		font-family: inherit;
		resize: vertical;
	}
	legend {
		font-size: var(--font-size-sm);
		font-weight: var(--font-weight-medium);
		padding: 0 var(--space-2);
	}
	.ingredients {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.ingredients li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.food-name {
		flex: 1;
	}
	.ingredients input[type='number'] {
		width: 5rem;
	}
</style>
