<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import type { Food, FoodPrice } from '$lib/types';

	let prices: FoodPrice[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);

	let selectedFood: Food | null = $state(null);
	let packagePrice = $state<number | null>(null);
	let packageQuantityG = $state<number | null>(null);

	const pricedFoodIds = $derived(new Set(prices.map((p) => p.food_id)));

	async function load() {
		prices = await api.listFoodPrices();
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

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
	<p class="muted">Calibrating…</p>
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
					<button type="button" class="btn btn-danger" onclick={() => handleDelete(price.food_id)}>
						Remove
					</button>
				</li>
			{/each}
		</ul>
	{/if}

	<form class="card price-form" onsubmit={handleAdd}>
		<h3>Add a price</h3>

		{#if selectedFood}
			<p>
				Selected: <strong>{selectedFood.name}</strong>
				<button type="button" class="btn btn-secondary" onclick={() => (selectedFood = null)}>
					Change
				</button>
			</p>
		{:else}
			<FoodSearchInput
				onSelect={(food) => (selectedFood = food)}
				exclude={(food) => pricedFoodIds.has(food.id)}
			/>
		{/if}

		<div class="field">
			<label for="package-price">Package price ($)</label>
			<input id="package-price" type="number" step="any" min="0" bind:value={packagePrice} required />
		</div>

		<div class="field">
			<label for="package-size">Package size (g)</label>
			<input id="package-size" type="number" step="any" min="0" bind:value={packageQuantityG} required />
		</div>

		<button type="submit" class="btn btn-primary" disabled={saving || !selectedFood}>
			{saving ? 'Saving…' : 'Save price'}
		</button>
	</form>
{/if}

<style>
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.entries li:last-child {
		border-bottom: none;
	}
	.price-form {
		max-width: 28rem;
		margin: var(--space-5) 0;
	}
	.price-form .field {
		margin-top: var(--space-3);
	}
</style>
