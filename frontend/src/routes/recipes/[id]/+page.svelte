<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import type { NutrientAmount, Recipe, RecipeShare, Score } from '$lib/types';

	const recipeId = Number(page.params.id);

	let recipe: Recipe | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	let shares: RecipeShare[] = $state([]);
	let shareEmail = $state('');
	let error: string | null = $state(null);
	let shareError: string | null = $state(null);
	let loading = $state(true);
	let deleting = $state(false);
	let copying = $state(false);
	let sharing = $state(false);

	async function loadShares() {
		if (!recipe?.is_owner) return;
		try {
			shares = await api.listShares(recipeId);
		} catch (e) {
			shareError = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			recipe = await api.getRecipe(recipeId);
			const [diaas, pdcaas, nutrientResult] = await Promise.allSettled([
				api.scoreRecipe(recipeId, 'diaas'),
				api.scoreRecipe(recipeId, 'pdcaas'),
				api.getRecipeNutrients(recipeId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
			await loadShares();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function handleDelete() {
		if (!confirm(`Delete "${recipe?.name}"?`)) return;
		deleting = true;
		try {
			await api.deleteRecipe(recipeId);
			await goto('/recipes');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			deleting = false;
		}
	}

	async function handleCopy() {
		copying = true;
		try {
			const copy = await api.copyRecipe(recipeId);
			await goto(`/recipes/${copy.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			copying = false;
		}
	}

	async function handleShare(e: SubmitEvent) {
		e.preventDefault();
		shareError = null;
		if (!shareEmail) return;
		sharing = true;
		try {
			await api.createShare(recipeId, shareEmail);
			shareEmail = '';
			await loadShares();
		} catch (e) {
			shareError = e instanceof Error ? e.message : String(e);
		} finally {
			sharing = false;
		}
	}

	async function handleUnshare(shareId: number) {
		try {
			await api.deleteShare(recipeId, shareId);
			await loadShares();
		} catch (e) {
			shareError = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<p><a href="/recipes">&larr; Back</a></p>

{#if loading}
	<p>Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if recipe}
	<h1>{recipe.name}</h1>
	<p class="muted">
		{recipe.servings} servings
		{#if !recipe.is_owner}
			· shared by {recipe.owner_email}
		{/if}
	</p>

	<ul class="ingredients">
		{#each recipe.ingredients as ingredient (ingredient.food_id)}
			<li>
				<a href="/foods/{ingredient.food_id}">{ingredient.food_name}</a>
				<span class="muted">{ingredient.quantity_g}g</span>
			</li>
		{/each}
	</ul>

	{#if diaasScore}<ScoreCard label="DIAAS" score={diaasScore} />{/if}
	{#if pdcaasScore}<ScoreCard label="PDCAAS" score={pdcaasScore} />{/if}

	{#if !diaasScore && !pdcaasScore}
		<p>No digestibility data on this recipe's ingredients — no score can be computed.</p>
	{/if}

	<NutrientBars {nutrients} per="per serving" />

	{#if recipe.is_owner}
		<section class="sharing">
			<h2>Sharing</h2>
			{#if shares.length > 0}
				<ul class="shares">
					{#each shares as share (share.id)}
						<li>
							{share.email}
							<button type="button" onclick={() => handleUnshare(share.id)}>Remove</button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="muted">Not shared with anyone yet.</p>
			{/if}
			<form onsubmit={handleShare}>
				<input type="email" bind:value={shareEmail} placeholder="Share with (email)" required />
				<button type="submit" disabled={sharing}>{sharing ? 'Sharing…' : 'Share'}</button>
			</form>
			{#if shareError}
				<p class="error">{shareError}</p>
			{/if}
		</section>

		<p><button type="button" onclick={handleDelete} disabled={deleting}>Delete recipe</button></p>
	{:else}
		<p>
			<button type="button" onclick={handleCopy} disabled={copying}>
				{copying ? 'Copying…' : 'Copy to my recipes'}
			</button>
		</p>
	{/if}
{/if}

<style>
	.error {
		color: #b00020;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.ingredients {
		list-style: none;
		padding: 0;
		margin-bottom: 1.5rem;
	}
	.ingredients li {
		padding: 0.25rem 0;
	}
	.ingredients .muted {
		margin-left: 0.5rem;
	}
	.sharing {
		margin: 1.5rem 0;
		padding: 1rem;
		border: 1px solid #eee;
		border-radius: 4px;
		max-width: 24rem;
	}
	.shares {
		list-style: none;
		padding: 0;
		margin-bottom: 0.75rem;
	}
	.shares li {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		padding: 0.2rem 0;
	}
	.sharing form {
		display: flex;
		gap: 0.5rem;
	}
	.sharing input {
		flex: 1;
	}
</style>
