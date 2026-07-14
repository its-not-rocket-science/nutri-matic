<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import BarcodeScanner from '$lib/components/BarcodeScanner.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import { downloadCsv } from '$lib/csv';
	import type { DiaryMealTemplate, DiarySummary, Food, Meal, QuickAdd, QuickAddItem, Recipe } from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	let date = $state(toIsoDate(new Date()));
	let summary: DiarySummary | null = $state(null);
	let allFoods: Food[] = $state([]);
	let allRecipes: Recipe[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);

	let itemType: 'food' | 'recipe' = $state('food');
	let search = $state('');
	let selectedFood: Food | null = $state(null);
	let selectedRecipe: Recipe | null = $state(null);
	let quantity = $state<number | null>(100);
	let meal: Meal = $state('breakfast');
	let adding = $state(false);
	let showScanner = $state(false);
	let scanning = $state(false);

	let templates: DiaryMealTemplate[] = $state([]);
	let applyingTemplateId: number | null = $state(null);
	let deletingTemplateId: number | null = $state(null);

	let quickAdd: QuickAdd | null = $state(null);
	let quickAddTab: 'recent' | 'frequent' = $state('recent');
	let addingQuickAddKey: string | null = $state(null);

	function quickAddKey(item: QuickAddItem): string {
		return item.food_id !== null ? `f${item.food_id}` : `r${item.recipe_id}`;
	}

	const searchResults = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (q.length < 2) return [];
		const source = itemType === 'food' ? allFoods : allRecipes;
		return source.filter((f) => f.name.toLowerCase().includes(q)).slice(0, 15);
	});

	async function loadDay() {
		loading = true;
		error = null;
		try {
			summary = await api.getDiaryDay(date);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function loadTemplates() {
		try {
			templates = await api.listDiaryMealTemplates();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function loadQuickAdd() {
		try {
			quickAdd = await api.getQuickAdd();
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
			[allFoods, allRecipes] = await Promise.all([api.listFoods(), api.listRecipes()]);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		await Promise.all([loadDay(), loadTemplates(), loadQuickAdd()]);
	});

	function shiftDay(days: number) {
		const d = new Date(date);
		d.setUTCDate(d.getUTCDate() + days);
		date = toIsoDate(d);
		loadDay();
	}

	function selectItem(item: Food | Recipe) {
		if (itemType === 'food') selectedFood = item as Food;
		else selectedRecipe = item as Recipe;
		search = '';
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
				await api.addDiaryEntry({ entry_date: date, meal, food_id: selectedFood.id, quantity_g: quantity });
			} else if (selectedRecipe) {
				await api.addDiaryEntry({
					entry_date: date,
					meal,
					recipe_id: selectedRecipe.id,
					quantity_servings: quantity
				});
			}
			selectedFood = null;
			selectedRecipe = null;
			quantity = 100;
			await loadDay();
			await loadQuickAdd();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			adding = false;
		}
	}

	async function handleQuickAdd(item: QuickAddItem) {
		error = null;
		const key = quickAddKey(item);
		addingQuickAddKey = key;
		try {
			if (item.food_id !== null) {
				await api.addDiaryEntry({
					entry_date: date,
					meal,
					food_id: item.food_id,
					quantity_g: item.quantity_g
				});
			} else if (item.recipe_id !== null) {
				await api.addDiaryEntry({
					entry_date: date,
					meal,
					recipe_id: item.recipe_id,
					quantity_servings: item.quantity_servings
				});
			}
			await loadDay();
			await loadQuickAdd();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			addingQuickAddKey = null;
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
		try {
			await api.deleteDiaryEntry(id);
			await loadDay();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleSaveAsTemplate(m: Meal) {
		const defaultName = `${m[0].toUpperCase()}${m.slice(1)}`;
		const name = prompt('Template name:', defaultName);
		if (!name || !name.trim()) return;
		error = null;
		try {
			await api.createDiaryMealTemplate(name.trim(), date, m);
			await loadTemplates();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleApplyTemplate(templateId: number) {
		error = null;
		applyingTemplateId = templateId;
		try {
			await api.applyDiaryMealTemplate(templateId, date, meal);
			await loadDay();
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
			await api.deleteDiaryMealTemplate(templateId);
			await loadTemplates();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			deletingTemplateId = null;
		}
	}

	const MEALS: Meal[] = ['breakfast', 'lunch', 'dinner', 'snack'];

	function handleDownloadCsv() {
		if (!summary) return;
		const rows: (string | number | null)[][] = [['Entries'], ['Meal', 'Food/Recipe', 'Quantity']];
		for (const entry of summary.entries) {
			rows.push([
				entry.meal,
				entry.food_name ?? entry.recipe_name,
				entry.food_id ? `${entry.quantity_g}g` : `${entry.quantity_servings} serving(s)`
			]);
		}
		rows.push([]);
		rows.push(['Nutrients']);
		rows.push(['Name', 'Amount', 'Unit', 'DRV', '% DRV']);
		for (const n of summary.nutrients) {
			rows.push([n.name, n.amount, n.unit, n.adult_drv, n.percent_drv]);
		}
		downloadCsv(`diary-${date}.csv`, rows);
	}
</script>

<h1>Diary</h1>
<p class="no-print"><a href="/">&larr; Back</a></p>

<div class="date-nav no-print">
	<button type="button" onclick={() => shiftDay(-1)}>&larr; Prev</button>
	<input type="date" bind:value={date} onchange={loadDay} />
	<button type="button" onclick={() => shiftDay(1)}>Next &rarr;</button>
</div>

<p class="date-heading">{date}</p>

{#if summary}
	<div class="export-actions no-print">
		<PrintButton />
		<button type="button" onclick={handleDownloadCsv}>Download CSV</button>
	</div>
{/if}

{#if error}
	<p class="error">{error}</p>
{/if}

{#if loading}
	<p>Loading…</p>
{:else if summary}
	{#each MEALS as m (m)}
		{@const mealEntries = summary.entries.filter((e) => e.meal === m)}
		{#if mealEntries.length > 0}
			<section>
				<h3>
					{m}
					<button type="button" class="no-print save-template-btn" onclick={() => handleSaveAsTemplate(m)}>
						Save as template
					</button>
				</h3>
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
							<button type="button" class="no-print" onclick={() => handleDelete(entry.id)}>Remove</button>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/each}

	{#if summary.entries.length === 0}
		<p>Nothing logged for this day yet.</p>
	{/if}

	{#if quickAdd && (quickAdd.recent.length > 0 || quickAdd.frequent.length > 0)}
		<section class="quick-add no-print">
			<h3>Quick add</h3>
			<div class="quick-add-tabs">
				<button type="button" class:active={quickAddTab === 'recent'} onclick={() => (quickAddTab = 'recent')}>
					Recent
				</button>
				<button
					type="button"
					class:active={quickAddTab === 'frequent'}
					onclick={() => (quickAddTab = 'frequent')}
				>
					Frequent
				</button>
			</div>
			<ul class="entries">
				{#each quickAddTab === 'recent' ? quickAdd.recent : quickAdd.frequent as item (quickAddKey(item))}
					<li>
						<span>{item.food_name ?? item.recipe_name}</span>
						<span class="muted">
							{item.food_id !== null ? `${item.quantity_g}g` : `${item.quantity_servings} serving(s)`}
						</span>
						<button
							type="button"
							onclick={() => handleQuickAdd(item)}
							disabled={addingQuickAddKey === quickAddKey(item)}
						>
							{addingQuickAddKey === quickAddKey(item) ? 'Adding…' : `Add as ${meal}`}
						</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	<form onsubmit={handleAdd} class="no-print">
		<h3>Add entry</h3>
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
		{:else}
			<label>
				Search {itemType}s
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

		<button type="submit" disabled={adding}>{adding ? 'Adding…' : 'Add to diary'}</button>
	</form>

	<section class="meal-templates no-print">
		<h3>Meal templates</h3>
		{#if templates.length === 0}
			<p class="muted">No meal templates saved yet — log a meal above, then use "Save as template".</p>
		{:else}
			<ul class="entries">
				{#each templates as t (t.id)}
					<li>
						<span>{t.name}</span>
						<span class="muted">{t.item_count} item{t.item_count === 1 ? '' : 's'}</span>
						<button
							type="button"
							onclick={() => handleApplyTemplate(t.id)}
							disabled={applyingTemplateId === t.id}
						>
							{applyingTemplateId === t.id ? 'Logging…' : `Log as ${meal}`}
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

	<NutrientBars nutrients={summary.nutrients} per="per day" />

	{#if summary.iron_bioavailability.length > 0 || summary.calcium_phosphorus}
		<section class="bioavailability">
			<h3>Bioavailability estimate</h3>
			<p class="muted">
				A simplified estimate, not lab-measured — see below for what it does and doesn't account for.
			</p>

			{#each summary.iron_bioavailability as meal (meal.meal)}
				<div class="iron-meal">
					<strong class="meal-label">{meal.meal}</strong>
					<span>
						{meal.absorbed_total_mg.toFixed(2)}mg iron absorbed (of {(meal.heme_iron_mg + meal.non_heme_iron_mg).toFixed(2)}mg total)
					</span>
					<span class="muted">
						{meal.non_heme_absorption_tier === 'enhanced' ? 'enhanced' : 'baseline'} non-haem absorption
						{#if meal.iron_split_source === 'estimated'}(estimated haem/non-haem split){/if}
					</span>
				</div>
			{/each}

			{#if summary.calcium_phosphorus}
				<div class="calcium-phosphorus">
					<strong>Calcium:phosphorus ratio</strong>
					<span>{summary.calcium_phosphorus.ratio.toFixed(2)}:1</span>
					<p class="muted">{summary.calcium_phosphorus.guidance}</p>
				</div>
			{/if}

			<details>
				<summary>Methodology</summary>
				<p class="muted">
					Haem iron is assumed to be 25% absorbed, non-haem 5% (baseline) or 10% (if the meal has
					&ge;25mg vitamin C or any meat/fish/poultry) — a simplified two-tier model built from
					published constants (Monsen 1978/1982; FAO 2004 Human Vitamin and Mineral Requirements),
					not a full continuous algorithm. Phytates, tannins, and oxalates aren't modelled — FDC
					doesn't track them. The calcium:phosphorus ratio references ESPGHAN's traditional 1:1–2:1
					guidance; newer research in older adults found no link between this ratio and bone
					density, so treat it as informational.
					<a href="/methodology#bioavailability">Full citations &rarr;</a>
				</p>
			</details>
		</section>
	{/if}
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
	.date-heading {
		display: none;
	}
	.export-actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}
	@media print {
		.no-print {
			display: none !important;
		}
		.date-heading {
			display: block;
			font-weight: 600;
		}
	}
	.error {
		color: #b00020;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
		margin: 0 0.5rem;
	}
	.bioavailability {
		margin-top: 1.5rem;
		padding: 1rem;
		border: 1px solid #eee;
		border-radius: 4px;
	}
	.iron-meal {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		padding: 0.4rem 0;
	}
	.meal-label {
		text-transform: capitalize;
	}
	.calcium-phosphorus {
		margin-top: 0.75rem;
		padding-top: 0.75rem;
		border-top: 1px solid #eee;
	}
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: 0.25rem 0;
	}
	.meal-templates .entries li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.save-template-btn {
		margin-left: 0.75rem;
		font-size: 0.75em;
	}
	.quick-add {
		margin: 1rem 0;
		padding: 1rem;
		border: 1px solid #eee;
		border-radius: 4px;
		max-width: 28rem;
	}
	.quick-add-tabs {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}
	.quick-add-tabs button.active {
		font-weight: 600;
		text-decoration: underline;
	}
	.quick-add .entries li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.quick-add .entries li span:first-child {
		flex: 1;
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
</style>
