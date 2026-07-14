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

	onMount(async () => {
		try {
			foods = await api.listFoods();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}

		if (auth.isLoggedIn) {
			await loadDashboard();
		} else {
			dashboardLoading = false;
		}
	});
</script>

<h1>Nutri-Matic</h1>

{#if auth.isLoggedIn}
	<section class="dashboard">
		{#if dashboardError}
			<p class="error">{dashboardError}</p>
		{/if}

		{#if dashboardLoading}
			<p>Loading your dashboard…</p>
		{:else}
			<div class="widgets">
				<div class="widget">
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
						<p class="muted">
							Try: <a href="/foods/{gapSuggestion.foods[0].food_id}">{gapSuggestion.foods[0].food_name}</a>
							for {gapSuggestion.nutrient_name}
						</p>
					{/if}
					<a href="/diary">Go to diary &rarr;</a>
				</div>

				<div class="widget">
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
					<a href="/meal-plan">Go to meal plan &rarr;</a>
				</div>

				<div class="widget">
					<h3>This week's grocery budget</h3>
					{#if weekShoppingList}
						<p>
							Estimated total: <strong>${weekShoppingList.total_cost.toFixed(2)}</strong>
						</p>
						{#if weekShoppingList.items_missing_price > 0}
							<p class="muted">
								{weekShoppingList.items_missing_price} item{weekShoppingList.items_missing_price === 1
									? ''
									: 's'} missing a price
							</p>
						{/if}
					{/if}
					<a href="/meal-plan">View shopping list &rarr;</a>
				</div>
			</div>
		{/if}
	</section>
{/if}

<p><a href="/foods/new">+ Add a food</a> · <a href="/search">Search by nutrient goals</a></p>

{#if loading}
	<p>Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if foods.length === 0}
	<p>No foods yet. Add one to get a DIAAS/PDCAAS score.</p>
{:else}
	<ul>
		{#each foods as food (food.id)}
			<li>
				<a href="/foods/{food.id}">{food.name}</a>
				<span class="muted">{food.protein_g_per_100g} g protein / 100g</span>
			</li>
		{/each}
	</ul>
{/if}

<style>
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
	}
	.dashboard {
		margin-bottom: 2rem;
	}
	.widgets {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
	}
	.widget {
		flex: 1 1 14rem;
		padding: 1rem;
		border: 1px solid #eee;
		border-radius: 4px;
	}
	.widget h3 {
		margin-top: 0;
	}
	.widget-list {
		list-style: none;
		padding: 0;
		margin: 0 0 0.5rem;
	}
	.widget-list li {
		border-bottom: none;
		padding: 0.2rem 0;
		display: flex;
		justify-content: space-between;
		gap: 0.5rem;
	}
</style>
