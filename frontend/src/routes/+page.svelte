<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { formatCurrency } from '$lib/currency';
	import { GOAL_MESSAGES, type Goal } from '$lib/goals';
	import type {
		DiarySummary,
		Food,
		GapSuggestion,
		Meal,
		MealOptimization,
		MealPlanEntry,
		ShoppingList
	} from '$lib/types';

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

	// A reasonable guess at which meal is "current" for the dashboard's
	// optimiser card — the diary itself always lets you pick any meal
	// explicitly, this is just a sensible default so the dashboard doesn't
	// have to ask.
	function guessCurrentMeal(): Meal {
		const hour = new Date().getHours();
		if (hour < 11) return 'breakfast';
		if (hour < 15) return 'lunch';
		if (hour < 20) return 'dinner';
		return 'snack';
	}

	let foods: Food[] = $state([]);
	let demoLoading = $state(false);
	let demoError: string | null = $state(null);

	async function handleTryDemo() {
		demoLoading = true;
		demoError = null;
		try {
			const { access_token } = await api.startDemo();
			auth.setToken(access_token);
			auth.setUser(await api.me());
			await goto('/');
		} catch (e) {
			demoError = e instanceof Error ? e.message : String(e);
			demoLoading = false;
		}
	}
	let error: string | null = $state(null);
	let loading = $state(true);

	const todayIso = toIsoDate(new Date());
	let todaySummary: DiarySummary | null = $state(null);
	let upcomingEntries: MealPlanEntry[] = $state([]);
	let weekShoppingList: ShoppingList | null = $state(null);
	let gapSuggestion: GapSuggestion | null = $state(null);
	let mealOptimization: MealOptimization | null = $state(null);
	let dashboardLoading = $state(true);
	let dashboardError: string | null = $state(null);

	const energy = $derived.by(() => {
		if (!todaySummary) return null;
		return todaySummary.nutrients.find((n) => n.key === 'energy') ?? null;
	});

	const lowestNutrients = $derived.by(() => {
		if (!todaySummary) return [];
		return todaySummary.nutrients
			.filter((n) => n.percent_drv !== null)
			.sort((a, b) => (a.percent_drv ?? 0) - (b.percent_drv ?? 0))
			.slice(0, 3);
	});
	const biggestGap = $derived(lowestNutrients[0] ?? null);
	const topSuggestion = $derived.by(() => {
		if (!mealOptimization) return null;
		return mealOptimization.suggestions[0] ?? null;
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

			const [summary, entries, shoppingList, gaps, optimization] = await Promise.all([
				api.getDiaryDay(todayIso),
				api.listMealPlanEntries(todayIso, toIsoDate(upcomingEnd)),
				api.getShoppingList(toIsoDate(weekStart), toIsoDate(weekEnd)),
				api.getGapSuggestions(todayIso),
				api.getMealOptimization(todayIso, guessCurrentMeal())
			]);
			todaySummary = summary;
			upcomingEntries = entries;
			weekShoppingList = shoppingList;
			gapSuggestion = gaps;
			mealOptimization = optimization;
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
		if (auth.isLoggedIn) {
			await loadFoods();
			await loadDashboard();
		}
	});
</script>

