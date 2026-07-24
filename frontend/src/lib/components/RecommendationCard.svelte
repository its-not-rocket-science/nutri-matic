<script lang="ts">
	import { nutrientLabel } from '$lib/nutrientLabels';
	import type { ScoreBreakdown } from '$lib/types';

	/** Generic rendering of one nutrient-gap recommendation — an ingredient,
	 * a recipe, or a substitution proposal — normalised to one shape so the
	 * three suggestion modes share one card layout (prompt 10). Never shows
	 * "deficiency"/"treats X" wording: benefits are phrased as "helps close
	 * the remaining Y gap", warnings as "pushes Z above its preferred
	 * range/upper limit" — matching docs/nutrient-gap-recommendations.md's
	 * never-diagnose rule. */
	let {
		title,
		servingLabel,
		energyLabel = null,
		benefitKeys,
		remainingShortfallKeys,
		warningKeys,
		coverageNote = null,
		explanation,
		scoreBreakdown = null,
		applyLabel = 'Add',
		applying = false,
		onApply = null
	}: {
		title: string;
		servingLabel: string;
		energyLabel?: string | null;
		benefitKeys: string[];
		remainingShortfallKeys: string[];
		warningKeys: string[];
		coverageNote?: string | null;
		explanation: string;
		scoreBreakdown?: ScoreBreakdown | null;
		applyLabel?: string;
		applying?: boolean;
		onApply?: (() => void) | null;
	} = $props();

	// Hardening prompt 3's "why this ranked here" — every named term with
	// a real (nonzero) contribution, rounded only for display. Order
	// matches the engine's own conceptual formula (benefits first, then
	// penalties) rather than declaration order, so a reader sees the
	// biggest-picture terms first.
	const BREAKDOWN_ROWS: { key: keyof ScoreBreakdown; label: string; sign: '+' | '−' }[] = [
		{ key: 'weighted_gap_reduction', label: 'Closes tracked nutrient gaps', sign: '+' },
		{ key: 'multi_nutrient_bonus', label: 'Bonus for improving several nutrients at once', sign: '+' },
		{ key: 'protein_quality_benefit', label: 'Improves protein quality', sign: '+' },
		{ key: 'dietary_fit', label: 'Fits dietary preferences', sign: '+' },
		{ key: 'practicality', label: 'Practical serving size', sign: '+' },
		{ key: 'upper_limit_penalty', label: 'Pushes a nutrient over its upper limit', sign: '−' },
		{ key: 'above_preferred_penalty', label: 'Pushes a nutrient above its preferred range', sign: '−' },
		{ key: 'energy_overshoot_penalty', label: 'Exceeds the requested extra-energy limit', sign: '−' },
		{ key: 'uncertainty_penalty', label: 'Lower-confidence or incomplete data', sign: '−' },
		{ key: 'implausible_serving_penalty', label: 'Unusual serving size', sign: '−' }
	];

	function breakdownRows(breakdown: ScoreBreakdown) {
		return BREAKDOWN_ROWS.map((row) => ({ ...row, value: breakdown[row.key] as number })).filter(
			(row) => Math.abs(row.value) > 0.005
		);
	}
</script>

<li class="recommendation-card">
	<div class="card-head">
		<strong>{title}</strong>
		<span class="muted">{servingLabel}{energyLabel ? ` — ${energyLabel}` : ''}</span>
	</div>

	{#if benefitKeys.length > 0}
		<p class="benefits">
			Helps close the remaining {benefitKeys.map(nutrientLabel).join(', ')} gap{benefitKeys.length > 1
				? 's'
				: ''}.
		</p>
	{/if}

	{#if warningKeys.length > 0}
		<p class="warning">
			⚠ Pushes {warningKeys.map(nutrientLabel).join(', ')} above its preferred range or upper limit.
		</p>
	{/if}

	{#if coverageNote}
		<p class="muted coverage-note">{coverageNote}</p>
	{/if}

	<details class="card-detail">
		<summary>Explanation &amp; remaining gaps</summary>
		<p>{explanation}</p>
		{#if remainingShortfallKeys.length > 0}
			<p class="muted">
				Still below/near target after this: {remainingShortfallKeys.map(nutrientLabel).join(', ')}.
			</p>
		{/if}
	</details>

	{#if scoreBreakdown}
		<details class="card-detail">
			<summary>Why this ranked here</summary>
			<ul class="score-breakdown">
				{#each breakdownRows(scoreBreakdown) as row (row.key)}
					<li>
						<span>{row.label}</span>
						<span class="muted">{row.sign}{Math.abs(row.value).toFixed(2)}</span>
					</li>
				{/each}
			</ul>
			<p class="muted">Total score: {scoreBreakdown.total.toFixed(2)}</p>
		</details>
	{/if}

	{#if onApply}
		<button type="button" onclick={onApply} disabled={applying}>
			{applying ? 'Adding…' : applyLabel}
		</button>
	{/if}
</li>

<style>
	.recommendation-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-3);
		border: 1px solid var(--color-border, #ccc);
		border-radius: var(--radius-sm);
	}
	.card-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.benefits {
		color: var(--color-success);
		margin: 0;
	}
	.warning {
		color: var(--color-warning);
		margin: 0;
	}
	.coverage-note {
		margin: 0;
		font-size: var(--font-size-sm);
	}
	.card-detail {
		font-size: var(--font-size-sm);
	}
	.card-detail summary {
		cursor: pointer;
	}
	.score-breakdown {
		list-style: none;
		margin: var(--space-1) 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.score-breakdown li {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
	}
</style>
