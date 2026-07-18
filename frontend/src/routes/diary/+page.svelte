<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import BarcodeScanner from '$lib/components/BarcodeScanner.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import { downloadCsv } from '$lib/csv';
	import { formatCurrency } from '$lib/currency';
	import type {
		DiaryMealTemplate,
		DiarySnapshot,
		DiarySummary,
		Food,
		GapSuggestion,
		Meal,
		MealOptimization,
		OptimizationSuggestion,
		QuickAdd,
		QuickAddItem,
		Recipe
	} from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	function addDays(iso: string, days: number): string {
		const d = new Date(iso + 'T00:00:00Z');
		d.setUTCDate(d.getUTCDate() + days);
		return toIsoDate(d);
	}

	let date = $state(toIsoDate(new Date()));
	let summary: DiarySummary | null = $state(null);
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

	let copyTargetDate = $state(addDays(toIsoDate(new Date()), 1));
	let copying = $state(false);
	let copySuccessMessage: string | null = $state(null);

	let quickAdd: QuickAdd | null = $state(null);
	let quickAddTab: 'recent' | 'frequent' = $state('recent');
	let addingQuickAddKey: string | null = $state(null);

	let gapSuggestion: GapSuggestion | null = $state(null);
	let snapshot: DiarySnapshot | null = $state(null);
	let takingSnapshot = $state(false);
	let addingGapFoodId: number | null = $state(null);

	let mealOptimizations: Partial<Record<Meal, MealOptimization | null>> = $state({});
	let optimizingMeal: Meal | null = $state(null);
	let applyingSuggestionKey: string | null = $state(null);
	let optimizeBudget: number | null = $state(null);

	function quickAddKey(item: QuickAddItem): string {
		return item.food_id !== null ? `f${item.food_id}` : `r${item.recipe_id}`;
	}

	// Surfaced inline next to the raw "Iron" bar so the gap between logged
	// and actually-absorbed iron isn't only visible in the separate
	// Bioavailability section further down the page.
	const totalAbsorbedIronMg = $derived.by(() => {
		if (!summary || summary.iron_bioavailability.length === 0) return null;
		return summary.iron_bioavailability.reduce((sum, m) => sum + m.absorbed_total_mg, 0);
	});

	const searchResults = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (q.length < 2) return [];
		return allRecipes.filter((f) => f.name.toLowerCase().includes(q)).slice(0, 15);
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

	async function loadGapSuggestions() {
		try {
			gapSuggestion = await api.getGapSuggestions(date);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function loadSnapshot() {
		try {
			snapshot = await api.getDiarySnapshot(date);
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
		await Promise.all([loadDay(), loadTemplates(), loadQuickAdd(), loadGapSuggestions(), loadSnapshot()]);
	});

	function shiftDay(days: number) {
		const d = new Date(date);
		d.setUTCDate(d.getUTCDate() + days);
		date = toIsoDate(d);
		copyTargetDate = addDays(date, 1);
		loadDay();
		loadGapSuggestions();
		loadSnapshot();
	}

	function selectItem(item: Recipe) {
		selectedRecipe = item;
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
			await loadGapSuggestions();
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
			await loadGapSuggestions();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			addingQuickAddKey = null;
		}
	}

	async function handleAddGapFood(foodId: number) {
		error = null;
		addingGapFoodId = foodId;
		try {
			await api.addDiaryEntry({ entry_date: date, meal, food_id: foodId, quantity_g: 100 });
			await loadDay();
			await loadQuickAdd();
			await loadGapSuggestions();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			addingGapFoodId = null;
		}
	}

	async function handleOptimizeMeal(m: Meal) {
		error = null;
		optimizingMeal = m;
		try {
			mealOptimizations[m] = await api.getMealOptimization(date, m, optimizeBudget);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			optimizingMeal = null;
		}
	}

	function suggestionKey(m: Meal, s: OptimizationSuggestion): string {
		return `${m}-${s.action}-${s.food_id ?? `recipe-${s.recipe_id}`}`;
	}

	async function handleApplySuggestion(m: Meal, s: OptimizationSuggestion) {
		error = null;
		applyingSuggestionKey = suggestionKey(m, s);
		try {
			if (s.action === 'swap' && s.replaces_food_id !== null) {
				const replaced = summary?.entries.find((e) => e.meal === m && e.food_id === s.replaces_food_id);
				if (replaced) await api.deleteDiaryEntry(replaced.id);
			}
			if (s.action === 'add_recipe') {
				await api.addDiaryEntry({
					entry_date: date,
					meal: m,
					recipe_id: s.recipe_id,
					quantity_servings: s.quantity_servings
				});
			} else {
				await api.addDiaryEntry({ entry_date: date, meal: m, food_id: s.food_id, quantity_g: s.quantity_g });
			}
			await loadDay();
			await loadQuickAdd();
			await loadGapSuggestions();
			mealOptimizations[m] = await api.getMealOptimization(date, m, optimizeBudget);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			applyingSuggestionKey = null;
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
			await loadGapSuggestions();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleCopyDay() {
		error = null;
		copySuccessMessage = null;
		copying = true;
		try {
			const created = await api.copyDiaryDay(date, copyTargetDate);
			copySuccessMessage = `Copied ${created.length} entr${created.length === 1 ? 'y' : 'ies'} to ${copyTargetDate}.`;
			if (copyTargetDate === date) {
				await loadDay();
				await loadGapSuggestions();
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			copying = false;
		}
	}

	async function handleTakeSnapshot() {
		error = null;
		takingSnapshot = true;
		try {
			snapshot = await api.createDiarySnapshot(date);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			takingSnapshot = false;
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
			await loadGapSuggestions();
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
	<input
		type="date"
		aria-label="Diary date"
		bind:value={date}
		onchange={() => {
			copyTargetDate = addDays(date, 1);
			loadDay();
			loadGapSuggestions();
			loadSnapshot();
		}}
	/>
	<button type="button" onclick={() => shiftDay(1)}>Next &rarr;</button>
</div>

<div class="copy-day no-print">
	<label>
		Copy this day to
		<input type="date" bind:value={copyTargetDate} />
	</label>
	<button type="button" onclick={handleCopyDay} disabled={copying || !summary || summary.entries.length === 0}>
		{copying ? 'Copying…' : 'Copy'}
	</button>
	{#if copySuccessMessage}
		<span class="muted">{copySuccessMessage}</span>
	{/if}
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
	<p class="muted">Calibrating…</p>
{:else if summary}
	<div class="optimize-budget no-print">
		<label>
			Optional budget for "Optimize this meal" suggestions
			<input type="number" min="0" step="0.01" placeholder="no limit" bind:value={optimizeBudget} />
		</label>
	</div>

	{#each MEALS as m (m)}
		{@const mealEntries = summary.entries.filter((e) => e.meal === m)}
		{#if mealEntries.length > 0}
			<section>
				<h3>
					{m}
					<button type="button" class="no-print save-template-btn" onclick={() => handleSaveAsTemplate(m)}>
						Save as template
					</button>
					<button
						type="button"
						class="no-print save-template-btn"
						onclick={() => handleOptimizeMeal(m)}
						disabled={optimizingMeal === m}
					>
						{optimizingMeal === m ? 'Optimizing…' : 'Optimize this meal'}
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

				{#if mealOptimizations[m] !== undefined}
					{#if mealOptimizations[m] === null}
						<p class="muted">No worthwhile improvements found for this meal.</p>
					{:else}
						{@const opt = mealOptimizations[m]}
						{#if opt && opt.suggestions.length > 0}
							<div class="optimize-suggestions">
								<p class="muted">Targeting: {opt.target_nutrient_name} (lowest %DRV in this day)</p>
								<ul class="entries">
									{#each opt.suggestions as s (suggestionKey(m, s))}
										<li>
											{#if s.action === 'swap'}
												<span>Swap {s.replaces_food_name} &rarr; {s.food_name} ({s.quantity_g}g)</span>
											{:else if s.action === 'add_recipe'}
												<span>
													Add 1 serving of <a href="/recipes/{s.recipe_id}">{s.food_name}</a>
												</span>
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
												onclick={() => handleApplySuggestion(m, s)}
												disabled={applyingSuggestionKey === suggestionKey(m, s)}
											>
												{applyingSuggestionKey === suggestionKey(m, s) ? 'Applying…' : 'Apply'}
											</button>
											<p class="rationale">{s.rationale}</p>
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					{/if}
				{/if}
			</section>
		{/if}
	{/each}

	{#if summary.entries.length === 0}
		<p class="muted">Nothing logged for this day yet — search for a food under any meal above to get started.</p>
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

	<section class="methodology-mode no-print">
		<h3>Live vs Snapshot <a href="/methodology#live-vs-snapshot">ⓘ</a></h3>
		<p class="muted">
			The numbers below are always <strong>Live</strong> — recomputed from current code and data
			(methodology v{summary.nutrients[0]?.drv_methodology_version ?? '—'}). Snapshotting this day
			freezes today's computation so you can compare it against Live Mode later, after any future
			methodology change.
		</p>
		{#if snapshot}
			<p class="snapshot-status">
				Snapshotted {new Date(snapshot.created_at).toLocaleDateString()} at methodology v{snapshot.drv_methodology_version}.
				{#if snapshot.drv_methodology_version === summary.nutrients[0]?.drv_methodology_version}
					Matches today's live methodology — no drift yet.
				{:else}
					Live methodology has since changed — this day's live numbers may now differ from the
					snapshot.
				{/if}
			</p>
		{:else}
			<button type="button" onclick={handleTakeSnapshot} disabled={takingSnapshot || summary.entries.length === 0}>
				{takingSnapshot ? 'Snapshotting…' : 'Take a snapshot of this day'}
			</button>
		{/if}
	</section>

	<NutrientBars nutrients={summary.nutrients} per="per day" absorbedIronMg={totalAbsorbedIronMg} />

	{#if gapSuggestion}
		<section class="gap-suggestion">
			<h3>
				Today's biggest gap: {gapSuggestion.nutrient_name}
				<span class="muted">({gapSuggestion.percent_drv.toFixed(0)}% of target)</span>
			</h3>
			<ul class="entries">
				{#each gapSuggestion.foods as f (f.food_id)}
					<li>
						<a href="/foods/{f.food_id}">{f.food_name}</a>
						<span class="muted">{f.amount_per_100g.toFixed(1)}{gapSuggestion.unit} / 100g</span>
						<button
							type="button"
							class="no-print"
							onclick={() => handleAddGapFood(f.food_id)}
							disabled={addingGapFoodId === f.food_id}
						>
							{addingGapFoodId === f.food_id ? 'Adding…' : `Add 100g as ${meal}`}
						</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

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

	{#if summary.sodium_potassium || summary.protein_distribution.length > 0}
		<section class="food-chemistry">
			<h3>Food chemistry <a class="no-print" href="/methodology#food-chemistry">ⓘ</a></h3>

			{#if summary.sodium_potassium}
				<div class="sodium-potassium">
					<strong>Sodium:potassium ratio</strong>
					<span>
						{summary.sodium_potassium.ratio !== null
							? `${summary.sodium_potassium.ratio.toFixed(2)}:1`
							: 'n/a'}
					</span>
					<p class="muted">{summary.sodium_potassium.guidance}</p>
				</div>
			{/if}

			{#if summary.protein_distribution.length > 0}
				<div class="protein-distribution">
					<strong>Protein distribution &amp; leucine threshold</strong>
					<ul class="entries">
						{#each summary.protein_distribution as d (d.meal)}
							<li>
								<span class="meal-label">{d.meal}</span>
								<span class="muted">{d.protein_g.toFixed(0)}g protein, {d.leucine_g.toFixed(2)}g leucine</span>
								<span
									class:threshold-met={d.meets_leucine_threshold}
									class:threshold-missed={!d.meets_leucine_threshold}
								>
									{d.meets_leucine_threshold ? '✓ meets' : '✗ below'}
									{d.leucine_threshold_g}g threshold
								</span>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
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
	.copy-day {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 1.5rem;
		font-size: 0.9em;
	}
	.copy-day label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
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
		color: var(--color-danger);
	}
	.muted {
		color: var(--color-text-muted);
		font-size: 0.9em;
		margin: 0 0.5rem;
	}
	.bioavailability,
	.gap-suggestion {
		margin-top: 1.5rem;
		padding: 1rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
	}
	.gap-suggestion .entries li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
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
		border-top: 1px solid var(--color-border);
	}
	.food-chemistry {
		margin-top: 1.5rem;
		padding: 1rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
	}
	.sodium-potassium {
		margin-bottom: 0.75rem;
	}
	.protein-distribution .entries li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.threshold-met {
		color: var(--color-success);
	}
	.threshold-missed {
		color: var(--color-text-muted);
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
	.optimize-suggestions {
		margin-top: 0.5rem;
		padding: 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
	}
	.methodology-mode {
		margin: 1rem 0;
		padding: 0.75rem 1rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
		font-size: 0.9em;
	}
	.methodology-mode h3 {
		margin-top: 0;
	}
	.snapshot-status {
		color: var(--color-primary);
	}
	.rationale {
		margin: 0.15rem 0 0.5rem;
		font-size: 0.85em;
		color: var(--color-text-muted);
	}
	.optimize-budget {
		margin: 0.75rem 0;
		font-size: 0.9em;
	}
	.optimize-budget input {
		margin-left: 0.4rem;
		width: 6rem;
	}
	.quick-add {
		margin: 1rem 0;
		padding: 1rem;
		border: 1px solid var(--color-border);
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
</style>
