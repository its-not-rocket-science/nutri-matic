<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import FilterBuilder from '$lib/components/FilterBuilder.svelte';
	import PresetControls from '$lib/components/PresetControls.svelte';
	import type { FilterKey, Food, NutrientFilterInput } from '$lib/types';

	let keys: FilterKey[] = $state([]);
	let filters: NutrientFilterInput[] = $state([]);
	let results: Food[] = $state([]);
	let searched = $state(false);
	let error: string | null = $state(null);
	let loading = $state(true);
	let searching = $state(false);

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
