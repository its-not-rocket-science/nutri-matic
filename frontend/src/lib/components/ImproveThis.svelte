<script lang="ts">
	import { api, type RecommendationScope } from '$lib/api';
	import RecommendationCard from '$lib/components/RecommendationCard.svelte';
	import { safetyWarningMessage } from '$lib/recommendationSafety';
	import type { IngredientSuggestion, RecipeSuggestion, SubstitutionSuggestion } from '$lib/types';

	/** Restrained "Improve this…" panel used on the diary day, meal-plan
	 * day/multi-day-summary, and recipe-detail pages (prompt 10). Fetches
	 * nothing until the user opens it — never overwhelms the page by
	 * default — and every apply action is confirmed first, since it can
	 * change a diary or plan (prompt 10's explicit requirement).
	 *
	 * Applying and re-fetching is delegated to the parent via
	 * onApplyIngredient/onApplyRecipe/onApplySubstitution because only the
	 * parent knows where a plan-level or day-level (as opposed to a single
	 * meal's) addition should land — the existing "Optimize this plan"
	 * feature on the meal-plan page already established that convention
	 * (adds go wherever the entry form's date/meal is currently set), and
	 * this reuses it rather than inventing a second one. */

	// Mirrors recommend_recipes.GOAL_PRESETS — a UI grouping, not a
	// nutritional-truth value, so a small local copy here is fine; keep the
	// two in sync if the backend's preset keys ever change.
	const GOAL_PRESETS: { key: string; label: string; nutrientKeys: string[] | null }[] = [
		{ key: 'overall_balance', label: 'Overall balance', nutrientKeys: null },
		{ key: 'fibre', label: 'Fibre', nutrientKeys: ['fiber_total'] },
		{ key: 'iron_folate', label: 'Iron & folate', nutrientKeys: ['iron', 'folate'] },
		{ key: 'calcium', label: 'Calcium', nutrientKeys: ['calcium'] },
		{ key: 'protein_quality', label: 'Protein quality', nutrientKeys: ['protein'] }
	];

	let {
		title,
		scope,
		targetDescription,
		allowRecipes = true,
		substitutionEntryId = null,
		substitutionSource = 'diary',
		onApplyIngredient,
		onApplyRecipe = null,
		onApplySubstitution = null
	}: {
		title: string;
		scope: RecommendationScope;
		/** Used only in the confirmation prompt, e.g. "today's lunch" or
		 * "this recipe" — describes where an applied suggestion will land. */
		targetDescription: string;
		allowRecipes?: boolean;
		substitutionEntryId?: number | null;
		substitutionSource?: 'diary' | 'meal_plan';
		onApplyIngredient: (s: IngredientSuggestion) => Promise<void>;
		onApplyRecipe?: ((s: RecipeSuggestion) => Promise<void>) | null;
		onApplySubstitution?: ((s: SubstitutionSuggestion) => Promise<void>) | null;
	} = $props();

	const allowSubstitution = $derived(substitutionEntryId !== null && onApplySubstitution !== null);

	let open = $state(false);
	let mode: 'ingredients' | 'recipes' | 'substitution' = $state('ingredients');
	let goalKey = $state('overall_balance');
	let maxEnergy = $state<number | null>(null);
	let loading = $state(false);
	let error: string | null = $state(null);
	let applyingKey: string | null = $state(null);

	let ingredientSuggestions: IngredientSuggestion[] = $state([]);
	let recipeSuggestions: RecipeSuggestion[] = $state([]);
	let substitutionSuggestions: SubstitutionSuggestion[] = $state([]);
	let hasFetchedOnce = $state(false);
	// standing, profile-level caveats (prompt 11) — shown once per panel,
	// never repeated on every card. disabledReason set means the engine
	// was disabled outright for this profile (e.g. under 18) rather than
	// guessing; suggestions are always empty in that case.
	let warnings: string[] = $state([]);
	let disabledReason: string | null = $state(null);

	function priorityNutrients(): string[] | undefined {
		const preset = GOAL_PRESETS.find((g) => g.key === goalKey);
		return preset?.nutrientKeys ?? undefined;
	}

	async function fetchSuggestions() {
		error = null;
		loading = true;
		try {
			if (mode === 'ingredients') {
				const res = await api.getIngredientSuggestions(scope, {
					priorityNutrients: priorityNutrients(),
					maxAdditionalEnergy: maxEnergy ?? undefined
				});
				ingredientSuggestions = res.suggestions;
				warnings = res.warnings;
				disabledReason = res.disabled_reason;
			} else if (mode === 'recipes') {
				const res = await api.getRecipeSuggestions(scope, {
					goal: goalKey,
					maxAdditionalEnergy: maxEnergy ?? undefined
				});
				recipeSuggestions = res.suggestions;
				warnings = res.warnings;
				disabledReason = res.disabled_reason;
			} else if (substitutionEntryId !== null) {
				const res = await api.getSubstitutionSuggestions(substitutionEntryId, substitutionSource, {
					priorityNutrients: priorityNutrients()
				});
				substitutionSuggestions = res.suggestions;
				warnings = res.warnings;
				disabledReason = res.disabled_reason;
			}
			hasFetchedOnce = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function togglePanel() {
		open = !open;
		if (open) fetchSuggestions();
	}

	function setMode(m: typeof mode) {
		mode = m;
		fetchSuggestions();
	}

	async function handleApplyIngredient(s: IngredientSuggestion) {
		if (!confirm(`Add ${s.quantity_g}g of ${s.food_name} to ${targetDescription}?`)) return;
		error = null;
		applyingKey = `ingredient-${s.food_id}`;
		try {
			await onApplyIngredient(s);
			await fetchSuggestions();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			applyingKey = null;
		}
	}

	async function handleApplyRecipe(s: RecipeSuggestion) {
		if (!onApplyRecipe) return;
		if (!confirm(`Add ${s.suggested_servings} serving(s) of ${s.recipe_name} to ${targetDescription}?`)) return;
		error = null;
		applyingKey = `recipe-${s.recipe_id}`;
		try {
			await onApplyRecipe(s);
			await fetchSuggestions();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			applyingKey = null;
		}
	}

	async function handleApplySubstitution(s: SubstitutionSuggestion) {
		if (!onApplySubstitution) return;
		if (
			!confirm(
				`Replace ${s.current_recipe_name} with ${s.replacement_servings} serving(s) of ${s.replacement_recipe_name}?`
			)
		)
			return;
		error = null;
		applyingKey = `sub-${s.replacement_recipe_id}`;
		try {
			await onApplySubstitution(s);
			await fetchSuggestions();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			applyingKey = null;
		}
	}

	function coverageNote(dataCoverage: number, isStock: boolean, matchCoverageLines: number | null): string | null {
		const notes: string[] = [];
		if (dataCoverage < 1) notes.push(`approximate — nutrient data available for ${Math.round(dataCoverage * 100)}% of what this recommendation is based on`);
		if (!isStock) notes.push('a personal recipe, not a reviewed stock recipe');
		if (matchCoverageLines !== null && matchCoverageLines < 1) {
			notes.push(`${Math.round(matchCoverageLines * 100)}% of ingredients matched to exact nutrient data`);
		}
		return notes.length > 0 ? notes.join('; ') : null;
	}
</script>

<div class="improve-this no-print">
	<button type="button" onclick={togglePanel} aria-expanded={open}>
		{open ? 'Hide' : title}
	</button>

	{#if open}
		<div class="panel">
			{#if error}
				<p class="error">{error}</p>
			{/if}

			{#if loading && !hasFetchedOnce}
				<p class="muted">Looking for improvements…</p>
			{:else if hasFetchedOnce && disabledReason}
				<p class="disabled-notice">{disabledReason}</p>
			{:else}
				<div class="panel-controls">
					<label>
						Priority
						<select bind:value={goalKey} onchange={fetchSuggestions}>
							{#each GOAL_PRESETS as preset (preset.key)}
								<option value={preset.key}>{preset.label}</option>
							{/each}
						</select>
					</label>
					<label>
						Max extra energy (kcal)
						<input type="number" min="0" step="10" placeholder="no limit" bind:value={maxEnergy} onchange={fetchSuggestions} />
					</label>
				</div>

				<div class="mode-tabs" role="tablist">
					<button type="button" role="tab" aria-selected={mode === 'ingredients'} onclick={() => setMode('ingredients')}>
						Add foods
					</button>
					{#if allowRecipes}
						<button type="button" role="tab" aria-selected={mode === 'recipes'} onclick={() => setMode('recipes')}>
							Suggest recipes
						</button>
					{/if}
					{#if allowSubstitution}
						<button type="button" role="tab" aria-selected={mode === 'substitution'} onclick={() => setMode('substitution')}>
							Replace this meal
						</button>
					{/if}
				</div>

				{#if warnings.length > 0}
					<details class="safety-notice">
						<summary>About these suggestions</summary>
						<ul>
							{#each warnings as code (code)}
								<li>{safetyWarningMessage(code)}</li>
							{/each}
						</ul>
					</details>
				{/if}
			{/if}

			{#if !hasFetchedOnce || disabledReason}
				<!-- nothing further to show: either still loading, or disabled above -->
			{:else if loading}
				<p class="muted">Looking for improvements…</p>
			{:else if mode === 'ingredients'}
				{#if ingredientSuggestions.length === 0}
					<p class="muted">No safe or useful addition found for the current priorities.</p>
				{:else}
					<ul class="recommendation-list">
						{#each ingredientSuggestions as s (s.food_id)}
							<RecommendationCard
								title={s.food_name}
								servingLabel={`${s.quantity_g}g`}
								energyLabel={s.extra_energy_kcal > 0 ? `+${Math.round(s.extra_energy_kcal)}kcal` : null}
								benefitKeys={s.nutrients_improved}
								remainingShortfallKeys={s.remaining_shortfalls}
								warningKeys={s.new_warnings}
								coverageNote={coverageNote(s.data_coverage, true, null)}
								explanation={s.explanation}
								applying={applyingKey === `ingredient-${s.food_id}`}
								onApply={() => handleApplyIngredient(s)}
							/>
						{/each}
					</ul>
				{/if}
			{:else if mode === 'recipes'}
				{#if recipeSuggestions.length === 0}
					<p class="muted">No suitable recipe found for the current priorities.</p>
				{:else}
					<ul class="recommendation-list">
						{#each recipeSuggestions as s (s.recipe_id)}
							<RecommendationCard
								title={s.recipe_name}
								servingLabel={`${s.suggested_servings} serving(s)`}
								energyLabel={s.energy_added_kcal > 0 ? `+${Math.round(s.energy_added_kcal)}kcal` : null}
								benefitKeys={s.nutrients_improved}
								remainingShortfallKeys={s.remaining_shortfalls}
								warningKeys={s.new_warnings}
								coverageNote={s.robustness_note ?? coverageNote(1, s.is_stock, s.match_coverage_lines)}
								explanation={s.explanation}
								applying={applyingKey === `recipe-${s.recipe_id}`}
								onApply={onApplyRecipe ? () => handleApplyRecipe(s) : null}
							/>
						{/each}
					</ul>
				{/if}
			{:else if mode === 'substitution'}
				{#if substitutionSuggestions.length === 0}
					<p class="muted">No suitable replacement found for the current priorities.</p>
				{:else}
					<ul class="recommendation-list">
						{#each substitutionSuggestions as s (s.replacement_recipe_id)}
							<RecommendationCard
								title={`${s.replacement_recipe_name} (instead of ${s.current_recipe_name})`}
								servingLabel={`${s.replacement_servings} serving(s)`}
								energyLabel={`${s.energy_difference_kcal >= 0 ? '+' : ''}${Math.round(s.energy_difference_kcal)}kcal`}
								benefitKeys={[]}
								remainingShortfallKeys={s.remaining_shortfalls}
								warningKeys={s.new_warnings}
								coverageNote={s.provenance_note ?? coverageNote(1, s.is_stock, s.match_coverage_lines)}
								explanation={s.explanation}
								applying={applyingKey === `sub-${s.replacement_recipe_id}`}
								onApply={onApplySubstitution ? () => handleApplySubstitution(s) : null}
							/>
						{/each}
					</ul>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.improve-this {
		margin: var(--space-3) 0;
	}
	.panel {
		margin-top: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--color-border, #ccc);
		border-radius: var(--radius-sm);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.panel-controls {
		display: flex;
		gap: var(--space-4);
		flex-wrap: wrap;
	}
	.mode-tabs {
		display: flex;
		gap: var(--space-2);
	}
	.mode-tabs button[aria-selected='true'] {
		font-weight: var(--font-weight-bold);
		text-decoration: underline;
	}
	.recommendation-list {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.disabled-notice {
		margin: 0;
		color: var(--color-warning);
	}
	.safety-notice {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted, inherit);
	}
	.safety-notice summary {
		cursor: pointer;
	}
	.safety-notice ul {
		margin: var(--space-1) 0 0;
		padding-left: var(--space-4);
	}
</style>
