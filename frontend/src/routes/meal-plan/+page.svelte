<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import BarcodeScanner from '$lib/components/BarcodeScanner.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import ImproveThis from '$lib/components/ImproveThis.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import { downloadCsv } from '$lib/csv';
	import { formatCurrency } from '$lib/currency';
	import type {
		Food,
		IngredientSuggestion,
		Meal,
		MealPlanEntry,
		MealPlanTemplate,
		OptimizationSuggestion,
		PlanOptimization,
		Recipe,
		RecipeSuggestion,
		ShoppingList,
		SubstitutionSuggestion
	} from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	function startOfWeek(d: Date): Date {
		const copy = new Date(d);
		const day = copy.getUTCDay(); // 0 = Sunday
		const diff = day === 0 ? -6 : 1 - day; // shift back to Monday
		copy.setUTCDate(copy.getUTCDate() + diff);
		return copy;
	}

	const MEALS: Meal[] = ['breakfast', 'lunch', 'dinner', 'snack'];
	const WEEKDAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

	let weekStart = $state(startOfWeek(new Date()));
	const weekDates = $derived.by(() => {
		const dates: string[] = [];
		for (let i = 0; i < 7; i++) {
			const d = new Date(weekStart);
			d.setUTCDate(d.getUTCDate() + i);
			dates.push(toIsoDate(d));
		}
		return dates;
	});

	let entries: MealPlanEntry[] = $state([]);
	let allRecipes: Recipe[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);

	let itemType: 'food' | 'recipe' = $state('food');
	let search = $state('');
	let selectedFood: Food | null = $state(null);
	let selectedRecipe: Recipe | null = $state(null);
	let quantity = $state<number | null>(100);
	// svelte(state_referenced_locally): intentional — this seeds the initial
	// value only; shiftWeek() below explicitly re-syncs planDate whenever
	// the visible week actually changes.
	let planDate = $state(weekDates[0]);
	let meal: Meal = $state('breakfast');
	let adding = $state(false);
	let markingId: number | null = $state(null);
	let showScanner = $state(false);
	let scanning = $state(false);

	let showShoppingList = $state(false);
	let shoppingList: ShoppingList | null = $state(null);
	let loadingShoppingList = $state(false);

	let planOptimization: PlanOptimization | null = $state(null);
	let optimizingPlan = $state(false);
	let optimizeBudget: number | null = $state(null);
	let applyingPlanSuggestionKey: string | null = $state(null);

	let templates: MealPlanTemplate[] = $state([]);
	let templateName = $state('');
	let savingTemplate = $state(false);
	let applyingTemplateId: number | null = $state(null);
	let deletingTemplateId: number | null = $state(null);

	function addDays(iso: string, days: number): string {
		const d = new Date(iso + 'T00:00:00Z');
		d.setUTCDate(d.getUTCDate() + days);
		return toIsoDate(d);
	}

	const searchResults = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (q.length < 2) return [];
		return allRecipes.filter((f) => f.name.toLowerCase().includes(q)).slice(0, 15);
	});

	async function loadWeek() {
		loading = true;
		error = null;
		try {
			entries = await api.listMealPlanEntries(weekDates[0], weekDates[6]);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
		if (showShoppingList) await loadShoppingList();
	}

	async function loadShoppingList() {
		loadingShoppingList = true;
		try {
			shoppingList = await api.getShoppingList(weekDates[0], weekDates[6]);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingShoppingList = false;
		}
	}

	async function loadTemplates() {
		try {
			templates = await api.listMealPlanTemplates();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			allRecipes = await api.listRecipes();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		await Promise.all([loadWeek(), loadTemplates()]);
	});

	function shiftWeek(weeks: number) {
		const d = new Date(weekStart);
		d.setUTCDate(d.getUTCDate() + weeks * 7);
		weekStart = d;
		planDate = weekDates[0];
		loadWeek();
	}

	function selectItem(item: Recipe) {
		selectedRecipe = item;
		search = '';
	}

	async function toggleShoppingList() {
		showShoppingList = !showShoppingList;
		if (showShoppingList && !shoppingList) await loadShoppingList();
	}

	async function handleOptimizePlan() {
		error = null;
		optimizingPlan = true;
		try {
			planOptimization = await api.getPlanOptimization(weekDates[0], weekDates[6], optimizeBudget);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			optimizingPlan = false;
		}
	}

	function planSuggestionKey(s: OptimizationSuggestion): string {
		return `${s.action}-${s.food_id ?? `recipe-${s.recipe_id}`}`;
	}

	async function handleApplyPlanSuggestion(s: OptimizationSuggestion) {
		error = null;
		applyingPlanSuggestionKey = planSuggestionKey(s);
		try {
			if (s.action === 'swap' && s.replaces_food_id !== null) {
				const replaced = entries.find((e) => e.food_id === s.replaces_food_id);
				if (replaced) await api.deleteMealPlanEntry(replaced.id);
			}
			// "add"/"add_recipe" suggestions have no single natural day/meal at
			// the plan level — they're added wherever the entry form is
			// currently set, same date/meal picker used to log entries by hand
			if (s.action === 'add_recipe') {
				await api.addMealPlanEntry({
					plan_date: planDate,
					meal,
					recipe_id: s.recipe_id,
					quantity_servings: s.quantity_servings
				});
			} else {
				await api.addMealPlanEntry({
					plan_date: planDate,
					meal,
					food_id: s.food_id,
					quantity_g: s.quantity_g
				});
			}
			await loadWeek();
			planOptimization = await api.getPlanOptimization(weekDates[0], weekDates[6], optimizeBudget);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			applyingPlanSuggestionKey = null;
		}
	}

	// "Improve this…" nutrient-gap recommendations (prompt 10). A plan-level
	// or day-level addition has no single natural meal to land in — same
	// ambiguity "Optimize this plan" already has above — so it's applied
	// wherever the "Add planned entry" form's day/meal selectors currently
	// point, exactly like handleApplyPlanSuggestion does. A meal-scoped
	// panel instead targets that specific day+meal directly.
	async function applyIngredientSuggestion(targetDate: string, targetMeal: Meal, s: IngredientSuggestion) {
		await api.addMealPlanEntry({ plan_date: targetDate, meal: targetMeal, food_id: s.food_id, quantity_g: s.quantity_g });
		shoppingList = null;
		await loadWeek();
	}

	async function applyRecipeSuggestion(targetDate: string, targetMeal: Meal, s: RecipeSuggestion) {
		await api.addMealPlanEntry({
			plan_date: targetDate,
			meal: targetMeal,
			recipe_id: s.recipe_id,
			quantity_servings: s.suggested_servings
		});
		shoppingList = null;
		await loadWeek();
	}

	async function applySubstitutionSuggestion(entryId: number, s: SubstitutionSuggestion) {
		const replaced = entries.find((e) => e.id === entryId);
		await api.deleteMealPlanEntry(entryId);
		await api.addMealPlanEntry({
			plan_date: replaced?.plan_date ?? planDate,
			meal: replaced?.meal ?? meal,
			recipe_id: s.replacement_recipe_id,
			quantity_servings: s.replacement_servings
		});
		shoppingList = null;
		await loadWeek();
	}

	async function handleAdd(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		if (quantity === null || quantity <= 0) {
			error = 'Enter a positive quantity.';
			return;
		}
		if (itemType === 'food' && !selectedFood) {
			error = 'Search for and select a food.';
			return;
		}
		if (itemType === 'recipe' && !selectedRecipe) {
			error = 'Search for and select a recipe.';
			return;
		}

		adding = true;
		try {
			if (itemType === 'food' && selectedFood) {
				await api.addMealPlanEntry({
					plan_date: planDate,
					meal,
					food_id: selectedFood.id,
					quantity_g: quantity
				});
			} else if (selectedRecipe) {
				await api.addMealPlanEntry({
					plan_date: planDate,
					meal,
					recipe_id: selectedRecipe.id,
					quantity_servings: quantity
				});
			}
			selectedFood = null;
			selectedRecipe = null;
			quantity = 100;
			shoppingList = null;
			await loadWeek();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			adding = false;
		}
	}

	async function handleScan(barcode: string) {
		showScanner = false;
		error = null;
		scanning = true;
		try {
			const food = await api.getFoodByBarcode(barcode);
			itemType = 'food';
			selectedFood = food;
			selectedRecipe = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			scanning = false;
		}
	}

	async function handleDelete(id: number) {
		error = null;
		try {
			await api.deleteMealPlanEntry(id);
			shoppingList = null;
			await loadWeek();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleMarkEaten(id: number) {
		error = null;
		markingId = id;
		try {
			await api.markMealPlanEntryEaten(id);
			shoppingList = null;
			await loadWeek();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			markingId = null;
		}
	}

	async function handleSaveTemplate(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		if (!templateName.trim()) return;
		savingTemplate = true;
		try {
			await api.createMealPlanTemplate(templateName.trim(), weekDates[0], weekDates[6]);
			templateName = '';
			await loadTemplates();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			savingTemplate = false;
		}
	}

	async function handleApplyTemplate(templateId: number, startDate: string) {
		error = null;
		applyingTemplateId = templateId;
		try {
			await api.applyMealPlanTemplate(templateId, startDate);
			shoppingList = null;
			await loadWeek();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			applyingTemplateId = null;
		}
	}

	async function handleDeleteTemplate(templateId: number) {
		error = null;
		deletingTemplateId = templateId;
		try {
			await api.deleteMealPlanTemplate(templateId);
			await loadTemplates();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			deletingTemplateId = null;
		}
	}

	function handleDownloadCsv() {
		if (!shoppingList) return;
		const rows: (string | number | null)[][] = [['Food', 'Quantity (g)', 'Price per 100g', 'Estimated cost']];
		for (const item of shoppingList.items) {
			rows.push([item.food_name, item.quantity_g, item.price_per_100g, item.estimated_cost]);
		}
		rows.push([]);
		rows.push(['Estimated total', '', '', shoppingList.total_cost]);
		downloadCsv(`shopping-list-${weekDates[0]}-to-${weekDates[6]}.csv`, rows);
	}
</script>

<h1>Meal plan</h1>
<p class="no-print"><a href="/">&larr; Back</a></p>

<div class="date-nav no-print">
	<button type="button" onclick={() => shiftWeek(-1)}>&larr; Prev week</button>
	<span>{weekDates[0]} &ndash; {weekDates[6]}</span>
	<button type="button" onclick={() => shiftWeek(1)}>Next week &rarr;</button>
</div>

{#if error}
	<p class="error">{error}</p>
{/if}

{#if loading}
	<p class="muted">Calibrating…</p>
{:else}
	<ImproveThis
		title="Improve this plan"
		scope={{ kind: 'range', startDate: weekDates[0], endDate: weekDates[6] }}
		targetDescription={`${planDate}'s ${meal}`}
		onApplyIngredient={(s) => applyIngredientSuggestion(planDate, meal, s)}
		onApplyRecipe={(s) => applyRecipeSuggestion(planDate, meal, s)}
	/>

	{#each weekDates as d, i (d)}
		{@const dayEntries = entries.filter((e) => e.plan_date === d)}
		<section class="no-print">
			<h3>{WEEKDAY_LABELS[i]} <span class="muted">{d}</span></h3>
			{#if dayEntries.length === 0}
				<p class="muted">Nothing planned — use "Add planned entry" below to fill this day in.</p>
			{:else}
				<ImproveThis
					title="Improve this day"
					scope={{ kind: 'day', entryDate: d, source: 'meal_plan' }}
					targetDescription={`${WEEKDAY_LABELS[i]}'s ${meal}`}
					onApplyIngredient={(s) => applyIngredientSuggestion(d, meal, s)}
					onApplyRecipe={(s) => applyRecipeSuggestion(d, meal, s)}
				/>
				{#each MEALS as m (m)}
					{@const mealEntries = dayEntries.filter((e) => e.meal === m)}
					{#if mealEntries.length > 0}
						<div class="meal-group">
							<span class="meal-label">{m}</span>
							<ul class="entries">
								{#each mealEntries as entry (entry.id)}
									<li>
										{#if entry.food_id}
											<a href="/foods/{entry.food_id}">{entry.food_name}</a>
											<span class="muted">{entry.quantity_g}g</span>
										{:else}
											<a href="/recipes/{entry.recipe_id}">{entry.recipe_name}</a>
											<span class="muted">{entry.quantity_servings} serving(s)</span>
										{/if}
										<button
											type="button"
											onclick={() => handleMarkEaten(entry.id)}
											disabled={markingId === entry.id}
										>
											{markingId === entry.id ? 'Marking…' : 'Mark eaten'}
										</button>
										<button type="button" onclick={() => handleDelete(entry.id)}>Remove</button>
									</li>
								{/each}
							</ul>
							<ImproveThis
								title="Improve this meal"
								scope={{ kind: 'day', entryDate: d, meal: m, source: 'meal_plan' }}
								targetDescription={`${WEEKDAY_LABELS[i]}'s ${m}`}
								substitutionEntryId={mealEntries.find((e) => e.recipe_id !== null)?.id ?? null}
								substitutionSource="meal_plan"
								onApplyIngredient={(s) => applyIngredientSuggestion(d, m, s)}
								onApplyRecipe={(s) => applyRecipeSuggestion(d, m, s)}
								onApplySubstitution={(s) =>
									applySubstitutionSuggestion(mealEntries.find((e) => e.recipe_id !== null)?.id ?? -1, s)}
							/>
						</div>
					{/if}
				{/each}
			{/if}
		</section>
	{/each}

	<form onsubmit={handleAdd} class="no-print">
		<h3>Add planned entry</h3>
		<label>
			Day
			<select bind:value={planDate}>
				{#each weekDates as d, i (d)}
					<option value={d}>{WEEKDAY_LABELS[i]} ({d})</option>
				{/each}
			</select>
		</label>

		<label>
			Type
			<select
				bind:value={itemType}
				onchange={() => {
					search = '';
					selectedFood = null;
					selectedRecipe = null;
				}}
			>
				<option value="food">Food</option>
				<option value="recipe">Recipe</option>
			</select>
		</label>

		{#if itemType === 'food'}
			<button type="button" onclick={() => (showScanner = true)} disabled={scanning}>
				{scanning ? 'Looking up…' : 'Scan barcode'}
			</button>
		{/if}

		{#if (itemType === 'food' && selectedFood) || (itemType === 'recipe' && selectedRecipe)}
			<p>
				Selected: <strong>{itemType === 'food' ? selectedFood?.name : selectedRecipe?.name}</strong>
				<button
					type="button"
					onclick={() => {
						selectedFood = null;
						selectedRecipe = null;
					}}>Change</button
				>
			</p>
		{:else if itemType === 'food'}
			<FoodSearchInput onSelect={(food) => (selectedFood = food)} label="Search foods" />
		{:else}
			<label>
				Search recipes
				<input type="text" bind:value={search} placeholder="Search…" />
			</label>
			{#if searchResults.length > 0}
				<ul class="search-results">
					{#each searchResults as item (item.id)}
						<li><button type="button" onclick={() => selectItem(item)}>{item.name}</button></li>
					{/each}
				</ul>
			{/if}
		{/if}

		<label>
			{itemType === 'food' ? 'Quantity (g)' : 'Servings'}
			<input type="number" step="any" min="0" bind:value={quantity} required />
		</label>

		<label>
			Meal
			<select bind:value={meal}>
				{#each MEALS as m (m)}
					<option value={m}>{m}</option>
				{/each}
			</select>
		</label>

		<button type="submit" disabled={adding}>{adding ? 'Adding…' : 'Add to plan'}</button>
	</form>

	<section class="templates no-print">
		<h3>Templates</h3>
		<form onsubmit={handleSaveTemplate} class="template-save">
			<input
				type="text"
				bind:value={templateName}
				placeholder="Template name (e.g. Typical week)"
				aria-label="Template name"
				required
			/>
			<button type="submit" disabled={savingTemplate}>
				{savingTemplate ? 'Saving…' : 'Save this week as template'}
			</button>
		</form>

		{#if templates.length === 0}
			<p class="muted">No templates saved yet — plan a week you like, then save it above to reuse it.</p>
		{:else}
			<ul class="entries">
				{#each templates as t (t.id)}
					<li>
						<span>{t.name}</span>
						<span class="muted">{t.entry_count} entr{t.entry_count === 1 ? 'y' : 'ies'}</span>
						<button
							type="button"
							onclick={() => handleApplyTemplate(t.id, weekDates[0])}
							disabled={applyingTemplateId === t.id}
						>
							{applyingTemplateId === t.id ? 'Applying…' : 'Apply to this week'}
						</button>
						<button
							type="button"
							onclick={() => handleApplyTemplate(t.id, addDays(weekDates[0], 7))}
							disabled={applyingTemplateId === t.id}
						>
							Apply to next week
						</button>
						<button
							type="button"
							onclick={() => handleDeleteTemplate(t.id)}
							disabled={deletingTemplateId === t.id}
						>
							{deletingTemplateId === t.id ? 'Deleting…' : 'Delete'}
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="shopping-list">
		<button type="button" class="no-print" onclick={toggleShoppingList}>
			{showShoppingList ? 'Hide shopping list' : 'Show shopping list for this week'}
		</button>
		{#if showShoppingList}
			{#if loadingShoppingList}
				<p class="muted">Calibrating…</p>
			{:else if shoppingList}
				<p class="range-heading">Shopping list, {weekDates[0]} to {weekDates[6]}</p>
				<div class="export-actions no-print">
					<PrintButton />
					<button type="button" onclick={handleDownloadCsv}>Download CSV</button>
				</div>
				{#if shoppingList.items.length === 0}
					<p class="muted">Nothing planned this week yet — the shopping list fills in once you add entries above.</p>
				{:else}
					<ul class="entries">
						{#each shoppingList.items as item (item.food_id)}
							<li>
								<a href="/foods/{item.food_id}">{item.food_name}</a>
								<span class="muted">{Math.round(item.quantity_g)}g</span>
								{#if item.estimated_cost !== null}
									<span class="cost">{formatCurrency(item.estimated_cost, auth.user?.currency)}</span>
								{:else}
									<span class="muted no-price">no price set</span>
								{/if}
							</li>
						{/each}
					</ul>
					<p class="total">
						Estimated total: <strong>{formatCurrency(shoppingList.total_cost, auth.user?.currency)}</strong>
						{#if shoppingList.items_missing_price > 0}
							<span class="muted">
								({shoppingList.items_missing_price} item{shoppingList.items_missing_price === 1 ? '' : 's'}
								missing a price — <a href="/food-prices">set prices</a>)
							</span>
						{/if}
					</p>
				{/if}
			{/if}
		{/if}
	</section>

	<section class="plan-optimize">
		<label class="optimize-budget">
			Optional budget for suggestions
			<input type="number" min="0" step="0.01" placeholder="no limit" bind:value={optimizeBudget} />
		</label>
		<button type="button" class="no-print" onclick={handleOptimizePlan} disabled={optimizingPlan}>
			{optimizingPlan ? 'Optimizing…' : 'Optimize this plan'}
		</button>

		{#if planOptimization !== null}
			{#if planOptimization.suggestions.length === 0}
				<p class="muted">No worthwhile improvements found for this week's plan.</p>
			{:else}
				<p class="muted">
					Targeting: {planOptimization.target_nutrient_name} (lowest %DRV across the week) — "add"
					suggestions go to the date/meal currently selected above ({planDate}, {meal}).
				</p>
				<ul class="entries">
					{#each planOptimization.suggestions as s (planSuggestionKey(s))}
						<li>
							{#if s.action === 'swap'}
								<span>Swap {s.replaces_food_name} &rarr; {s.food_name} ({s.quantity_g}g)</span>
							{:else if s.action === 'add_recipe'}
								<span>Add 1 serving of <a href="/recipes/{s.recipe_id}">{s.food_name}</a></span>
							{:else}
								<span>Add {s.quantity_g}g {s.food_name}</span>
							{/if}
							<span class="muted">
								{s.before_percent_drv.toFixed(0)}% &rarr; {s.after_percent_drv.toFixed(0)}%
								({s.improvement >= 0 ? '+' : ''}{s.improvement.toFixed(1)}pp{s.calories_added
									? `, +${s.calories_added.toFixed(0)}kcal`
									: ''}{s.estimated_cost !== null
									? `, ${s.estimated_cost >= 0 ? '+' : ''}${formatCurrency(s.estimated_cost, auth.user?.currency)}`
									: ''})
							</span>
							<button
								type="button"
								class="no-print"
								onclick={() => handleApplyPlanSuggestion(s)}
								disabled={applyingPlanSuggestionKey === planSuggestionKey(s)}
							>
								{applyingPlanSuggestionKey === planSuggestionKey(s) ? 'Applying…' : 'Apply'}
							</button>
							<p class="rationale">{s.rationale}</p>
						</li>
					{/each}
				</ul>
			{/if}
		{/if}
	</section>
{/if}

{#if showScanner}
	<BarcodeScanner onScan={handleScan} onClose={() => (showScanner = false)} />
{/if}

<style>
	.date-nav {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 1.5rem;
	}
	.error {
		color: var(--color-danger);
	}
	.muted {
		color: var(--color-text-muted);
		font-size: 0.9em;
		margin: 0 0.5rem;
	}
	section {
		margin-bottom: 1.25rem;
	}
	.meal-group {
		margin: 0.25rem 0 0.5rem;
	}
	.meal-label {
		text-transform: capitalize;
		font-weight: 600;
		font-size: 0.85em;
		color: var(--color-text-muted);
	}
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: 0.25rem 0;
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.cost {
		margin-left: auto;
		font-weight: 600;
	}
	.no-price {
		margin-left: auto;
	}
	.total {
		margin-top: 0.75rem;
	}
	.plan-optimize {
		margin-top: 1.5rem;
	}
	.rationale {
		margin: 0.15rem 0 0.5rem;
		font-size: 0.85em;
		color: var(--color-text-muted);
	}
	.optimize-budget {
		display: block;
		margin-bottom: 0.5rem;
		font-size: 0.9em;
	}
	.optimize-budget input {
		margin-left: 0.4rem;
		width: 6rem;
	}
	.range-heading {
		display: none;
	}
	.export-actions {
		display: flex;
		gap: 0.5rem;
		margin: 0.5rem 0;
	}
	@media print {
		.no-print {
			display: none !important;
		}
		.range-heading {
			display: block;
			font-weight: 600;
		}
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 28rem;
		margin: 1.5rem 0;
		padding: 1rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
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
	.template-save {
		display: flex;
		flex-direction: row;
		gap: 0.5rem;
		max-width: none;
		margin: 0.5rem 0 1rem;
		padding: 0;
		border: none;
	}
	.template-save input {
		flex: 1;
	}
	.templates .entries li {
		flex-wrap: wrap;
	}
</style>
