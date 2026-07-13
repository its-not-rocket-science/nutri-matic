<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import type { NutrientAmount, Recipe, Score } from '$lib/types';

	const recipeId = Number(page.params.id);

	let recipe: Recipe | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);
	let deleting = $state(false);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			recipe = await api.getRecipe(recipeId);
			const [diaas, pdcaas, nutrientResult] = await Promise.allSettled([
				api.scoreRecipe(recipeId, 'diaas'),
				api.scoreRecipe(recipeId, 'pdcaas'),
				api.getRecipeNutrients(recipeId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function handleDelete() {
		if (!confirm(`Delete "${recipe?.name}"?`)) return;
		deleting = true;
		try {
			await api.deleteRecipe(recipeId);
			await goto('/recipes');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			deleting = false;
		}
	}
</script>

<p><a href="/recipes">&larr; Back</a></p>

{#if loading}
	<p>Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if recipe}
	<h1>{recipe.name}</h1>
	<p class="muted">{recipe.servings} servings</p>

	<ul class="ingredients">
		{#each recipe.ingredients as ingredient (ingredient.food_id)}
			<li>
				<a href="/foods/{ingredient.food_id}">{ingredient.food_name}</a>
				<span class="muted">{ingredient.quantity_g}g</span>
			</li>
		{/each}
	</ul>

	{#if diaasScore}<ScoreCard label="DIAAS" score={diaasScore} />{/if}
	{#if pdcaasScore}<ScoreCard label="PDCAAS" score={pdcaasScore} />{/if}

	{#if !diaasScore && !pdcaasScore}
		<p>No digestibility data on this recipe's ingredients — no score can be computed.</p>
	{/if}

	<NutrientBars {nutrients} per="per serving" />

	<p><button type="button" onclick={handleDelete} disabled={deleting}>Delete recipe</button></p>
{/if}

<style>
	.error {
		color: #b00020;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.ingredients {
		list-style: none;
		padding: 0;
		margin-bottom: 1.5rem;
	}
	.ingredients li {
		padding: 0.25rem 0;
	}
	.ingredients .muted {
		margin-left: 0.5rem;
	}
</style>
