<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import BarcodeScanner from '$lib/components/BarcodeScanner.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import { downloadCsv } from '$lib/csv';
	import type { Food, Meal, MealPlanEntry, MealPlanTemplate, Recipe, ShoppingList } from '$lib/types';

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
	let planDate = $state(weekDates[0]);
	let meal: Meal = $state('breakfast');
	let adding = $state(false);
	let markingId: number | null = $state(null);
	let showScanner = $state(false);
	let scanning = $state(false);

	let showShoppingList = $state(false);
	let shoppingList: ShoppingList | null = $state(null);
	let loadingShoppingList = $state(false);

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
	<p>Loading…</p>
{:else}
	{#each weekDates as d, i (d)}
		{@const dayEntries = entries.filter((e) => e.plan_date === d)}
		<section class="no-print">
			<h3>{WEEKDAY_LABELS[i]} <span class="muted">{d}</span></h3>
			{#if dayEntries.length === 0}
				<p class="muted">Nothing planned.</p>
			{:else}
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
			<input type="text" bind:value={templateName} placeholder="Template name (e.g. Typical week)" required />
			<button type="submit" disabled={savingTemplate}>
				{savingTemplate ? 'Saving…' : 'Save this week as template'}
			</button>
		</form>

		{#if templates.length === 0}
			<p class="muted">No templates saved yet.</p>
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
				<p>Loading…</p>
			{:else if shoppingList}
				<p class="range-heading">Shopping list, {weekDates[0]} to {weekDates[6]}</p>
				<div class="export-actions no-print">
					<PrintButton />
					<button type="button" onclick={handleDownloadCsv}>Download CSV</button>
				</div>
				{#if shoppingList.items.length === 0}
					<p class="muted">Nothing planned this week.</p>
				{:else}
					<ul class="entries">
						{#each shoppingList.items as item (item.food_id)}
							<li>
								<a href="/foods/{item.food_id}">{item.food_name}</a>
								<span class="muted">{Math.round(item.quantity_g)}g</span>
								{#if item.estimated_cost !== null}
									<span class="cost">${item.estimated_cost.toFixed(2)}</span>
								{:else}
									<span class="muted no-price">no price set</span>
								{/if}
							</li>
						{/each}
					</ul>
					<p class="total">
						Estimated total: <strong>${shoppingList.total_cost.toFixed(2)}</strong>
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
		color: #b00020;
	}
	.muted {
		color: #666;
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
		color: #444;
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
		border: 1px solid #eee;
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
