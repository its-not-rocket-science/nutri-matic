<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { Collection } from '$lib/types';

	let collections: Collection[] = $state([]);
	let newName = $state('');
	let error: string | null = $state(null);
	let loading = $state(true);
	let creating = $state(false);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			collections = await api.listCollections();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function handleCreate(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		if (!newName.trim()) return;
		creating = true;
		try {
			const collection = await api.createCollection(newName);
			await goto(`/collections/${collection.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			creating = false;
		}
	}
</script>

<h1>Collections</h1>
<p><a href="/recipes">&larr; Back to recipes</a></p>

{#if loading}
	<p>Loading…</p>
{:else}
	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if collections.length === 0}
		<p>No collections yet.</p>
	{:else}
		<ul>
			{#each collections as collection (collection.id)}
				<li>
					<a href="/collections/{collection.id}">{collection.name}</a>
					<span class="muted">{collection.recipe_count} recipe{collection.recipe_count === 1 ? '' : 's'}</span>
				</li>
			{/each}
		</ul>
	{/if}

	<form onsubmit={handleCreate}>
		<input type="text" bind:value={newName} placeholder="New collection name" required />
		<button type="submit" disabled={creating}>{creating ? 'Creating…' : 'Create collection'}</button>
	</form>
{/if}

<style>
	.error {
		color: #b00020;
	}
	.muted {
		color: #666;
		margin-left: 0.5rem;
		font-size: 0.9em;
	}
	ul {
		list-style: none;
		padding: 0;
	}
	li {
		padding: 0.5rem 0;
		border-bottom: 1px solid #eee;
	}
	form {
		display: flex;
		gap: 0.5rem;
		margin-top: 1.5rem;
		max-width: 24rem;
	}
	form input {
		flex: 1;
	}
</style>
