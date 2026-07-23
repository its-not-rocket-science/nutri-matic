<script lang="ts">
	import { nutrientLabel } from '$lib/nutrientLabels';

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
		applyLabel?: string;
		applying?: boolean;
		onApply?: (() => void) | null;
	} = $props();
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
</style>
