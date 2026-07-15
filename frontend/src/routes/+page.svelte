<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { DiarySummary, Food, GapSuggestion, MealPlanEntry, ShoppingList } from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	function startOfWeekMonday(d: Date): Date {
		const copy = new Date(d);
		const day = copy.getUTCDay(); // 0 = Sunday
		const diff = day === 0 ? -6 : 1 - day;
		copy.setUTCDate(copy.getUTCDate() + diff);
		return copy;
	}

	let foods: Food[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);

	const todayIso = toIsoDate(new Date());
	let todaySummary: DiarySummary | null = $state(null);
	let upcomingEntries: MealPlanEntry[] = $state([]);
	let weekShoppingList: ShoppingList | null = $state(null);
	let gapSuggestion: GapSuggestion | null = $state(null);
	let dashboardLoading = $state(true);
	let dashboardError: string | null = $state(null);

	const lowestNutrients = $derived.by(() => {
		if (!todaySummary) return [];
		return todaySummary.nutrients
			.filter((n) => n.percent_drv !== null)
			.sort((a, b) => (a.percent_drv ?? 0) - (b.percent_drv ?? 0))
			.slice(0, 5);
	});

	async function loadDashboard() {
		dashboardLoading = true;
		dashboardError = null;
		try {
			const today = new Date();
			const weekStart = startOfWeekMonday(today);
			const weekEnd = new Date(weekStart);
			weekEnd.setUTCDate(weekEnd.getUTCDate() + 6);
			const upcomingEnd = new Date(today);
			upcomingEnd.setUTCDate(upcomingEnd.getUTCDate() + 2);

			const [summary, entries, shoppingList, gaps] = await Promise.all([
				api.getDiaryDay(todayIso),
				api.listMealPlanEntries(todayIso, toIsoDate(upcomingEnd)),
				api.getShoppingList(toIsoDate(weekStart), toIsoDate(weekEnd)),
				api.getGapSuggestions(todayIso)
			]);
			todaySummary = summary;
			upcomingEntries = entries;
			weekShoppingList = shoppingList;
			gapSuggestion = gaps;
		} catch (e) {
			dashboardError = e instanceof Error ? e.message : String(e);
		} finally {
			dashboardLoading = false;
		}
	}

	async function loadFoods() {
		loading = true;
		error = null;
		try {
			foods = (await api.listFoods(10)).items;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	onMount(async () => {
		await loadFoods();

		if (auth.isLoggedIn) {
			await loadDashboard();
		} else {
			dashboardLoading = false;
		}
	});
</script>

<h1>Nutri-Matic</h1>

<div class="quick-actions">
	<a class="btn btn-primary" href="/foods/new">+ Add a food</a>
	<a class="btn btn-secondary" href="/search">Search by nutrient goals</a>
</div>

{#if auth.isLoggedIn}
	<section class="dashboard">
		{#if dashboardError}
			<p class="error">
				{dashboardError}
				<button type="button" class="btn btn-secondary" onclick={loadDashboard}>Retry</button>
			</p>
		{/if}

		{#if dashboardLoading}
			<div class="widgets">
				{#each Array.from({ length: 3 }) as _}
					<div class="widget card skeleton" aria-hidden="true">
						<div class="skeleton-line skeleton-title"></div>
						<div class="skeleton-line"></div>
						<div class="skeleton-line"></div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="widgets">
				<div class="widget card">
					<h3>Today's nutrient gaps</h3>
					{#if lowestNutrients.length === 0}
						<p class="muted">Nothing logged today yet.</p>
					{:else}
						<ul class="widget-list">
							{#each lowestNutrients as n (n.key)}
								<li>
									{n.name}
									<span class="muted">{Math.round(n.percent_drv ?? 0)}% DRV</span>
								</li>
							{/each}
						</ul>
					{/if}
					{#if gapSuggestion && gapSuggestion.foods.length > 0}
						<p class="muted suggestion">
							Try: <a href="/foods/{gapSuggestion.foods[0].food_id}">{gapSuggestion.foods[0].food_name}</a>
							for {gapSuggestion.nutrient_name}
						</p>
					{/if}
					<a class="widget-link" href="/diary">Go to diary &rarr;</a>
				</div>

				<div class="widget card">
					<h3>Upcoming meals</h3>
					{#if upcomingEntries.length === 0}
						<p class="muted">Nothing planned for the next few days.</p>
					{:else}
						<ul class="widget-list">
							{#each upcomingEntries as entry (entry.id)}
								<li>
									{entry.plan_date} &middot; {entry.meal}
									<span class="muted">{entry.food_name ?? entry.recipe_name}</span>
								</li>
							{/each}
						</ul>
					{/if}
					<a class="widget-link" href="/meal-plan">Go to meal plan &rarr;</a>
				</div>

				<div class="widget card">
					<h3>This week's grocery budget</h3>
					{#if weekShoppingList}
						<p class="budget-total">
							Estimated total: <strong>${weekShoppingList.total_cost.toFixed(2)}</strong>
						</p>
						{#if weekShoppingList.items_missing_price > 0}
							<p class="muted">
								{weekShoppingList.items_missing_price} item{weekShoppingList.items_missing_price === 1
									? ''
									: 's'} missing a price
							</p>
						{/if}
					{:else}
						<p class="muted">Nothing planned this week yet.</p>
					{/if}
					<a class="widget-link" href="/meal-plan">View shopping list &rarr;</a>
				</div>
			</div>
		{/if}
	</section>
{/if}

<h2>Foods</h2>

{#if loading}
	<div class="widgets">
		<div class="widget card skeleton" aria-hidden="true">
			<div class="skeleton-line"></div>
			<div class="skeleton-line"></div>
			<div class="skeleton-line"></div>
		</div>
	</div>
{:else if error}
	<p class="error">
		{error}
		<button type="button" class="btn btn-secondary" onclick={loadFoods}>Retry</button>
	</p>
{:else if foods.length === 0}
	<p class="muted">No foods yet. Add one to get a DIAAS/PDCAAS score.</p>
{:else}
	<div class="widget card food-list-card">
		<ul class="widget-list">
			{#each foods as food (food.id)}
				<li>
					<a href="/foods/{food.id}">{food.name}</a>
					<span class="muted">{food.protein_g_per_100g} g protein / 100g</span>
				</li>
			{/each}
		</ul>
	</div>
	<p><a href="/search">Browse all foods &rarr;</a></p>
{/if}

<style>
	.quick-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		margin-bottom: var(--space-6);
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

	.dashboard {
		margin-bottom: var(--space-7);
	}
	.error {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.widgets {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
		gap: var(--space-4);
	}
	.widget {
		display: flex;
		flex-direction: column;
	}
	.widget h3 {
		margin-top: 0;
		margin-bottom: var(--space-3);
	}
	.widget-list {
		margin-bottom: var(--space-3);
	}
	.widget-list li {
		padding: var(--space-1) 0;
		border-bottom: none;
	}
	.suggestion {
		margin-top: 0;
	}
	.budget-total {
		margin-bottom: var(--space-2);
	}
	.widget-link {
		margin-top: auto;
		padding-top: var(--space-2);
		font-weight: var(--font-weight-medium);
	}
	.food-list-card {
		margin-bottom: var(--space-3);
	}

	.skeleton .skeleton-line {
		height: 0.9rem;
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-3);
		background: linear-gradient(
			90deg,
			var(--color-surface-muted) 25%,
			var(--color-border) 50%,
			var(--color-surface-muted) 75%
		);
		background-size: 200% 100%;
		animation: shimmer 1.4s ease-in-out infinite;
	}
	.skeleton .skeleton-title {
		width: 60%;
		height: 1.1rem;
	}
	.skeleton .skeleton-line:last-child {
		margin-bottom: 0;
		width: 80%;
	}

	@keyframes shimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.skeleton .skeleton-line {
			animation: none;
		}
	}
</style>
