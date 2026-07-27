<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FilterBuilder from '$lib/components/FilterBuilder.svelte';
	import PresetControls from '$lib/components/PresetControls.svelte';
	import type { FilterKey, NutrientFilterInput, Recipe, RecipeSummary } from '$lib/types';

	// Public-launch hardening prompt 7: the stock-recipe catalogue no
	// longer fetches every public recipe at once — see docs/stock-recipes.md
	// for the measured before/after (1502 queries/272KB for the whole
	// catalogue vs. 5 queries/~2.6KB for one page). `stockPage` lives in
	// the URL (not just component state) so a specific page is a real
	// deep link and the browser back/forward buttons move between pages,
	// same as any other paginated view in this app.
	const STOCK_PAGE_SIZE = 24;

	let recipes: Recipe[] = $state([]);
	let sharedRecipes: Recipe[] = $state([]);
	let stockRecipes: RecipeSummary[] = $state([]);
	let stockTotal = $state(0);
	let stockLoading = $state(true);
	let stockError: string | null = $state(null);
	let filterKeys: FilterKey[] = $state([]);
	let filters: NutrientFilterInput[] = $state([]);
	let myTags: string[] = $state([]);
	let tagFilter = $state('');
	let filtering = $state(false);
	let showFilters = $state(false);
	let error: string | null = $state(null);
	let loading = $state(true);
	let copyingId: number | null = $state(null);

	const stockPageNum = $derived(Math.max(1, Math.floor(Number(page.url.searchParams.get('stockPage')) || 1)));
	const stockTotalPages = $derived(Math.max(1, Math.ceil(stockTotal / STOCK_PAGE_SIZE)));

	let prevButtonEl: HTMLButtonElement | undefined = $state();
	let nextButtonEl: HTMLButtonElement | undefined = $state();
	let pendingFocus: 'prev' | 'next' | null = null;
	// Caught by PR review: rapid browser back/forward (or repeated clicks)
	// can have two page requests in flight at once; without this, whichever
	// one resolves LAST wins even if it's not the one matching the current
	// URL, overwriting fresher state with stale data. Each load captures its
	// own generation number and only applies its result if it's still the
	// most recent one requested by the time it resolves.
	let stockLoadGeneration = 0;

	async function loadStockPage(pageNum: number) {
		if (!auth.isLoggedIn) return;
		const generation = ++stockLoadGeneration;
		stockLoading = true;
		stockError = null;
		try {
			const result = await api.listPublicRecipes(STOCK_PAGE_SIZE, (pageNum - 1) * STOCK_PAGE_SIZE);
			if (generation !== stockLoadGeneration) return; // superseded by a later page load

			// Caught by PR review: a stale/bookmarked/hand-edited stockPage
			// beyond the real last page (e.g. the catalogue shrank, or
			// ?stockPage=999) would otherwise render an empty list with no
			// in-page way back — Previous alone works but is a long, unobvious
			// slog. Silently correct the URL to the real last page instead of
			// ever showing a request/response mismatch to the user.
			const realTotalPages = Math.max(1, Math.ceil(result.total / STOCK_PAGE_SIZE));
			if (pageNum > realTotalPages) {
				stockTotal = result.total;
				stockLoading = false;
				goToStockPage(realTotalPages, null, true);
				return;
			}

			stockRecipes = result.items;
			stockTotal = result.total;
		} catch (e) {
			if (generation !== stockLoadGeneration) return;
			stockError = e instanceof Error ? e.message : String(e);
		} finally {
			if (generation === stockLoadGeneration) stockLoading = false;
			// Verified directly (browser testing): despite `goto`'s own
			// `keepFocus: true`, re-keying the `{#each stockRecipes}` list
			// (every row's id changes between pages) still drops focus to
			// `<body>` — the button survives as the same DOM node but is
			// briefly detached from the live tree during Svelte's each-block
			// reconciliation, which blurs it without anything re-focusing it
			// afterwards. `tick()` waits for that DOM update to actually
			// apply before refocusing — refocusing synchronously here (before
			// the pending state change is flushed) loses the race and gets
			// clobbered by the same reconciliation right afterwards. Falls
			// back to whichever button is still enabled if the one just
			// clicked became disabled (e.g. Next landed on the last page).
			const target = pendingFocus;
			pendingFocus = null;
			if (target && generation === stockLoadGeneration) {
				await tick();
				if (target === 'prev') (!prevButtonEl?.disabled ? prevButtonEl : nextButtonEl)?.focus();
				else (!nextButtonEl?.disabled ? nextButtonEl : prevButtonEl)?.focus();
			}
		}
	}

	$effect(() => {
		loadStockPage(stockPageNum);
	});

	function goToStockPage(
		pageNum: number, focusTarget: 'prev' | 'next' | null = null, replaceState = false,
	) {
		pendingFocus = focusTarget;
		const url = new URL(page.url);
		if (pageNum <= 1) {
			url.searchParams.delete('stockPage');
		} else {
			url.searchParams.set('stockPage', String(pageNum));
		}
		goto(url, { noScroll: true, keepFocus: true, replaceState });
	}

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
					{#if recipe.dietary_status}
						<span
							class="badge {recipe.dietary_status.status === 'avoid' ? 'badge-estimated' : 'badge-info'}"
							title={recipe.dietary_status.reasons.length > 0
								? recipe.dietary_status.reasons.join(', ')
								: 'Low confidence in an ingredient’s data — not confirmed safe'}
						>
							{recipe.dietary_status.status === 'avoid' ? 'Avoid' : 'Unknown suitability'}
						</span>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	<h2>Stock recipes</h2>
	{#if stockError}
		<p class="error">{stockError}</p>
	{:else if stockLoading && stockRecipes.length === 0}
		<p class="muted">Loading stock recipes…</p>
	{:else if stockTotal === 0}
		<p class="muted">No stock recipes yet.</p>
	{:else}
		<!-- Deliberately stays mounted across a page change (not swapped for a
		     "Loading…" placeholder mid-transition) — the Previous/Next buttons
		     below keep keyboard focus across a page flip this way; briefly
		     showing the outgoing page's rows while the next page loads reads
		     better than losing focus/scroll position on every click. -->
		<ul class="card">
			{#each stockRecipes as recipe (recipe.id)}
				<li>
					<a href="/recipes/{recipe.id}">{recipe.name}</a>
					<span class="muted">
						{recipe.servings} servings
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
		{#if stockTotalPages > 1}
			<nav class="pagination" aria-label="Stock recipes pages">
				<button
					bind:this={prevButtonEl}
					type="button"
					class="btn btn-secondary"
					onclick={() => goToStockPage(stockPageNum - 1, 'prev')}
					disabled={stockPageNum <= 1 || stockLoading}
				>
					&larr; Previous
				</button>
				<span class="muted">Page {stockPageNum} of {stockTotalPages}{stockLoading ? ' · loading…' : ''}</span>
				<button
					bind:this={nextButtonEl}
					type="button"
					class="btn btn-secondary"
					onclick={() => goToStockPage(stockPageNum + 1, 'next')}
					disabled={stockPageNum >= stockTotalPages || stockLoading}
				>
					Next &rarr;
				</button>
			</nav>
		{/if}
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
	.pagination {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin: var(--space-3) 0 var(--space-5);
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
