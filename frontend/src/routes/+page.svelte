<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import type { Food } from '$lib/types';

	let foods: Food[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			foods = await api.listFoods();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});
</script>

<h1>Nutri-Matic</h1>
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
</style>
