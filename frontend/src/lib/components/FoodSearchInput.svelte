<script lang="ts">
	import { api } from '#lib/api.ts';
	import type { Food } from '#lib/types.ts';
	import { searchResultText } from '#lib/searchResult.ts';

	let {
		onSelect,
		label = 'Search foods',
		exclude,
		hint = null
	}: {
		onSelect: (food: Food) => void;
		label?: string;
		exclude?: (food: Food) => boolean;
		// shown above the input, and the input is focused, e.g. after a
		// barcode miss sends the user here to search by name instead
		hint?: string | null;
	} = $props();

	let input: HTMLInputElement | undefined = $state();

	$effect(() => {
		if (hint) input?.focus();
	});

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
	{#if hint}
		<p class="search-hint" role="status">{hint}</p>
	{/if}
	<input
		id="food-search-input"
		type="text"
		bind:this={input}
		bind:value={query}
		oninput={handleInput}
		placeholder="Search…"
	/>
</div>
{#if searching}
	<p class="muted">Searching…</p>
{:else if results.length > 0}
	<ul class="search-results card">
		{#each results as food (food.id)}
			{@const text = searchResultText(food)}
			<li>
				<button type="button" class="btn-plain" onclick={() => handleSelect(food)}>
					<span class="result-name">
						<span>{text.title}</span>
						{#if text.source}
							<span class="muted search-source">{text.source}</span>
						{/if}
						{#if text.note}
							<span class="muted search-note">{text.note}</span>
						{/if}
					</span>
					{#if food.preparation_label}
						<span class="badge badge-info" title="Preparation state, read from the food's name">
							{food.preparation_label}
						</span>
					{/if}
					{#if food.dietary_status}
						<span
							class="badge {food.dietary_status.status === 'avoid' ? 'badge-estimated' : 'badge-info'}"
							title={food.dietary_status.reasons.length > 0
								? food.dietary_status.reasons.join(', ')
								: 'No name match against your dietary constraints, but low confidence in this food’s data — not confirmed safe'}
						>
							{food.dietary_status.status === 'avoid' ? 'Avoid' : 'Unknown suitability'}
						</span>
					{/if}
				</button>
			</li>
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
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		text-align: left;
		background: none;
		border: none;
		padding: var(--space-2) var(--space-2);
		border-radius: var(--radius-sm);
	}
	.search-hint {
		margin: 0 0 var(--space-2);
	}
	.result-name {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-width: 0;
	}
	.search-note,
	.search-source {
		font-size: 0.85em;
	}
	.btn-plain:hover {
		background: var(--color-surface-muted);
	}
</style>
