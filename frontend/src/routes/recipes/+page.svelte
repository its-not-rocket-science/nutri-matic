<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FilterBuilder from '$lib/components/FilterBuilder.svelte';
	import PresetControls from '$lib/components/PresetControls.svelte';
	import type { FilterKey, NutrientFilterInput, Recipe } from '$lib/types';

	let recipes: Recipe[] = $state([]);
	let sharedRecipes: Recipe[] = $state([]);
	let filterKeys: FilterKey[] = $state([]);
	let filters: NutrientFilterInput[] = $state([]);
	let filtering = $state(false);
	let showFilters = $state(false);
	let error: string | null = $state(null);
	let loading = $state(true);
	let copyingId: number | null = $state(null);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			const [recipeList, shared, keys] = await Promise.all([
				api.listRecipes(),
				api.listSharedWithMe(),
				api.getFilterKeys()
			]);
			recipes = recipeList;
			sharedRecipes = shared;
			filterKeys = keys.recipe;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function runSearch() {
		error = null;
		filtering = true;
		try {
			recipes = filters.length > 0 ? await api.searchRecipes({ filters }) : await api.listRecipes();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			filtering = false;
		}
	}

	function handleFilter(e: SubmitEvent) {
		e.preventDefault();
		runSearch();
	}

	function clearFilters() {
		filters = [];
		runSearch();
	}

	async function handleCopy(recipeId: number) {
		error = null;
		copyingId = recipeId;
		try {
			const copy = await api.copyRecipe(recipeId);
			await goto(`/recipes/${copy.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			copyingId = null;
		}
	}
</script>

<h1>Recipes</h1>
<p><a href="/">&larr; Back</a></p>
<p><a href="/recipes/new">+ New recipe</a></p>

{#if loading}
	<p>Loading…</p>
{:else}
	<p>
		<button type="button" onclick={() => (showFilters = !showFilters)}>
			{showFilters ? 'Hide filters' : 'Filter by nutrient goals'}
		</button>
	</p>

	{#if showFilters}
		<form onsubmit={handleFilter}>
			<FilterBuilder keys={filterKeys} bind:filters />
			<PresetControls scope="recipe" bind:filters />
			<div class="actions">
				<button type="submit" disabled={filtering}>{filtering ? 'Filtering…' : 'Apply filters'}</button>
				<button type="button" onclick={clearFilters} disabled={filtering}>Clear</button>
			</div>
		</form>
	{/if}

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<h2>My recipes</h2>
	{#if recipes.length === 0}
		<p>No recipes match.</p>
	{:else}
		<ul>
			{#each recipes as recipe (recipe.id)}
				<li>
					<a href="/recipes/{recipe.id}">{recipe.name}</a>
					<span class="muted">
						{recipe.ingredients.length} ingredients · {recipe.servings} servings
						{#if recipe.rating_count > 0}
							· ★ {recipe.average_rating?.toFixed(1)} ({recipe.rating_count})
						{/if}
					</span>
				</li>
			{/each}
		</ul>
	{/if}

	<h2>Shared with me</h2>
	{#if sharedRecipes.length === 0}
		<p>No recipes have been shared with you.</p>
	{:else}
		<ul>
			{#each sharedRecipes as recipe (recipe.id)}
				<li>
					<a href="/recipes/{recipe.id}">{recipe.name}</a>
					<span class="muted">
						by {recipe.owner_email} · {recipe.servings} servings
						{#if recipe.rating_count > 0}
							· ★ {recipe.average_rating?.toFixed(1)} ({recipe.rating_count})
						{/if}
					</span>
					<button
						type="button"
						onclick={() => handleCopy(recipe.id)}
						disabled={copyingId === recipe.id}
					>
						{copyingId === recipe.id ? 'Copying…' : 'Copy to my recipes'}
					</button>
				</li>
			{/each}
		</ul>
	{/if}
{/if}

<style>
	form {
		max-width: 32rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		margin: 1rem 0 1.5rem;
		padding: 1rem;
		border: 1px solid #eee;
		border-radius: 4px;
	}
	.actions {
		display: flex;
		gap: 0.5rem;
	}
	.muted {
		color: #666;
		margin-left: 0.5rem;
		font-size: 0.9em;
	}
	.error {
		color: #b00020;
	}
	ul {
		list-style: none;
		padding: 0;
	}
	li {
		padding: 0.5rem 0;
		border-bottom: 1px solid #eee;
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
</style>
