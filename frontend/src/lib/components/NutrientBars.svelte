<script lang="ts">
	import InfoLink from '$lib/components/InfoLink.svelte';
	import type { NutrientAmount } from '$lib/types';

	let {
		nutrients,
		per = 'per 100g',
		absorbedIronMg = null
	}: { nutrients: NutrientAmount[]; per?: string; absorbedIronMg?: number | null } = $props();

	const NUTRIENT_GROUPS: { label: string; keys: string[] }[] = [
		{
			label: 'Fat-soluble vitamins',
			keys: ['vitamin_a', 'retinol', 'beta_carotene', 'vitamin_d', 'vitamin_e', 'vitamin_k1', 'vitamin_k2']
		},
		{
			label: 'Water-soluble vitamins',
			keys: [
				'vitamin_c', 'thiamin', 'riboflavin', 'niacin', 'pantothenic_acid',
				'vitamin_b6', 'biotin', 'folate', 'vitamin_b12', 'choline'
			]
		},
		{
			label: 'Minerals',
			keys: [
				'calcium', 'iron', 'iron_heme', 'iron_non_heme', 'magnesium', 'phosphorus',
				'potassium', 'zinc', 'copper', 'manganese', 'selenium', 'iodine'
			]
		},
		{
			label: 'Dietary fibre',
			keys: [
				'fiber_total', 'fiber_soluble', 'fiber_insoluble',
				'resistant_starch', 'inulin', 'beta_glucan'
			]
		},
		{
			label: 'Fats',
			keys: [
				'fat_total', 'saturated_fat', 'monounsaturated_fat', 'polyunsaturated_fat',
				'ala', 'epa', 'dha', 'la', 'arachidonic_acid'
			]
		}
	];

	function groupNutrients(keys: string[]): NutrientAmount[] {
		const byKey = new Map(nutrients.map((n) => [n.key, n]));
		return keys.map((k) => byKey.get(k)).filter((n): n is NutrientAmount => !!n);
	}

	// energy is a flagship single figure (esp. on the diary's "per day"
	// view, where it's consumed-vs-personalized-target), not one row among
	// many vitamin/mineral bars — shown separately, excluded from the
	// generic groups below.
	const energy = $derived(nutrients.find((n) => n.key === 'energy'));

	const omega3to6Ratio = $derived.by(() => {
		const byKey = new Map(nutrients.map((n) => [n.key, n.amount]));
		const n3 = (byKey.get('ala') ?? 0) + (byKey.get('epa') ?? 0) + (byKey.get('dha') ?? 0);
		const n6 = (byKey.get('la') ?? 0) + (byKey.get('arachidonic_acid') ?? 0);
		if (n3 <= 0 || n6 <= 0) return null;
		return n6 / n3;
	});
</script>

