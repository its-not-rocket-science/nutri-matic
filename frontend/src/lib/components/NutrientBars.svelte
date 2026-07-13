<script lang="ts">
	import type { NutrientAmount } from '$lib/types';

	let { nutrients, per = 'per 100g' }: { nutrients: NutrientAmount[]; per?: string } = $props();

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

	const omega3to6Ratio = $derived.by(() => {
		const byKey = new Map(nutrients.map((n) => [n.key, n.amount]));
		const n3 = (byKey.get('ala') ?? 0) + (byKey.get('epa') ?? 0) + (byKey.get('dha') ?? 0);
		const n6 = (byKey.get('la') ?? 0) + (byKey.get('arachidonic_acid') ?? 0);
		if (n3 <= 0 || n6 <= 0) return null;
		return n6 / n3;
	});
</script>

{#if nutrients.length > 0}
	<h2>Vitamins, minerals &amp; fibre <span class="muted">({per})</span></h2>
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
						<li class:gap={isGap}>
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
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/each}
	<p class="muted">
		% DRV is against a single generic-adult reference value, not adjusted for your age, sex, or
		life stage.
		{#if per === 'per day'}
			Nutrients under 50% of target for the day are highlighted.
		{/if}
	</p>
{/if}

<style>
	.muted {
		color: #666;
		font-size: 0.9em;
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
	.gap .aa-name,
	.gap .aa-value {
		font-weight: bold;
		color: #b00020;
	}
	.gap .bar-fill {
		background: #b00020;
	}
</style>
