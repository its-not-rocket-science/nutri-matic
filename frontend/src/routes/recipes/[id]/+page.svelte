<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import ImproveThis from '$lib/components/ImproveThis.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import StarRating from '$lib/components/StarRating.svelte';
	import TagEditor from '$lib/components/TagEditor.svelte';
	import { downloadCsv } from '$lib/csv';
	import type {
		AbsorbedProtein,
		Complement,
		Food,
		IngredientSuggestion,
		NutrientAmount,
		OptimizationSuggestion,
		Recipe,
		RecipeComment,
		RecipeIngredient,
		RecipeNutrientGap,
		RecipeRatingSummary,
		RecipeShare,
		Robustness,
		Score
	} from '$lib/types';

	const recipeId = Number(page.params.id);

	let recipe: Recipe | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let diaasUnavailableReason: string | null = $state(null);
	let pdcaasUnavailableReason: string | null = $state(null);
	let absorbedProtein: AbsorbedProtein | null = $state(null);
	let robustness: Robustness | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	const totalProtein = $derived(nutrients.find((n) => n.key === 'protein') ?? null);
	let nutrientGaps: RecipeNutrientGap[] = $state([]);
	// prompt 5.2 — complementary-ingredient and same-family ingredient-swap
	// suggestions, both keyed off this recipe's own gaps/protein score.
	// diaas is the default method here (matching diaasScore already being
	// this page's primary protein-quality figure) rather than exposing a
	// second method picker just for this card.
	let complement: Complement | null = $state(null);
	let ingredientSwaps: OptimizationSuggestion[] = $state([]);
	let addingComplementFoodId: number | null = $state(null);
	let applyingSwapKey: string | null = $state(null);

	// Provenance of a *stock* recipe's ingredient list — prompt section 6:
	// don't let a source_url attribution link imply ingredients were
	// scraped verbatim when they weren't. Three distinct cases, in
	// priority order:
	//   1. an educational_note means the list was deliberately adapted/
	//      composited for nutritional-analysis purposes (prompt section 7's
	//      generic muesli composite is the motivating example) — never a
	//      transcription of one specific real-world dish.
	//   2. a non-"manual" source_name means the ingredients were imported
	//      directly from structured recipe data at source_url.
	//   3. otherwise ("manual", no note) the list was hand-typed by a
	//      maintainer — source_url, if present, is only a "see something
	//      similar" reference link, not where the ingredients came from.
	// null for an ordinary (non-stock) recipe, which has no such claim to
	// make either way — its own optional source_url is shown plainly.
	type ProvenanceKind = 'adapted_composite' | 'structured_import' | 'manual_curated';
	const provenance = $derived.by((): { kind: ProvenanceKind; label: string; note: string } | null => {
		if (!recipe || !recipe.is_stock) return null;
		if (recipe.educational_note) {
			return { kind: 'adapted_composite', label: 'Adapted for analysis', note: recipe.educational_note };
		}
		if (recipe.source_name && recipe.source_name !== 'manual') {
			return {
				kind: 'structured_import',
				label: 'Structured-data import',
				note: 'This ingredient list was imported directly from the linked source page.'
			};
		}
		return {
			kind: 'manual_curated',
			label: 'Manually curated',
			note: recipe.source_url
				? 'This ingredient list was written by hand for this recipe, not scraped from the linked page — it’s shown for reference only.'
				: 'This ingredient list was written by hand for this recipe.'
		};
	});
	const provenanceBadgeClass: Record<ProvenanceKind, string> = {
		structured_import: 'badge-measured',
		manual_curated: 'badge-info',
		adapted_composite: 'badge-estimated'
	};

	// Per-ingredient match provenance (prompt section 8) — which
	// AliasRelationship (ingredient_aliases.py) resolved this ingredient,
	// shown as a badge next to it. Purely informational: this never
	// changes the ingredient's quantity or the recipe's nutrition numbers.
	const RELATIONSHIP_LABELS: Record<string, string> = {
		exact: 'Exact match',
		regional_equivalent: 'Regional equivalent',
		close_analogue: 'Close analogue',
		category_proxy: 'Category proxy',
		reviewed_substitution: 'Reviewed substitute'
	};
	const RELATIONSHIP_BADGE_CLASS: Record<string, string> = {
		exact: 'badge-measured',
		regional_equivalent: 'badge-measured',
		close_analogue: 'badge-info',
		category_proxy: 'badge-estimated',
		reviewed_substitution: 'badge-info'
	};
	function relationshipLabel(ingredient: RecipeIngredient): string | null {
		const rel = ingredient.provenance?.match_relationship;
		return rel ? (RELATIONSHIP_LABELS[rel] ?? rel) : null;
	}
	function relationshipBadgeClass(ingredient: RecipeIngredient): string {
		const rel = ingredient.provenance?.match_relationship;
		return (rel && RELATIONSHIP_BADGE_CLASS[rel]) || 'badge-info';
	}
	function confidenceWords(confidence: number | null | undefined): string {
		if (confidence === null || confidence === undefined) return 'unknown confidence';
		if (confidence >= 0.9) return 'high confidence';
		if (confidence >= 0.75) return 'moderate confidence';
		if (confidence >= 0.5) return 'low-to-moderate confidence';
		return 'low confidence';
	}
	// A compact hover tooltip rather than a permanent block of text, so an
	// approximate mapping's explanation is available without overwhelming
	// the default ingredient list (prompt section 6) — e.g. "Crumpet
	// represented using a plain English muffin nutrient profile. Close
	// analogue; moderate confidence."
	function relationshipTitle(ingredient: RecipeIngredient): string {
		const provenance = ingredient.provenance;
		if (!provenance) return '';
		const parts: string[] = [];
		if (provenance.match_rationale) parts.push(provenance.match_rationale);
		const label = relationshipLabel(ingredient);
		if (label) parts.push(`${label}; ${confidenceWords(provenance.match_confidence)}.`);
		if (provenance.match_used_fallback) {
			parts.push('Its preferred database match was unavailable, so this was resolved via fallback search.');
		}
		return parts.join(' ');
	}
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
			const [
				diaas,
				pdcaas,
				nutrientResult,
				absorbedResult,
				ratingResult,
				robustnessResult,
				gapsResult,
				complementResult,
				swapsResult
			] = await Promise.allSettled([
				api.scoreRecipe(recipeId, 'diaas'),
				api.scoreRecipe(recipeId, 'pdcaas'),
				api.getRecipeNutrients(recipeId),
				api.getRecipeAbsorbedProtein(recipeId),
				api.getRatings(recipeId),
				api.getRecipeRobustness(recipeId),
				api.getRecipeNutrientGaps(recipeId),
				api.complementRecipe(recipeId, 'diaas'),
				api.getIngredientSwaps(recipeId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			else diaasUnavailableReason = diaas.reason instanceof Error ? diaas.reason.message : String(diaas.reason);
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			else pdcaasUnavailableReason = pdcaas.reason instanceof Error ? pdcaas.reason.message : String(pdcaas.reason);
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
			if (absorbedResult.status === 'fulfilled') absorbedProtein = absorbedResult.value;
			if (ratingResult.status === 'fulfilled') ratings = ratingResult.value;
			if (robustnessResult.status === 'fulfilled') robustness = robustnessResult.value;
			if (gapsResult.status === 'fulfilled') nutrientGaps = gapsResult.value;
			if (complementResult.status === 'fulfilled') complement = complementResult.value;
			if (swapsResult.status === 'fulfilled') ingredientSwaps = swapsResult.value;
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

	// Shared refresh after any ingredient-list mutation (add/swap) — recomputes
	// everything downstream of the ingredient list: nutrient totals, gaps,
	// the complement/swap suggestions themselves (adding or swapping an
	// ingredient can change the limiting amino acid or the worst gap), and
	// the protein scores/absorbed-protein/robustness cards, which otherwise
	// keep showing pre-mutation figures right next to a suggestion that was
	// just applied.
	async function refreshRecipeDerivedData() {
		const [nutrientResult, gapsResult, complementResult, swapsResult, diaasResult, pdcaasResult, absorbedResult, robustnessResult] =
			await Promise.allSettled([
				api.getRecipeNutrients(recipeId),
				api.getRecipeNutrientGaps(recipeId),
				api.complementRecipe(recipeId, 'diaas'),
				api.getIngredientSwaps(recipeId),
				api.scoreRecipe(recipeId, 'diaas'),
				api.scoreRecipe(recipeId, 'pdcaas'),
				api.getRecipeAbsorbedProtein(recipeId),
				api.getRecipeRobustness(recipeId)
			]);
		if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
		if (gapsResult.status === 'fulfilled') nutrientGaps = gapsResult.value;
		if (complementResult.status === 'fulfilled') complement = complementResult.value;
		if (swapsResult.status === 'fulfilled') ingredientSwaps = swapsResult.value;
		if (diaasResult.status === 'fulfilled') {
			diaasScore = diaasResult.value;
			diaasUnavailableReason = null;
		} else {
			diaasUnavailableReason = diaasResult.reason instanceof Error ? diaasResult.reason.message : String(diaasResult.reason);
		}
		if (pdcaasResult.status === 'fulfilled') {
			pdcaasScore = pdcaasResult.value;
			pdcaasUnavailableReason = null;
		} else {
			pdcaasUnavailableReason = pdcaasResult.reason instanceof Error ? pdcaasResult.reason.message : String(pdcaasResult.reason);
		}
		if (absorbedResult.status === 'fulfilled') absorbedProtein = absorbedResult.value;
		if (robustnessResult.status === 'fulfilled') robustness = robustnessResult.value;
	}

	// "Improve this recipe" (prompt 10) — the recipe's own ingredients stand
	// in for "the current meal" (see routers/recommendations.py's
	// recipe_id scope), so applying a suggestion just adds it as a new
	// ingredient via the same addIngredient the manual "Add ingredient"
	// form already uses, then refreshes the nutrient totals it affects.
	async function applyIngredientSuggestionToRecipe(s: IngredientSuggestion) {
		recipe = await api.addIngredient(recipeId, s.food_id, s.quantity_g);
		await refreshRecipeDerivedData();
	}

	// Prompt 5.2a — complementary-ingredient CTA: add the suggested food at
	// the same PAIRING_QUANTITY_G the backend scored it at (complement.food_id
	// isn't already in the recipe, per suggest_complements' own exclusion).
	async function applyComplementSuggestion(foodId: number, quantityG: number) {
		addingComplementFoodId = foodId;
		try {
			recipe = await api.addIngredient(recipeId, foodId, quantityG);
			await refreshRecipeDerivedData();
		} catch (e) {
			editError = e instanceof Error ? e.message : String(e);
		} finally {
			addingComplementFoodId = null;
		}
	}

	// Prompt 5.2b — ingredient-swap CTA: add the suggestion's food first,
	// then remove the replaced ingredient — deliberately in that order, not
	// remove-then-add. If the add fails (e.g. a stale suggestion whose food
	// is already an ingredient, which 409s), nothing has been removed yet
	// and the recipe is untouched; the alternative ordering would have
	// already deleted the original ingredient with no way back. Matches the
	// existing recipe ingredient by food_id (replaces_food_id) rather than
	// ingredient row id, since OptimizationSuggestionOut only carries the
	// food id.
	async function applyIngredientSwap(s: OptimizationSuggestion) {
		if (s.replaces_food_id == null || s.food_id == null || s.quantity_g == null) return;
		const key = `${s.replaces_food_id}-${s.food_id}`;
		applyingSwapKey = key;
		try {
			const existing = recipe?.ingredients.find((i) => i.food_id === s.replaces_food_id);
			recipe = await api.addIngredient(recipeId, s.food_id, s.quantity_g);
			if (existing) {
				recipe = await api.removeIngredient(recipeId, existing.id);
			}
			await refreshRecipeDerivedData();
		} catch (e) {
			editError = e instanceof Error ? e.message : String(e);
		} finally {
			applyingSwapKey = null;
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
		{#if recipe.is_stock && provenance}
			<p class="muted provenance-note">
				<span class="badge {provenanceBadgeClass[provenance.kind]}">{provenance.label}</span>
				{provenance.note}
				{#if recipe.source_url}
					<a href={recipe.source_url} target="_blank" rel="noopener noreferrer">
						{provenance.kind === 'structured_import' ? 'View source' : 'View similar recipe'}
					</a>
				{/if}
			</p>
		{:else if recipe.source_url}
			<p class="muted">
				Source: <a href={recipe.source_url} target="_blank" rel="noopener noreferrer">{recipe.source_url}</a>
			</p>
		{/if}
		{#if recipe.is_stock && (recipe.unresolved_ingredients.length > 0 || (recipe.match_coverage_lines ?? 1) < 1)}
			<p class="alert data-quality-warning">
				Data quality: {recipe.unresolved_ingredients.length} ingredient line{recipe.unresolved_ingredients
					.length === 1
					? ''
					: 's'} from the original source couldn't be confidently matched to a food and
				{recipe.unresolved_ingredients.length === 1 ? 'is' : 'are'} excluded from the analysis below{#if recipe.match_coverage_lines !== null}
					&nbsp;({Math.round(recipe.match_coverage_lines * 100)}% of ingredient lines matched){/if}.
				{#if recipe.unresolved_ingredients.length > 0}
					<span class="unresolved-list">Unmatched: {recipe.unresolved_ingredients.join('; ')}</span>
				{/if}
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

	{#if nutrientGaps.length > 0}
		<section class="card nutrient-gaps">
			<h2>Key nutrient shortfalls <span class="muted">(per serving)</span></h2>
			<p class="muted field-note">
				This recipe's most significant gaps, one serving compared against a typical daily
				target — not a claim this recipe should cover a whole day on its own, just where it
				falls short of one.
			</p>
			<ul class="entries">
				{#each nutrientGaps as gap (gap.key)}
					<li>
						<span class="gap-name">{gap.name}</span>
						<span class="muted">
							{gap.consumed_amount !== null
								? `${gap.consumed_amount < 10 ? gap.consumed_amount.toFixed(2) : gap.consumed_amount.toFixed(0)}${gap.unit}`
								: ''}
							{#if gap.percent_shortfall !== null}
								&middot; {gap.percent_shortfall.toFixed(0)}% short of target
							{/if}
						</span>
						<span class="badge {gap.status === 'below_target' ? 'badge-estimated' : 'badge-info'}">
							{gap.status === 'below_target' ? 'below target' : 'near target'}
						</span>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if recipe.is_owner && complement && complement.suggestions.length > 0}
		<section class="card complement-suggestions">
			<h2>Complementary ingredients</h2>
			<p class="muted field-note">
				This recipe's limiting amino acid is <strong>{complement.limiting_amino_acid}</strong>. Adding
				one of these would raise the combined protein score.
			</p>
			<ul class="entries">
				{#each complement.suggestions as s (s.food_id)}
					<li>
						<a href="/foods/{s.food_id}">{s.food_name}</a>
						<span class="muted">+{s.score_improvement.toFixed(2)} score</span>
						<button
							type="button"
							class="btn btn-secondary no-print"
							disabled={addingComplementFoodId === s.food_id}
							onclick={() => applyComplementSuggestion(s.food_id, 100)}
						>
							{addingComplementFoodId === s.food_id ? 'Adding…' : 'Add to recipe'}
						</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if recipe.is_owner && ingredientSwaps.length > 0}
		<section class="card ingredient-swaps">
			<h2>Ingredient swaps</h2>
			<p class="muted field-note">
				Swapping these would improve this recipe's biggest nutrient shortfall.
			</p>
			<ul class="entries">
				{#each ingredientSwaps as s (`${s.replaces_food_id}-${s.food_id}`)}
					<li>
						<span>
							Replace <strong>{s.replaces_food_name}</strong> with <strong>{s.food_name}</strong>
						</span>
						<span class="muted">
							{s.before_percent_drv.toFixed(0)}% &rarr; {s.after_percent_drv.toFixed(0)}% of target
						</span>
						<button
							type="button"
							class="btn btn-secondary no-print"
							disabled={applyingSwapKey === `${s.replaces_food_id}-${s.food_id}`}
							onclick={() => applyIngredientSwap(s)}
						>
							{applyingSwapKey === `${s.replaces_food_id}-${s.food_id}` ? 'Swapping…' : 'Apply swap'}
						</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	<ul class="ingredients">
		{#each recipe.ingredients as ingredient (ingredient.id)}
			<li>
				<a href="/foods/{ingredient.food_id}">{ingredient.food_name}</a>
				{#if relationshipLabel(ingredient)}
					<span
						class="badge {relationshipBadgeClass(ingredient)} no-print"
						title={relationshipTitle(ingredient)}
					>
						{relationshipLabel(ingredient)}
					</span>
				{/if}
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
						{#if absorbedProtein.diaas_coverage_fraction !== null && absorbedProtein.diaas_coverage_fraction < 1}
							<span class="badge badge-info" title="Some ingredients lack amino acid data and were excluded"
								>partial — {(absorbedProtein.diaas_coverage_fraction * 100).toFixed(0)}% coverage</span
							>
						{/if}
					</span>
				{/if}
				{#if absorbedProtein.pdcaas_absorbed_g !== null}
					<span>
						PDCAAS {absorbedProtein.pdcaas_absorbed_g.toFixed(1)}g
						{#if absorbedProtein.pdcaas_percent_drv !== null}
							<span class="muted">({absorbedProtein.pdcaas_percent_drv.toFixed(0)}%)</span>
						{/if}
						{#if absorbedProtein.pdcaas_coverage_fraction !== null && absorbedProtein.pdcaas_coverage_fraction < 1}
							<span class="badge badge-info" title="Some ingredients lack amino acid data and were excluded"
								>partial — {(absorbedProtein.pdcaas_coverage_fraction * 100).toFixed(0)}% coverage</span
							>
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

	{#if robustness}
		<section class="card robustness">
			<h2>Nutritional robustness</h2>
			<p class="muted robustness-caveat">
				How stable this recipe's calculated nutrition is when ingredient quantities vary within
				realistic uncertainty — not a health score, and not a claim about the source recipe itself.
			</p>
			<p class="robustness-overall">
				<strong>Overall: {robustness.overall_rating !== null ? `${robustness.overall_rating}/5` : 'not rated'}</strong>
			</p>
			<p>{robustness.overall_explanation}</p>
			<details class="score-details">
				<summary>Per-nutrient breakdown</summary>
				<ul class="robustness-metrics">
					{#each Object.entries(robustness.metrics) as [key, metric] (key)}
						<li>
							<strong>{key.replaceAll('_', ' ')}:</strong>
							{metric.display_rating !== null ? `${metric.display_rating}/5` : 'not calculated'}
							{#if metric.not_calculated_reason === null && metric.coverage_fraction !== null && metric.coverage_fraction < 1}
								<span
									class="badge badge-info"
									title="Some ingredients lack amino acid data and were excluded from this metric"
									>partial — {(metric.coverage_fraction * 100).toFixed(0)}% coverage</span
								>
							{/if}
							<br />
							<span class="muted">
								{metric.not_calculated_reason ?? metric.explanation}
							</span>
							{#if metric.excluded_foods.length > 0}
								<br />
								<span class="muted">Excluded: {metric.excluded_foods.map((f) => f.name).join(', ')}</span>
							{/if}
						</li>
					{/each}
				</ul>
			</details>
		</section>
	{/if}

	<NutrientBars {nutrients} per="per serving" />

	{#if recipe.is_owner}
		<ImproveThis
			title="Improve this recipe"
			scope={{ kind: 'recipe', recipeId, servings: recipe.servings }}
			targetDescription="this recipe"
			allowRecipes={false}
			onApplyIngredient={applyIngredientSuggestionToRecipe}
		/>
	{/if}

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
	.nutrient-gaps {
		margin-bottom: var(--space-5);
	}
	.nutrient-gaps .field-note {
		margin: var(--space-1) 0 var(--space-3);
	}
	.nutrient-gaps .entries {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.nutrient-gaps .entries li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-1) 0;
	}
	.nutrient-gaps .gap-name {
		font-weight: 600;
	}
	.complement-suggestions,
	.ingredient-swaps {
		margin-bottom: var(--space-5);
	}
	.complement-suggestions .field-note,
	.ingredient-swaps .field-note {
		margin: var(--space-1) 0 var(--space-3);
	}
	.complement-suggestions .entries,
	.ingredient-swaps .entries {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.complement-suggestions .entries li,
	.ingredient-swaps .entries li {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding: var(--space-1) 0;
	}
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
	.data-quality-warning {
		max-width: 32rem;
	}
	.provenance-note {
		max-width: 32rem;
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
	}
	.unresolved-list {
		display: block;
		font-size: 0.85em;
	}
	.robustness {
		margin: var(--space-4) 0;
		max-width: 32rem;
	}
	.robustness h2 {
		margin-top: 0;
	}
	.robustness-caveat {
		font-size: 0.85em;
	}
	.robustness-overall {
		margin-bottom: var(--space-1);
	}
	.robustness-metrics {
		list-style: none;
		padding: 0;
		margin: var(--space-2) 0 0;
	}
	.robustness-metrics li {
		padding: var(--space-1) 0;
		text-transform: capitalize;
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
