<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import StarRating from '$lib/components/StarRating.svelte';
	import TagEditor from '$lib/components/TagEditor.svelte';
	import type { NutrientAmount, Recipe, RecipeComment, RecipeRatingSummary, RecipeShare, Score } from '$lib/types';

	const recipeId = Number(page.params.id);

	let recipe: Recipe | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	let shares: RecipeShare[] = $state([]);
	let shareEmail = $state('');
	let ratings: RecipeRatingSummary | null = $state(null);
	let comments: RecipeComment[] = $state([]);
	let newComment = $state('');
	let error: string | null = $state(null);
	let shareError: string | null = $state(null);
	let commentError: string | null = $state(null);
	let loading = $state(true);
	let deleting = $state(false);
	let copying = $state(false);
	let sharing = $state(false);
	let posting = $state(false);

	async function loadShares() {
		if (!recipe?.is_owner) return;
		try {
			shares = await api.listShares(recipeId);
		} catch (e) {
			shareError = e instanceof Error ? e.message : String(e);
		}
	}

	async function loadComments() {
		try {
			comments = await api.listComments(recipeId);
		} catch (e) {
			commentError = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			recipe = await api.getRecipe(recipeId);
			const [diaas, pdcaas, nutrientResult, ratingResult] = await Promise.allSettled([
				api.scoreRecipe(recipeId, 'diaas'),
				api.scoreRecipe(recipeId, 'pdcaas'),
				api.getRecipeNutrients(recipeId),
				api.getRatings(recipeId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
			if (ratingResult.status === 'fulfilled') ratings = ratingResult.value;
			await Promise.all([loadShares(), loadComments()]);
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

	async function handleRate(n: number) {
		try {
			ratings = await api.rateRecipe(recipeId, n);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleClearRating() {
		try {
			ratings = await api.deleteRating(recipeId);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleAddComment(e: SubmitEvent) {
		e.preventDefault();
		commentError = null;
		if (!newComment.trim()) return;
		posting = true;
		try {
			await api.createComment(recipeId, newComment);
			newComment = '';
			await loadComments();
		} catch (e) {
			commentError = e instanceof Error ? e.message : String(e);
		} finally {
			posting = false;
		}
	}

	async function handleDeleteComment(commentId: number) {
		try {
			await api.deleteComment(recipeId, commentId);
			await loadComments();
		} catch (e) {
			commentError = e instanceof Error ? e.message : String(e);
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

	<div class="rating-row">
		<StarRating
			value={ratings?.my_rating ?? null}
			onRate={handleRate}
			onClear={ratings?.my_rating ? handleClearRating : undefined}
		/>
		{#if ratings && ratings.count > 0}
			<span class="muted">
				{ratings.average?.toFixed(1)} average ({ratings.count} rating{ratings.count === 1 ? '' : 's'})
			</span>
		{:else}
			<span class="muted">No ratings yet</span>
		{/if}
	</div>

	<TagEditor bind:recipe={recipe as Recipe} editable={recipe.is_owner} />

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

	<section class="comments">
		<h2>Comments</h2>
		{#if comments.length > 0}
			<ul>
				{#each comments as comment (comment.id)}
					<li>
						<div class="comment-meta">
							<strong>{comment.user_email}</strong>
							<span class="muted">{new Date(comment.created_at).toLocaleString()}</span>
							{#if comment.is_own || recipe.is_owner}
								<button type="button" onclick={() => handleDeleteComment(comment.id)}>Delete</button>
							{/if}
						</div>
						<p>{comment.body}</p>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="muted">No comments yet.</p>
		{/if}

		<form onsubmit={handleAddComment}>
			<textarea bind:value={newComment} placeholder="Add a comment…" rows="2" required></textarea>
			<button type="submit" disabled={posting}>{posting ? 'Posting…' : 'Post comment'}</button>
		</form>
		{#if commentError}
			<p class="error">{commentError}</p>
		{/if}
	</section>
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
	.rating-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin: 0.75rem 0 1.5rem;
	}
	.comments {
		margin: 1.5rem 0;
		max-width: 32rem;
	}
	.comments ul {
		list-style: none;
		padding: 0;
	}
	.comments li {
		padding: 0.5rem 0;
		border-bottom: 1px solid #eee;
	}
	.comments li p {
		margin: 0.25rem 0 0;
	}
	.comment-meta {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.comments form {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin-top: 1rem;
	}
	.comments textarea {
		font-family: inherit;
		resize: vertical;
	}
</style>
