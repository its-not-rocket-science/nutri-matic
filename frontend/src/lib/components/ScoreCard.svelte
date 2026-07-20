<script lang="ts">
	import InfoLink from '$lib/components/InfoLink.svelte';
	import { AMINO_ACID_LABELS, type Score } from '$lib/types';

	let { label, score }: { label: string; score: Score } = $props();
</script>

<section class="card">
	<h2>
		{label}: {score.score.toFixed(1)}%
		{#if score.digestibility_source}
			<span
				class="badge badge-{score.digestibility_source}"
				title={score.digestibility_source === 'estimated'
					? 'Digestibility is a broad food-category estimate, not measured for this specific food'
					: 'Digestibility is a published value for this specific food or a close equivalent'}
				>{score.digestibility_source}</span
			>
		{/if}
		{#if score.is_partial}
			<span
				class="badge badge-info"
				title="Some ingredients lack amino acid data and were excluded from this score"
				>partial — {(score.coverage_fraction * 100).toFixed(0)}% coverage</span
			>
		{/if}
		<InfoLink href="/methodology#protein-quality" label="How DIAAS/PDCAAS scores are computed" />
	</h2>
	<p class="muted">
		Reference pattern: {score.pattern_used} · Limiting amino acid: <strong
			>{AMINO_ACID_LABELS[score.limiting_amino_acid as keyof typeof AMINO_ACID_LABELS]}</strong
		>
	</p>
	{#if score.is_partial}
		<p class="muted partial-note">
			Computed from ingredients with complete amino acid data only. Excluded ({(
				(1 - score.coverage_fraction) *
				100
			).toFixed(0)}% of protein): {score.excluded_ingredients.map((i) => i.name).join(', ')}.
		</p>
	{/if}
	<ul class="bars">
		{#each Object.entries(score.per_aa_ratios) as [aa, ratio] (aa)}
			<li class:limiting={aa === score.limiting_amino_acid}>
				<span class="aa-name">{AMINO_ACID_LABELS[aa as keyof typeof AMINO_ACID_LABELS]}</span>
				<span class="bar-track">
					<span class="bar-fill" style="width: {Math.min(ratio, 150) / 1.5}%"></span>
				</span>
				<span class="aa-value">{ratio.toFixed(0)}%</span>
			</li>
		{/each}
	</ul>
</section>

<style>
	.badge {
		vertical-align: middle;
		margin-left: var(--space-2);
	}
	.partial-note {
		margin-top: 0;
	}
	.bars {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.bars li {
		display: grid;
		grid-template-columns: 12rem 1fr 6rem;
		align-items: center;
		gap: var(--space-3);
	}
	.bars .aa-value {
		white-space: nowrap;
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	@media (max-width: 30rem) {
		.bars li {
			grid-template-columns: 1fr auto;
			row-gap: var(--space-1);
		}
		.bar-track {
			grid-column: 1 / -1;
		}
	}
	.bars li.limiting .aa-name,
	.bars li.limiting .aa-value {
		font-weight: var(--font-weight-bold);
		color: var(--color-danger);
	}
	.bar-track {
		background: var(--color-surface-muted);
		border-radius: var(--radius-sm);
		height: 0.75rem;
		overflow: hidden;
	}
	.bar-fill {
		display: block;
		height: 100%;
		background: var(--color-success);
	}
	.limiting .bar-fill {
		background: var(--color-danger);
	}
</style>
