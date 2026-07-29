<script lang="ts">
	import { api } from '$lib/api';
	import type { RecipeSearchResult } from '$lib/types';

	let { onSelect, label = 'Search recipes' }: { onSelect: (recipe: RecipeSearchResult) => void; label?: string } =
		$props();

	let query = $state('');
	let results: RecipeSearchResult[] = $state([]);
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
				results = await api.searchRecipesByName(q);
			} catch {
				results = [];
			} finally {
				searching = false;
			}
		}, 250);
	}

	function handleSelect(recipe: RecipeSearchResult) {
		onSelect(recipe);
		query = '';
		results = [];
	}

	function scopeLabel(recipe: RecipeSearchResult): string | null {
		if (recipe.is_owner) return null;
		if (recipe.is_shared) return 'Shared with you';
		return 'Public';
	}
</script>

<div class="field">
	<label for="recipe-search-input">{label}</label>
	<input id="recipe-search-input" type="text" bind:value={query} oninput={handleInput} placeholder="Search…" />
</div>
{#if searching}
	<p class="muted">Searching…</p>
{:else if results.length > 0}
	<ul class="search-results card">
		{#each results as recipe (recipe.id)}
			<li>
				<button type="button" class="btn-plain" onclick={() => handleSelect(recipe)}>
					<span>{recipe.name}</span>
					{#if scopeLabel(recipe)}
						<span class="badge badge-info">{scopeLabel(recipe)}</span>
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
	.btn-plain:hover {
		background: var(--color-surface-muted);
	}
</style>
