<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import StarRating from '$lib/components/StarRating.svelte';
	import TagEditor from '$lib/components/TagEditor.svelte';
	import { downloadCsv } from '$lib/csv';
	import type {
		AbsorbedProtein,
		Food,
		NutrientAmount,
		Recipe,
		RecipeComment,
		RecipeRatingSummary,
		RecipeShare,
		Score
	} from '$lib/types';

	const recipeId = Number(page.params.id);

	let recipe: Recipe | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let diaasUnavailableReason: string | null = $state(null);
	let pdcaasUnavailableReason: string | null = $state(null);
	let absorbedProtein: AbsorbedProtein | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	const totalProtein = $derived(nutrients.find((n) => n.key === 'protein') ?? null);
	let shares: RecipeShare[] = $state([]);
	let shareEmail = $state('');
	let ratings: RecipeRatingSummary | null = $state(null);
	let comments: RecipeComment[] = $state([]);
	let newComment = $state('');
	let error: string | null = $state(null);
	let shareError: string | null = $state(null);
	let commentError: string | null = $state(null);
	let editError: string | null = $state(null);
	let loading = $state(true);
	let deleting = $state(false);
	let copying = $state(false);
	let sharing = $state(false);
	let posting = $state(false);
	let editingDetails = $state(false);
	let editName = $state('');
	let editServings = $state<number | null>(null);
	let editSourceUrl = $state('');
	let editMethod = $state('');
	let savingDetails = $state(false);
	let addingIngredient = $state(false);

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
			const [diaas, pdcaas, nutrientResult, absorbedResult, ratingResult] = await Promise.allSettled([
				api.scoreRecipe(recipeId, 'diaas'),
				api.scoreRecipe(recipeId, 'pdcaas'),
				api.getRecipeNutrients(recipeId),
				api.getRecipeAbsorbedProtein(recipeId),
				api.getRatings(recipeId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			else diaasUnavailableReason = diaas.reason instanceof Error ? diaas.reason.message : String(diaas.reason);
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			else pdcaasUnavailableReason = pdcaas.reason instanceof Error ? pdcaas.reason.message : String(pdcaas.reason);
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
			if (absorbedResult.status === 'fulfilled') absorbedProtein = absorbedResult.value;
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

	function startEditDetails() {
		if (!recipe) return;
		editName = recipe.name;
		editServings = recipe.servings;
		editSourceUrl = recipe.source_url ?? '';
		editMethod = recipe.method ?? '';
		editError = null;
		editingDetails = true;
	}

	async function handleSaveDetails(e: SubmitEvent) {
		e.preventDefault();
		if (!editName || editServings === null || editServings <= 0) {
			editError = 'Name and a positive number of servings are required.';
			return;
		}
		const trimmedUrl = editSourceUrl.trim();
		if (trimmedUrl && !trimmedUrl.startsWith('http://') && !trimmedUrl.startsWith('https://')) {
			editError = 'Source URL must start with http:// or https://';
			return;
		}
		savingDetails = true;
		editError = null;
		try {
			recipe = await api.updateRecipe(recipeId, {
				name: editName,
				servings: editServings,
				source_url: trimmedUrl || null,
				method: editMethod.trim() || null
			});
			editingDetails = false;
		} catch (e) {
			editError = e instanceof Error ? e.message : String(e);
		} finally {
			savingDetails = false;
		}
	}

	async function handleAddIngredient(food: Food) {
		editError = null;
		addingIngredient = true;
		try {
			recipe = await api.addIngredient(recipeId, food.id, 100);
		} catch (e) {
			editError = e instanceof Error ? e.message : String(e);
		} finally {
			addingIngredient = false;
		}
	}

	async function handleUpdateIngredientQuantity(ingredientId: number, quantityG: number) {
		if (quantityG <= 0) return;
		editError = null;
		try {
			recipe = await api.updateIngredient(recipeId, ingredientId, quantityG);
		} catch (e) {
			editError = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleRemoveIngredient(ingredientId: number) {
		editError = null;
		try {
			recipe = await api.removeIngredient(recipeId, ingredientId);
		} catch (e) {
			editError = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<svelte:head>
	<title>{recipe ? `${recipe.name} — Nutri-Matic` : 'Nutri-Matic'}</title>
	{#if recipe}
		<meta name="description" content="DIAAS/PDCAAS protein quality score and micronutrient profile for {recipe.name}." />
	{/if}
</svelte:head>

<p class="no-print"><a href="/recipes">&larr; Back</a></p>

{#if loading}
	<p class="muted">Calibrating…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if recipe}
	{#if editingDetails}
		<form class="card edit-details-form no-print" onsubmit={handleSaveDetails}>
			<div class="field">
				<label for="edit-name">Name</label>
				<input id="edit-name" type="text" bind:value={editName} required />
			</div>
			<div class="field">
				<label for="edit-servings">Servings</label>
				<input id="edit-servings" type="number" step="any" min="0" bind:value={editServings} required />
			</div>
			<div class="field">
				<label for="edit-source-url">Source URL (optional)</label>
				<input id="edit-source-url" type="url" bind:value={editSourceUrl} placeholder="https://…" />
			</div>
			<details class="method-details">
				<summary>Method (optional)</summary>
				<div class="field">
					<label for="edit-method">Cooking instructions</label>
					<textarea id="edit-method" bind:value={editMethod} rows="6" placeholder="Optional step-by-step method…"
					></textarea>
				</div>
			</details>
			{#if editError}<p class="error">{editError}</p>{/if}
			<div class="actions">
				<button type="submit" class="btn btn-primary" disabled={savingDetails}>
					{savingDetails ? 'Saving…' : 'Save'}
				</button>
				<button type="button" class="btn btn-secondary" onclick={() => (editingDetails = false)}>Cancel</button>
			</div>
		</form>
	{:else}
		<h1>{recipe.name}</h1>
		<p class="muted">
			{recipe.servings} servings
			{#if !recipe.is_owner}
				· by {recipe.owner_email}{recipe.is_public ? ' · stock recipe' : ''}
			{:else if recipe.is_public}
				· stock recipe
			{/if}
			{#if recipe.is_owner}
				<button type="button" class="btn btn-secondary no-print" onclick={startEditDetails}>Edit</button>
			{/if}
		</p>
		{#if recipe.source_url}
			<p class="muted">
				Source: <a href={recipe.source_url} target="_blank" rel="noopener noreferrer">{recipe.source_url}</a>
			</p>
		{/if}
		{#if recipe.method}
			<details class="method-details">
				<summary>Method</summary>
				<p class="method-text">{recipe.method}</p>
			</details>
		{/if}
	{/if}

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
		{#each recipe.ingredients as ingredient (ingredient.id)}
			<li>
				<a href="/foods/{ingredient.food_id}">{ingredient.food_name}</a>
				{#if recipe.is_owner}
					<input
						type="number"
						step="any"
						min="0"
						class="no-print"
						value={ingredient.quantity_g}
						aria-label="Quantity in grams for {ingredient.food_name}"
						onchange={(e) =>
							handleUpdateIngredientQuantity(ingredient.id, Number((e.target as HTMLInputElement).value))}
					/>
					<span class="muted no-print">g</span>
					<span class="muted print-only">{ingredient.quantity_g}g</span>
					<button
						type="button"
						class="btn btn-danger no-print"
						onclick={() => handleRemoveIngredient(ingredient.id)}
					>
						Remove
					</button>
				{:else}
					<span class="muted">{ingredient.quantity_g}g</span>
				{/if}
			</li>
		{/each}
	</ul>

	{#if recipe.is_owner}
		<div class="no-print add-ingredient">
			<FoodSearchInput
				onSelect={handleAddIngredient}
				label="Add ingredient"
				exclude={(food) => recipe?.ingredients.some((i) => i.food_id === food.id) ?? false}
			/>
			{#if addingIngredient}<span class="muted">Adding…</span>{/if}
		</div>
		{#if editError}<p class="error">{editError}</p>{/if}
	{/if}

	<section class="proteins card">
		<h2>Protein</h2>
		{#if totalProtein}
			<p class="protein-line">
				<strong>Total: {totalProtein.amount.toFixed(1)}g</strong>
				{#if totalProtein.percent_drv !== null}
					<span class="muted">({totalProtein.percent_drv.toFixed(0)}% of daily target)</span>
				{/if}
			</p>
		{/if}
		{#if absorbedProtein && (absorbedProtein.diaas_absorbed_g !== null || absorbedProtein.pdcaas_absorbed_g !== null)}
			<p class="protein-line">
				<strong>Absorbed:</strong>
				{#if absorbedProtein.diaas_absorbed_g !== null}
					<span>
						DIAAS {absorbedProtein.diaas_absorbed_g.toFixed(1)}g
						{#if absorbedProtein.diaas_percent_drv !== null}
							<span class="muted">({absorbedProtein.diaas_percent_drv.toFixed(0)}%)</span>
						{/if}
					</span>
				{/if}
				{#if absorbedProtein.pdcaas_absorbed_g !== null}
					<span>
						PDCAAS {absorbedProtein.pdcaas_absorbed_g.toFixed(1)}g
						{#if absorbedProtein.pdcaas_percent_drv !== null}
							<span class="muted">({absorbedProtein.pdcaas_percent_drv.toFixed(0)}%)</span>
						{/if}
					</span>
				{/if}
			</p>
		{/if}

		{#if diaasScore}
			<details class="score-details">
				<summary>DIAAS breakdown ({diaasScore.score.toFixed(1)}%)</summary>
				<ScoreCard label="DIAAS" score={diaasScore} />
			</details>
		{:else if diaasUnavailableReason}
			<p class="alert">DIAAS score unavailable: {diaasUnavailableReason}</p>
		{/if}
		{#if pdcaasScore}
			<details class="score-details">
				<summary>PDCAAS breakdown ({pdcaasScore.score.toFixed(1)}%)</summary>
				<ScoreCard label="PDCAAS" score={pdcaasScore} />
			</details>
		{:else if pdcaasUnavailableReason}
			<p class="alert">PDCAAS score unavailable: {pdcaasUnavailableReason}</p>
		{/if}
	</section>

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
				<input
					type="email"
					bind:value={shareEmail}
					placeholder="Share with (email)"
					aria-label="Share with (email)"
					required
				/>
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
			<p class="muted">No comments yet. Be the first to weigh in.</p>
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
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.ingredients .muted {
		margin-left: var(--space-2);
	}
	.ingredients input[type='number'] {
		width: 5rem;
	}
	.print-only {
		display: none;
	}
	.add-ingredient {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
	}
	.edit-details-form {
		max-width: 24rem;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.edit-details-form .actions {
		display: flex;
		gap: var(--space-2);
	}
	.proteins {
		margin: var(--space-4) 0;
		max-width: 32rem;
	}
	.proteins h2 {
		margin-top: 0;
	}
	.protein-line {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
		margin: var(--space-1) 0;
	}
	.score-details {
		margin-top: var(--space-3);
	}
	.score-details summary {
		cursor: pointer;
		font-weight: var(--font-weight-medium);
	}
	.method-details {
		margin: var(--space-3) 0;
		max-width: 32rem;
	}
	.method-details summary {
		cursor: pointer;
		font-weight: var(--font-weight-medium);
	}
	.method-text {
		white-space: pre-wrap;
		margin: var(--space-2) 0 0;
	}
	.method-details textarea {
		font-family: inherit;
		resize: vertical;
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
		.print-only {
			display: inline;
		}
		/* method is worth having on a printed recipe to cook from — force it
		   open regardless of whether it was expanded on screen */
		.method-details summary {
			display: none;
		}
		.method-details > :not(summary) {
			display: block !important;
		}
	}
</style>
