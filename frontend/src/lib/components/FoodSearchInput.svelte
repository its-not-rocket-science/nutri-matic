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

<label>
	{label}
	<input type="text" bind:value={query} oninput={handleInput} placeholder="Search…" />
</label>
{#if searching}
	<p class="muted">Searching…</p>
{:else if results.length > 0}
	<ul class="search-results">
		{#each results as food (food.id)}
			<li><button type="button" onclick={() => handleSelect(food)}>{food.name}</button></li>
		{/each}
	</ul>
{/if}

<style>
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.search-results {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.search-results button {
		width: 100%;
		text-align: left;
	}
</style>
