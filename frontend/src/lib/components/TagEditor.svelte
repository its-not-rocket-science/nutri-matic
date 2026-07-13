<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import type { Recipe } from '$lib/types';

	let { recipe = $bindable(), editable }: { recipe: Recipe; editable: boolean } = $props();

	let newTag = $state('');
	let myTags: string[] = $state([]);
	let error: string | null = $state(null);

	onMount(async () => {
		if (!editable) return;
		try {
			myTags = await api.listMyTags();
		} catch {
			// autocomplete is a nicety — ignore failures
		}
	});

	async function handleAdd(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		if (!newTag.trim()) return;
		try {
			recipe = await api.addTag(recipe.id, newTag);
			newTag = '';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleRemove(tag: string) {
		error = null;
		try {
			recipe = await api.removeTag(recipe.id, tag);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<div class="tags">
	{#each recipe.tags as tag (tag)}
		<span class="tag">
			{tag}
			{#if editable}
				<button type="button" onclick={() => handleRemove(tag)} aria-label={`Remove tag ${tag}`}>&times;</button>
			{/if}
		</span>
	{/each}
	{#if editable}
		<form onsubmit={handleAdd}>
			<input list="tag-options" bind:value={newTag} placeholder="Add tag…" />
			<datalist id="tag-options">
				{#each myTags as t (t)}<option value={t}></option>{/each}
			</datalist>
			<button type="submit">Add</button>
		</form>
	{/if}
</div>
{#if error}
	<p class="error">{error}</p>
{/if}

<style>
	.tags {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		margin: 0.5rem 0;
	}
	.tag {
		background: #eef;
		color: #334;
		border-radius: 999px;
		padding: 0.15rem 0.6rem;
		font-size: 0.85em;
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
	}
	.tag button {
		background: none;
		border: none;
		cursor: pointer;
		color: #334;
		font-size: 1em;
		line-height: 1;
		padding: 0;
	}
	.tags form {
		display: inline-flex;
		gap: 0.3rem;
	}
	.tags input {
		font-size: 0.85em;
		padding: 0.15rem 0.4rem;
	}
	.error {
		color: #b00020;
		font-size: 0.9em;
	}
</style>
