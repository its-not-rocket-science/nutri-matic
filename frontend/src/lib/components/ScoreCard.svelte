<script lang="ts">
	import InfoLink from '$lib/components/InfoLink.svelte';
	import { AMINO_ACID_LABELS, type Score } from '$lib/types';

	let { label, score }: { label: string; score: Score } = $props();
</script>

<section>
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
		<InfoLink href="/methodology#protein-quality" label="How DIAAS/PDCAAS scores are computed" />
	</h2>
	<p class="muted">
		Reference pattern: {score.pattern_used} · Limiting amino acid: <strong
			>{AMINO_ACID_LABELS[score.limiting_amino_acid as keyof typeof AMINO_ACID_LABELS]}</strong
		>
	</p>
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
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.badge {
		display: inline-block;
		font-size: 0.6em;
		font-weight: normal;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		padding: 0.15em 0.5em;
		border-radius: 999px;
		vertical-align: middle;
		margin-left: 0.4em;
	}
	.badge-measured {
		background: #dff0d8;
		color: #2d6a2d;
	}
	.badge-estimated {
		background: #fdf3d0;
		color: #8a6d00;
	}
	.bars {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.bars li {
		display: grid;
		grid-template-columns: 12rem 1fr auto;
		align-items: center;
		gap: 0.5rem;
	}
	.bars .aa-value {
		white-space: nowrap;
	}
	.bars li.limiting .aa-name,
	.bars li.limiting .aa-value {
		font-weight: bold;
		color: #b00020;
	}
	.bar-track {
		background: #eee;
		border-radius: 4px;
		height: 0.75rem;
		overflow: hidden;
	}
	.bar-fill {
		display: block;
		height: 100%;
		background: #3a7d44;
	}
	.limiting .bar-fill {
		background: #b00020;
	}
</style>
