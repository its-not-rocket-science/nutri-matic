<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { Recipe } from '$lib/types';

	let recipes: Recipe[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			recipes = await api.listRecipes();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});
</script>

<h1>Recipes</h1>
<p><a href="/">&larr; Back</a></p>
<p><a href="/recipes/new">+ New recipe</a></p>

{#if loading}
	<p>Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if recipes.length === 0}
	<p>No recipes yet.</p>
{:else}
	<ul>
		{#each recipes as recipe (recipe.id)}
			<li>
				<a href="/recipes/{recipe.id}">{recipe.name}</a>
				<span class="muted">{recipe.ingredients.length} ingredients · {recipe.servings} servings</span>
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