{#if auth.isLoggedIn}
	<h1>Nutri-Matic</h1>

	{#if auth.user?.goal}
		<p class="muted goal-banner">{GOAL_MESSAGES[auth.user.goal as Goal]}</p>
	{/if}

	<div class="quick-actions">
		<a class="btn btn-primary" href="/foods/new">+ Add a food</a>
		<a class="btn btn-secondary" href="/search">Search by nutrient goals</a>
	</div>

	<section class="dashboard">
		{#if dashboardError}
			<p class="error">
				{dashboardError}
				<button type="button" class="btn btn-secondary" onclick={loadDashboard}>Retry</button>
			</p>
		{/if}

		{#if dashboardLoading}
			<div class="widgets">
				{#each Array.from({ length: 4 }) as _}
					<div class="widget card skeleton" aria-hidden="true">
						<div class="skeleton-line skeleton-title"></div>
						<div class="skeleton-line"></div>
						<div class="skeleton-line"></div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="widgets widgets-primary">
				<div class="widget card">
					<p class="label-caps">Today's nutrition</p>
					{#if energy}
						<h3>
							{energy.amount.toFixed(0)} <span class="unit">kcal</span>
						</h3>
						{#if energy.adult_drv !== null}
							<p class="muted">
								of {energy.adult_drv.toFixed(0)} kcal target ({energy.percent_drv?.toFixed(0)}%)
							</p>
						{:else}
							<p class="muted">
								Set weight, height, sex, birth year &amp; activity level in your profile for a target.
							</p>
						{/if}
					{:else}
						<p class="muted">Nothing logged today yet — a blank slate, scientifically speaking.</p>
					{/if}
					<a class="widget-link" href="/diary">Go to diary &rarr;</a>
				</div>

				<div class="widget card">
					<p class="label-caps">Biggest gap</p>
					{#if biggestGap}
						<h3>
							{biggestGap.name} <span class="gap-value">{Math.round(biggestGap.percent_drv ?? 0)}%</span>
						</h3>
						<p class="muted">of today's target — the lowest of anything you've logged</p>
						{#if gapSuggestion && gapSuggestion.foods.length > 0}
							<p class="muted suggestion">
								Try: <a href="/foods/{gapSuggestion.foods[0].food_id}">{gapSuggestion.foods[0].food_name}</a>
								for {gapSuggestion.nutrient_name}
							</p>
						{/if}
					{:else}
						<p class="muted">Log something today to see where the gaps are.</p>
					{/if}
					<a class="widget-link" href="/diary">Go to diary &rarr;</a>
				</div>

				<div class="widget card">
					<p class="label-caps">Highest-impact recommendation</p>
					{#if topSuggestion}
						<h3>+{topSuggestion.improvement.toFixed(1)}pp <span class="unit">{mealOptimization?.target_nutrient_name}</span></h3>
						<p class="proof-suggestion">
							{#if topSuggestion.action === 'swap'}
								Swap <strong>{topSuggestion.replaces_food_name}</strong> &rarr;
								<strong>{topSuggestion.food_name}</strong> ({topSuggestion.quantity_g}g)
							{:else if topSuggestion.action === 'add_recipe'}
								Add 1 serving of <strong>{topSuggestion.food_name}</strong>
							{:else}
								Add <strong>{topSuggestion.quantity_g}g {topSuggestion.food_name}</strong>
							{/if}
						</p>
						<p class="muted">
							{topSuggestion.before_percent_drv.toFixed(0)}% &rarr; {topSuggestion.after_percent_drv.toFixed(0)}%
							{#if topSuggestion.estimated_cost !== null}
								&middot; {topSuggestion.estimated_cost >= 0 ? '+' : ''}{formatCurrency(
									topSuggestion.estimated_cost,
									auth.user?.currency
								)}
							{/if}
						</p>
					{:else}
						<p class="muted">No worthwhile improvement found for {guessCurrentMeal()} yet — log a food or two first.</p>
					{/if}
					<a class="widget-link" href="/diary">Open optimiser &rarr;</a>
				</div>

				<div class="widget card">
					<p class="label-caps">Optimiser</p>
					<h3>Simulate, don't guess</h3>
					<p class="muted">
						Run the full optimiser against any meal — every suggestion is scored against your actual
						diary and pantry prices, not a generic list.
					</p>
					<a class="widget-link btn btn-accent" href="/diary">Open optimiser &rarr;</a>
				</div>
			</div>

			<div class="widgets widgets-secondary">
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
							Estimated total: <strong>{formatCurrency(weekShoppingList.total_cost, auth.user?.currency)}</strong>
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
		<p class="muted">No foods yet — use "Add a food" above to get your first DIAAS/PDCAAS score.</p>
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
{:else}
	<section class="hero">
		<p class="eyebrow">Nutritional Analysis &amp; Optimisation Instrument</p>
		<h1>Know exactly what's in your next meal — down to the limiting amino acid.</h1>
		<p class="hero-sub">
			Nutri-Matic measures protein quality, tracks bioavailable micronutrients, and tells you
			precisely what to eat next to close the gap. Real USDA data, provenance-tracked line by line
			— never guessed, never rounded up.
		</p>
		<div class="hero-cta">
			<a class="btn btn-primary" href="/register">Create a free account</a>
			<button type="button" class="btn btn-accent" disabled={demoLoading} onclick={handleTryDemo}>
				{demoLoading ? 'Setting up…' : 'Try the demo'}
			</button>
			<a class="btn btn-secondary" href="/methodology">See how scoring works</a>
		</div>
		{#if demoError}
			<p class="error">{demoError}</p>
		{/if}
		<p class="muted demo-note">
			The demo drops you straight into a pre-populated account — a couple of days of diary
			entries, a recipe, a meal plan, a weight log — no signup, nothing to fill in first.
		</p>
	</section>

	<section class="proof">
		<h2 class="section-title">See it work</h2>
		<div class="proof-grid">
			<div class="card proof-card">
				<p class="label-caps">Meal analysis</p>
				<h3>
					DIAAS: 123.8%
					<span class="badge badge-measured">measured</span>
				</h3>
				<p class="muted">Chicken breast, cooked · limiting amino acid: valine</p>
				<ul class="proof-bars">
					<li>
						<span>Lysine</span>
						<span class="bar-track"><span class="bar-fill" style="width: 100%"></span></span>
						<span class="proof-value">182%</span>
					</li>
					<li class="limiting">
						<span>Valine</span>
						<span class="bar-track"><span class="bar-fill bar-fill-limiting" style="width: 83%"></span></span>
						<span class="proof-value">124%</span>
					</li>
				</ul>
			</div>

			<div class="card proof-card">
				<p class="label-caps">Nutrient gaps</p>
				<h3>Vitamin D <span class="gap-value">31% of target</span></h3>
				<p class="muted">Today's diary, ranked lowest-to-target first</p>
				<ul class="proof-bars">
					<li class="limiting">
						<span>Vitamin D</span>
						<span class="bar-track"><span class="bar-fill bar-fill-limiting" style="width: 21%"></span></span>
						<span class="proof-value">31%</span>
					</li>
					<li>
						<span>Iron</span>
						<span class="bar-track"><span class="bar-fill" style="width: 64%"></span></span>
						<span class="proof-value">64%</span>
					</li>
				</ul>
			</div>

			<div class="card proof-card">
				<p class="label-caps">Optimisation</p>
				<h3>+27pp for &lt;10&cent;</h3>
				<p class="muted">Simulated against your actual pantry, not a generic suggestion</p>
				<p class="proof-suggestion">
					Add <strong>150g lentils, cooked</strong> to lunch<br />
					<span class="muted">Iron: 64% &rarr; 91% of target (+27pp), +$0.09</span>
				</p>
			</div>
		</div>
	</section>

	<section class="cta-band">
		<h2>Your first score takes under two minutes.</h2>
		<p class="muted">No credit card. No calorie counting. Just the numbers, sourced.</p>
		<a class="btn btn-primary" href="/register">Create a free account</a>
	</section>
{/if}

<style>
	.goal-banner {
		margin: 0 0 var(--space-4);
	}
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
	.widgets-secondary {
		margin-top: var(--space-4);
	}
	.widget {
		display: flex;
		flex-direction: column;
	}
	.widget h3 {
		margin-top: 0;
		margin-bottom: var(--space-3);
		font-size: var(--font-size-lg);
	}
	.widget .unit {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		font-weight: var(--font-weight-normal);
	}
	.widgets-primary .widget-link.btn {
		text-align: center;
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

	/* ---------- landing page (logged-out) ---------- */
	.hero {
		max-width: 44rem;
		padding: var(--space-7) 0 var(--space-6);
	}
	.eyebrow {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-size: var(--font-size-xs);
		color: var(--color-text-subtle);
		margin-bottom: var(--space-3);
	}
	.hero h1 {
		font-size: var(--font-size-3xl);
		text-wrap: balance;
	}
	.hero-sub {
		font-size: var(--font-size-md);
		color: var(--color-text-muted);
		max-width: 38rem;
	}
	.hero-cta {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		margin-top: var(--space-5);
	}
	.demo-note {
		margin-top: var(--space-3);
		max-width: 30rem;
	}

	.section-title {
		margin-bottom: var(--space-5);
	}
	.proof {
		margin: var(--space-7) 0;
	}
	.proof-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
		gap: var(--space-4);
	}
	.proof-card h3 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-bottom: var(--space-1);
	}
	.gap-value {
		font-size: var(--font-size-sm);
		color: var(--color-danger);
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.proof-bars {
		list-style: none;
		margin: var(--space-4) 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.proof-bars li {
		display: grid;
		grid-template-columns: 5rem 1fr 3.5rem;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}
	.proof-bars .bar-track {
		background: var(--color-surface-muted);
		border-radius: var(--radius-sm);
		height: 0.6rem;
		overflow: hidden;
	}
	.proof-bars .bar-fill {
		display: block;
		height: 100%;
		background: var(--color-success);
	}
	.proof-bars .bar-fill-limiting {
		background: var(--color-danger);
	}
	.proof-bars .proof-value {
		text-align: right;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.proof-bars li.limiting span:first-child,
	.proof-bars li.limiting .proof-value {
		color: var(--color-danger);
		font-weight: var(--font-weight-medium);
	}
	.proof-suggestion {
		margin-top: var(--space-4);
		line-height: var(--line-height-normal);
	}

	.cta-band {
		text-align: center;
		max-width: 32rem;
		margin: var(--space-7) auto;
		padding: var(--space-6) var(--space-4);
		border-top: 1px solid var(--color-border);
	}
	.cta-band .btn {
		margin-top: var(--space-4);
	}
</style>
