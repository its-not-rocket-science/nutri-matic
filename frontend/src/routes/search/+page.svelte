<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import FilterBuilder from '$lib/components/FilterBuilder.svelte';
	import PresetControls from '$lib/components/PresetControls.svelte';
	import type { FilterKey, Food, NutrientFilterInput, NutrientSource } from '$lib/types';

	let keys: FilterKey[] = $state([]);
	let filters: NutrientFilterInput[] = $state([]);
	let results: Food[] = $state([]);
	let searched = $state(false);
	let error: string | null = $state(null);
	let loading = $state(true);
	let searching = $state(false);

	// Prompt 6.1 — "best sources of a nutrient" browse, alongside the
	// existing threshold-filter search above rather than replacing it: the
	// two answer different questions ("what meets these constraints?" vs
	// "what has the most of this one nutrient?"). Excludes the score/
	// protein-special filter keys (diaas_score, pdcaas_score,
	// protein_g_per_100g) since those aren't real nutrient_key values the
	// backend's NUTRIENTS lookup recognises.
	const NON_NUTRIENT_KEYS = new Set(['diaas_score', 'pdcaas_score', 'protein_g_per_100g']);
	let nutrientKeys: FilterKey[] = $derived(keys.filter((k) => !NON_NUTRIENT_KEYS.has(k.key)));
	let selectedNutrientKey = $state('');
	let sources: NutrientSource[] = $state([]);
	let sourcesSearched = $state(false);
	let sourcesError: string | null = $state(null);
	let sourcesLoading = $state(false);

	onMount(async () => {
		try {
			const { food } = await api.getFilterKeys();
			keys = food;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function handleSearch(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		searching = true;
		try {
			results = await api.searchFoods({ filters, limit: 100 });
			searched = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			searching = false;
		}
	}

	async function handleSourcesSearch(e: SubmitEvent) {
		e.preventDefault();
		if (!selectedNutrientKey) return;
		sourcesError = null;
		sourcesLoading = true;
		try {
			sources = await api.getNutrientSources(selectedNutrientKey);
			sourcesSearched = true;
		} catch (e) {
			sourcesError = e instanceof Error ? e.message : String(e);
		} finally {
			sourcesLoading = false;
		}
	}
</script>

<h1>Search foods</h1>
<p><a href="/">&larr; Back</a></p>

{#if loading}
	<p class="muted">Calibrating…</p>
{:else}
	<form class="card search-form" onsubmit={handleSearch}>
		<FilterBuilder {keys} bind:filters />
		<PresetControls scope="food" bind:filters />
		<button type="submit" class="btn btn-primary" disabled={searching}>
			{searching ? 'Searching…' : 'Search'}
		</button>
	</form>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if searched}
		<h2>Results <span class="muted">({results.length}{results.length === 100 ? '+' : ''})</span></h2>
		{#if results.length === 0}
			<p class="muted">No foods match those filters — try loosening a threshold or removing one.</p>
		{:else}
			<ul class="card">
				{#each results as food (food.id)}
					<li>
						<a href="/foods/{food.id}">{food.name}</a>
						<span class="muted">{food.protein_g_per_100g} g protein / 100g</span>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}

	<h2>Best sources of a nutrient</h2>
	<form class="card search-form" onsubmit={handleSourcesSearch}>
		<label>
			Nutrient
			<select bind:value={selectedNutrientKey} required>
				<option value="" disabled selected>Choose a nutrient…</option>
				{#each nutrientKeys as key (key.key)}
					<option value={key.key}>{key.label}</option>
				{/each}
			</select>
		</label>
		<button type="submit" class="btn btn-primary" disabled={sourcesLoading || !selectedNutrientKey}>
			{sourcesLoading ? 'Searching…' : 'Find best sources'}
		</button>
	</form>

	{#if sourcesError}
		<p class="error">{sourcesError}</p>
	{/if}

	{#if sourcesSearched}
		{#if sources.length === 0}
			<p class="muted">
				No practical sources found — foods with implausible or hard-to-eat-standalone values for
				this nutrient are filtered out, and your dietary exclusions still apply.
			</p>
		{:else}
			<ul class="card">
				{#each sources as source (`${source.kind}-${source.food_id ?? source.recipe_id}`)}
					<li>
						{#if source.kind === 'food'}
							<a href="/foods/{source.food_id}">{source.name}</a>
						{:else}
							<a href="/recipes/{source.recipe_id}">{source.name}</a>
						{/if}
						<span class="muted">
							{source.amount.toFixed(2)}{source.unit} per {source.per === '100g' ? '100g' : 'serving'}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
{/if}

<style>
	.search-form {
		max-width: 32rem;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin-bottom: var(--space-5);
	}
	ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	li {
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
	}
	li:last-child {
		border-bottom: none;
	}
</style>
