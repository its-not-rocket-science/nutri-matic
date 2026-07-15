<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import StarRating from '$lib/components/StarRating.svelte';
	import TagEditor from '$lib/components/TagEditor.svelte';
	import { downloadCsv } from '$lib/csv';
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

	function handleDownloadCsv() {
		if (!recipe) return;
		const rows: (string | number | null)[][] = [['Ingredients'], ['Food', 'Quantity (g)']];
		for (const ing of recipe.ingredients) {
			rows.push([ing.food_name, ing.quantity_g]);
		}
		rows.push([]);
		rows.push(['Nutrients (per serving)']);
		rows.push(['Name', 'Amount', 'Unit', 'DRV', '% DRV']);
		for (const n of nutrients) {
			rows.push([n.name, n.amount, n.unit, n.adult_drv, n.percent_drv]);
		}
		downloadCsv(`recipe-${recipe.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.csv`, rows);
	}
</script>

<p class="no-print"><a href="/recipes">&larr; Back</a></p>

{#if loading}
	<p class="muted">Loading…</p>
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

	<div class="export-actions no-print">
		<PrintButton />
		<button type="button" class="btn btn-secondary" onclick={handleDownloadCsv}>Download CSV</button>
	</div>

	<div class="rating-row no-print">
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

	<div class="no-print">
		<TagEditor bind:recipe={recipe as Recipe} editable={recipe.is_owner} />
	</div>

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
		<section class="card sharing no-print">
			<h2>Sharing</h2>
			{#if shares.length > 0}
				<ul class="shares">
					{#each shares as share (share.id)}
						<li>
							{share.email}
							<button type="button" class="btn btn-danger" onclick={() => handleUnshare(share.id)}>
								Remove
							</button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="muted">Not shared with anyone yet.</p>
			{/if}
			<form class="share-form" onsubmit={handleShare}>
				<input type="email" bind:value={shareEmail} placeholder="Share with (email)" required />
				<button type="submit" class="btn btn-primary" disabled={sharing}>
					{sharing ? 'Sharing…' : 'Share'}
				</button>
			</form>
			{#if shareError}
				<p class="error">{shareError}</p>
			{/if}
		</section>

		<p class="no-print">
			<button type="button" class="btn btn-danger" onclick={handleDelete} disabled={deleting}>
				Delete recipe
			</button>
		</p>
	{:else}
		<p class="no-print">
			<button type="button" class="btn btn-secondary" onclick={handleCopy} disabled={copying}>
				{copying ? 'Copying…' : 'Copy to my recipes'}
			</button>
		</p>
	{/if}

	<section class="comments no-print">
		<h2>Comments</h2>
		{#if comments.length > 0}
			<ul class="card">
				{#each comments as comment (comment.id)}
					<li>
						<div class="comment-meta">
							<strong>{comment.user_email}</strong>
							<span class="muted">{new Date(comment.created_at).toLocaleString()}</span>
							{#if comment.is_own || recipe.is_owner}
								<button type="button" class="btn btn-danger" onclick={() => handleDeleteComment(comment.id)}>
									Delete
								</button>
							{/if}
						</div>
						<p>{comment.body}</p>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="muted">No comments yet.</p>
		{/if}

		<form class="comment-form" onsubmit={handleAddComment}>
			<textarea bind:value={newComment} placeholder="Add a comment…" rows="2" required></textarea>
			<button type="submit" class="btn btn-primary" disabled={posting}>
				{posting ? 'Posting…' : 'Post comment'}
			</button>
		</form>
		{#if commentError}
			<p class="error">{commentError}</p>
		{/if}
	</section>
{/if}

<style>
	.ingredients {
		list-style: none;
		padding: 0;
		margin-bottom: var(--space-5);
	}
	.ingredients li {
		padding: var(--space-1) 0;
	}
	.ingredients .muted {
		margin-left: var(--space-2);
	}
	.sharing {
		margin: var(--space-5) 0;
		max-width: 24rem;
	}
	.shares {
		list-style: none;
		padding: 0;
		margin-bottom: var(--space-3);
	}
	.shares li {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		padding: var(--space-1) 0;
	}
	.share-form {
		display: flex;
		gap: var(--space-2);
	}
	.share-form input {
		flex: 1;
	}
	.rating-row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin: var(--space-3) 0 var(--space-5);
	}
	.comments {
		margin: var(--space-5) 0;
		max-width: 32rem;
	}
	.comments ul {
		list-style: none;
		padding: 0;
	}
	.comments li {
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
	}
	.comments li:last-child {
		border-bottom: none;
	}
	.comments li p {
		margin: var(--space-1) 0 0;
	}
	.comment-meta {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.comment-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
	.comment-form textarea {
		font-family: inherit;
		resize: vertical;
	}
	.export-actions {
		display: flex;
		gap: var(--space-2);
		margin: var(--space-2) 0 var(--space-4);
	}
	@media print {
		.no-print {
			display: none !important;
		}
	}
</style>
