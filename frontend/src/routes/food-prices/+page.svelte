<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { Food, FoodPrice } from '$lib/types';

	let prices: FoodPrice[] = $state([]);
	let allFoods: Food[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);

	let search = $state('');
	let selectedFood: Food | null = $state(null);
	let packagePrice = $state<number | null>(null);
	let packageQuantityG = $state<number | null>(null);

	const searchResults = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (q.length < 2) return [];
		const priced = new Set(prices.map((p) => p.food_id));
		return allFoods.filter((f) => !priced.has(f.id) && f.name.toLowerCase().includes(q)).slice(0, 15);
	});

	async function load() {
		prices = await api.listFoodPrices();
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			allFoods = await api.listFoods();
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	function selectFood(food: Food) {
		selectedFood = food;
		search = '';
	}

	async function handleAdd(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		if (!selectedFood || !packagePrice || !packageQuantityG) return;
		saving = true;
		try {
			await api.setFoodPrice(selectedFood.id, {
				package_price: packagePrice,
				package_quantity_g: packageQuantityG
			});
			selectedFood = null;
			packagePrice = null;
			packageQuantityG = null;
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}

	async function handleDelete(foodId: number) {
		error = null;
		try {
			await api.deleteFoodPrice(foodId);
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<h1>Food prices</h1>
<p><a href="/">&larr; Back</a></p>
<p class="muted">
	Set what you actually pay for a food (price for a package of a given size) so the meal plan's
	weekly shopping list can estimate a total cost.
</p>

{#if error}
	<p class="error">{error}</p>
{/if}

{#if loading}
	<p>Loading…</p>
{:else}
	{#if prices.length === 0}
		<p class="muted">No prices set yet.</p>
	{:else}
		<ul class="entries">
			{#each prices as price (price.id)}
				<li>
					<a href="/foods/{price.food_id}">{price.food_name}</a>
					<span class="muted">
						${price.package_price.toFixed(2)} / {price.package_quantity_g}g
						(${price.price_per_100g.toFixed(2)} per 100g)
					</span>
					<button type="button" onclick={() => handleDelete(price.food_id)}>Remove</button>
				</li>
			{/each}
		</ul>
	{/if}

	<form onsubmit={handleAdd}>
		<h3>Add a price</h3>

		{#if selectedFood}
			<p>
				Selected: <strong>{selectedFood.name}</strong>
				<button type="button" onclick={() => (selectedFood = null)}>Change</button>
			</p>
		{:else}
			<label>
				Search foods
				<input type="text" bind:value={search} placeholder="Search…" />
			</label>
			{#if searchResults.length > 0}
				<ul class="search-results">
					{#each searchResults as food (food.id)}
						<li><button type="button" onclick={() => selectFood(food)}>{food.name}</button></li>
					{/each}
				</ul>
			{/if}
		{/if}

		<label>
			Package price ($)
			<input type="number" step="any" min="0" bind:value={packagePrice} required />
		</label>

		<label>
			Package size (g)
			<input type="number" step="any" min="0" bind:value={packageQuantityG} required />
		</label>

		<button type="submit" disabled={saving || !selectedFood}>{saving ? 'Saving…' : 'Save price'}</button>
	</form>
{/if}

<style>
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
		padding: 0.4rem 0;
		display: flex;
		align-items: center;
		gap: 0.5rem;
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
