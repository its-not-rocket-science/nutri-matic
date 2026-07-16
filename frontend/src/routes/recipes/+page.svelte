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
	let myTags: string[] = $state([]);
	let tagFilter = $state('');
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
			const [recipeList, shared, keys, tags] = await Promise.all([
				api.listRecipes(),
				api.listSharedWithMe(),
				api.getFilterKeys(),
				api.listMyTags()
			]);
			recipes = recipeList;
			sharedRecipes = shared;
			filterKeys = keys.recipe;
			myTags = tags;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function handleTagFilter() {
		error = null;
		try {
			recipes = await api.listRecipes(tagFilter || undefined);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

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
<p><a href="/recipes/new">+ New recipe</a> · <a href="/collections">Collections</a></p>

{#if loading}
	<p class="muted">Calibrating…</p>
{:else}
	<p>
		<button type="button" class="btn btn-secondary" onclick={() => (showFilters = !showFilters)}>
			{showFilters ? 'Hide filters' : 'Filter by nutrient goals'}
		</button>
	</p>

	{#if showFilters}
		<form class="card filter-form" onsubmit={handleFilter}>
			<FilterBuilder keys={filterKeys} bind:filters />
			<PresetControls scope="recipe" bind:filters />
			<div class="actions">
				<button type="submit" class="btn btn-primary" disabled={filtering}>
					{filtering ? 'Filtering…' : 'Apply filters'}
				</button>
				<button type="button" class="btn btn-secondary" onclick={clearFilters} disabled={filtering}>
					Clear
				</button>
			</div>
		</form>
	{/if}

	{#if myTags.length > 0}
		<div class="field tag-filter">
			<label for="tag-filter">Filter by tag</label>
			<select id="tag-filter" bind:value={tagFilter} onchange={handleTagFilter}>
				<option value="">All</option>
				{#each myTags as tag (tag)}
					<option value={tag}>{tag}</option>
				{/each}
			</select>
		</div>
	{/if}

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<h2>My recipes</h2>
	{#if recipes.length === 0}
		<p class="muted">
			{filters.length > 0 || tagFilter
				? 'No recipes match — try clearing a filter.'
				: 'No recipes yet.'}
			<a href="/recipes/new">Create a new recipe</a>.
		</p>
	{:else}
		<ul class="card">
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
		<p class="muted">No recipes have been shared with you.</p>
	{:else}
		<ul class="card">
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
						class="btn btn-secondary"
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
	.filter-form {
		max-width: 32rem;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin: var(--space-4) 0 var(--space-5);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
	}
	.tag-filter {
		max-width: 16rem;
	}
	ul {
		list-style: none;
		padding: 0;
		margin: 0 0 var(--space-5);
	}
	li {
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	li:last-child {
		border-bottom: none;
	}
</style>
