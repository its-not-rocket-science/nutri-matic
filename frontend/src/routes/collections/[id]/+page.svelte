<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { CollectionDetail, Recipe } from '$lib/types';

	const collectionId = Number(page.params.id);

	let collection: CollectionDetail | null = $state(null);
	let candidates: Recipe[] = $state([]);
	let selectedRecipeId: number | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);
	let adding = $state(false);
	let deleting = $state(false);

	const availableCandidates = $derived.by(() => {
		const inCollection = new Set(collection?.recipes.map((r) => r.id) ?? []);
		return candidates.filter((r) => !inCollection.has(r.id));
	});

	async function load() {
		collection = await api.getCollection(collectionId);
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			const [mine, shared] = await Promise.all([api.listRecipes(), api.listSharedWithMe()]);
			candidates = [...mine, ...shared];
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
		if (selectedRecipeId === null) return;
		adding = true;
		try {
			collection = await api.addRecipeToCollection(collectionId, selectedRecipeId);
			selectedRecipeId = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			adding = false;
		}
	}

	async function handleRemove(recipeId: number) {
		error = null;
		try {
			collection = await api.removeRecipeFromCollection(collectionId, recipeId);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleDeleteCollection() {
		if (!collection || !confirm(`Delete collection "${collection.name}"?`)) return;
		deleting = true;
		try {
			await api.deleteCollection(collectionId);
			await goto('/collections');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			deleting = false;
		}
	}
</script>

<p><a href="/collections">&larr; Back to collections</a></p>

{#if loading}
	<p>Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if collection}
	<h1>{collection.name}</h1>

	{#if collection.recipes.length === 0}
		<p>No recipes in this collection yet.</p>
	{:else}
		<ul>
			{#each collection.recipes as recipe (recipe.id)}
				<li>
					<a href="/recipes/{recipe.id}">{recipe.name}</a>
					<span class="muted">
						{#if !recipe.is_owner}by {recipe.owner_email} · {/if}{recipe.servings} servings
					</span>
					<button type="button" onclick={() => handleRemove(recipe.id)}>Remove</button>
				</li>
			{/each}
		</ul>
	{/if}

	{#if availableCandidates.length > 0}
		<form onsubmit={handleAdd}>
			<select bind:value={selectedRecipeId}>
				<option value={null}>Add a recipe…</option>
				{#each availableCandidates as recipe (recipe.id)}
					<option value={recipe.id}>{recipe.name}</option>
				{/each}
			</select>
			<button type="submit" disabled={adding || selectedRecipeId === null}>
				{adding ? 'Adding…' : 'Add'}
			</button>
		</form>
	{/if}

	<p><button type="button" onclick={handleDeleteCollection} disabled={deleting}>Delete collection</button></p>
{/if}

<style>
	.error {
		color: #b00020;
	}
	.muted {
		color: #666;
		margin: 0 0.5rem;
		font-size: 0.9em;
	}
	ul {
		list-style: none;
		padding: 0;
	}
	li {
		padding: 0.5rem 0;
		border-bottom: 1px solid #eee;
		display: flex;
		align-items: center;
	}
	form {
		display: flex;
		gap: 0.5rem;
		margin: 1.5rem 0;
	}
</style>