{#if energy}
	<div class="energy" title={energy.drv_source ?? undefined}>
		<strong>{energy.amount.toFixed(0)} kcal</strong>
		<span class="muted">{per}</span>
		{#if energy.adult_drv !== null}
			<span class="muted">
				of {energy.adult_drv.toFixed(0)} kcal target ({energy.percent_drv?.toFixed(0)}%)
			</span>
		{:else if per === 'per day'}
			<span class="muted">— set weight, height, sex, birth year &amp; activity level in your profile for a target</span>
		{/if}
	</div>
{/if}

{#if nutrients.length > 0}
	<h2>
		Vitamins, minerals &amp; fibre <span class="muted">({per})</span>
		<InfoLink href="/methodology#vitamins-minerals" label="Where these reference values come from" />
	</h2>
	{#each NUTRIENT_GROUPS as group (group.label)}
		{@const rows = groupNutrients(group.keys)}
		{#if rows.length > 0}
			<section>
				<h3>
					{group.label}
					{#if group.label === 'Fats' && omega3to6Ratio !== null}
						<span class="muted">(n-3 : n-6 = 1 : {omega3to6Ratio.toFixed(1)})</span>
					{/if}
				</h3>
				<ul class="bars">
					{#each rows as n (n.key)}
						{@const isGap = per === 'per day' && n.percent_drv !== null && n.percent_drv < 50}
						<li class:gap={isGap} title={n.drv_source ?? undefined}>
							<span class="aa-name">{n.name}</span>
							<span class="bar-track">
								{#if n.percent_drv !== null}
									<span class="bar-fill" style="width: {Math.min(n.percent_drv, 150) / 1.5}%"></span>
								{/if}
							</span>
							<span class="aa-value">
								{n.amount < 10 ? n.amount.toFixed(2) : n.amount.toFixed(0)}
								{n.unit}
								{#if n.percent_drv !== null}
									<span class="muted">({n.percent_drv.toFixed(0)}% DRV)</span>
								{/if}
							</span>
							{#if n.key === 'iron'}
								{#if absorbedIronMg !== null}
									<span class="muted absorbed-note">
										&asymp;{absorbedIronMg.toFixed(2)}mg actually estimated absorbed today — see
										Bioavailability estimate below for why that's so much lower than the raw total.
									</span>
								{:else}
									<span class="muted absorbed-note">
										Raw content — how much is actually absorbed depends on the rest of the meal
										(haem vs non-haem, vitamin C present); log this in the Diary for a real
										per-meal absorption estimate.
									</span>
								{/if}
							{/if}
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/each}
	<p class="muted">
		Daily reference values come from UK RNI, EFSA PRI, or US RDA/AI depending on the nutrient, and
		reflect your profile (sex, pregnancy/lactation) when signed in with one set. Hover a nutrient
		for its specific source.
		{#if per === 'per day'}
			Nutrients under 50% of target for the day are highlighted.
		{/if}
	</p>

	<details class="sourcing-detail">
		<summary>Show sourcing &amp; confidence for every nutrient above</summary>
		<div class="table-scroll">
			<table>
				<thead>
					<tr>
						<th>Nutrient</th>
						<th>Confidence</th>
						<th>Source</th>
					</tr>
				</thead>
				<tbody>
					{#each nutrients.filter((n) => n.drv_source) as n (n.key)}
						<tr>
							<td>{n.name}</td>
							<td>
								<span class="confidence-badge confidence-{n.drv_confidence}">
									{n.drv_confidence?.replaceAll('_', ' ')}
								</span>
							</td>
							<td class="muted">{n.drv_source}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</details>
{/if}

<style>
	.energy {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-bottom: var(--space-4);
		font-size: var(--font-size-md);
		font-variant-numeric: tabular-nums;
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
		grid-template-columns: 12rem 1fr 9rem;
		align-items: center;
		gap: var(--space-3);
	}
	.bars .aa-value {
		white-space: nowrap;
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.absorbed-note {
		grid-column: 1 / -1;
		font-size: var(--font-size-xs);
		font-style: italic;
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
	.gap .aa-name,
	.gap .aa-value {
		font-weight: var(--font-weight-bold);
		color: var(--color-danger);
	}
	.gap .bar-fill {
		background: var(--color-danger);
	}
	.sourcing-detail {
		margin-top: var(--space-3);
		font-size: var(--font-size-sm);
	}
	.sourcing-detail table {
		margin-top: var(--space-2);
	}
	.confidence-badge {
		display: inline-block;
		font-size: var(--font-size-xs);
		padding: 0.1em 0.5em;
		border-radius: var(--radius-full);
		white-space: nowrap;
		text-transform: capitalize;
	}
	.confidence-live_confirmed {
		background: var(--color-success-subtle);
		color: var(--color-success);
	}
	.confidence-secondary_source {
		background: var(--color-surface-muted);
		color: var(--color-text-muted);
	}
	.confidence-personalized_calculation {
		background: var(--color-primary-subtle);
		color: var(--color-primary);
	}
</style>
