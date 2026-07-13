<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import BarcodeScanner from '$lib/components/BarcodeScanner.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import type { DiarySummary, Food, Meal, Recipe } from '$lib/types';

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
		await loadDay();
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
		try {
			await api.deleteDiaryEntry(id);
			await loadDay();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	const MEALS: Meal[] = ['breakfast', 'lunch', 'dinner', 'snack'];
</script>

<h1>Diary</h1>
<p><a href="/">&larr; Back</a></p>

<div class="date-nav">
	<button type="button" onclick={() => shiftDay(-1)}>&larr; Prev</button>
	<input type="date" bind:value={date} onchange={loadDay} />
	<button type="button" onclick={() => shiftDay(1)}>Next &rarr;</button>
</div>

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
				<h3>{m}</h3>
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
							<button type="button" onclick={() => handleDelete(entry.id)}>Remove</button>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/each}

	{#if summary.entries.length === 0}
		<p>Nothing logged for this day yet.</p>
	{/if}

	<form onsubmit={handleAdd}>
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

	<NutrientBars nutrients={summary.nutrients} per="per day" />
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
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: 0.25rem 0;
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
