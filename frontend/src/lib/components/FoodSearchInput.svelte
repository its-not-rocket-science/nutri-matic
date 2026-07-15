<script lang="ts">
	import { api } from '$lib/api';
	import type { Food } from '$lib/types';

	let {
		onSelect,
		label = 'Search foods',
		exclude
	}: { onSelect: (food: Food) => void; label?: string; exclude?: (food: Food) => boolean } = $props();

	let query = $state('');
	let results: Food[] = $state([]);
	let searching = $state(false);
	let debounceHandle: ReturnType<typeof setTimeout> | undefined;

	function handleInput() {
		clearTimeout(debounceHandle);
		const q = query.trim();
		if (q.length < 2) {
			results = [];
			searching = false;
			return;
		}
		searching = true;
		debounceHandle = setTimeout(async () => {
			try {
				const found = await api.searchFoodsByName(q);
				results = exclude ? found.filter((f) => !exclude(f)) : found;
			} catch {
				results = [];
			} finally {
				searching = false;
			}
		}, 250);
	}

	function handleSelect(food: Food) {
		onSelect(food);
		query = '';
		results = [];
	}
</script>

<div class="field">
	<label for="food-search-input">{label}</label>
	<input id="food-search-input" type="text" bind:value={query} oninput={handleInput} placeholder="Search…" />
</div>
{#if searching}
	<p class="muted">Searching…</p>
{:else if results.length > 0}
	<ul class="search-results card">
		{#each results as food (food.id)}
			<li><button type="button" class="btn-plain" onclick={() => handleSelect(food)}>{food.name}</button></li>
		{/each}
	</ul>
{/if}

<style>
	.search-results {
		list-style: none;
		padding: var(--space-2);
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.btn-plain {
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		padding: var(--space-2) var(--space-2);
		border-radius: var(--radius-sm);
	}
	.btn-plain:hover {
		background: var(--color-surface-muted);
	}
</style>
